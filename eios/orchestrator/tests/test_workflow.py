"""Phases 3–15 regression checks, restricted to a disposable database.

Docker and model-provider boundaries are mocked here. Live experiments are
verified separately; mocked success must never be reported as live recovery.
"""
import copy
import json
import os
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi import HTTPException
import psycopg

import auth
import db
from auth_recovery_migrate import migrate as recovery_migrate
from intelligence.migrate import migrate as intelligence_migrate
from phase1_migrate import migrate as registry_migrate, service_id
from telemetry.migrate import migrate as telemetry_migrate
from workflow_migrate import migrate
from workflow_store import rows, one, blob, now, audit, transition, detail
from workflow_topology import health
from workflow_analysis import anomaly, correlate, rank, detect, _related
from workflow_runtime import propose, decide, execute, verify, DockerRuntimeAdapter
from workflow_investigation import investigate, retrieve, TOOLS
from workflow_evaluation import evaluate
from workflow_experiments import start, cleanup


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'eios_workflow_test' not in os.environ.get('EIOS_POSTGRES_DSN', ''):
            raise RuntimeError('Use a disposable eios_workflow_test database')
        db.pool.open(wait=True)
        with db.pool.connection() as conn:
            conn.execute(Path('/app/db/init.sql').read_text(), prepare=False)
            intelligence_migrate(conn)
            registry_migrate(conn)
            recovery_migrate(conn)
            telemetry_migrate(conn)
            migrate(conn)

    @classmethod
    def tearDownClass(cls):
        db.pool.close()

    def setUp(self):
        self.app = uuid4()
        self.clock = now()
        self.actor = 'verification-' + uuid4().hex[:12]
        self.sids = {name: service_id(self.app, name) for name in ('payment', 'checkout', 'unrelated')}
        with db.pool.connection() as conn:
            conn.execute("INSERT INTO applications(application_id,name,environment,runtime_type,discovery_scope) VALUES(%s,%s,'test','docker',%s)",
                         (self.app, self.actor, blob({'compose_project': self.actor})))
            conn.execute("INSERT INTO users(user_id,username,password_hash,role) VALUES(%s,%s,%s,'administrator')",
                         (uuid4(), self.actor, auth.password_hash('disposable-verification-password')))
            for name, sid in self.sids.items():
                conn.execute('INSERT INTO services(service_id,application_id,name,runtime_identifier) VALUES(%s,%s,%s,%s)',
                             (sid, self.app, name, name))
        self.view = {'state': 'available', 'application_id': str(self.app), 'observed_at': self.clock.isoformat(),
                     'services': [self.node(name) for name in self.sids], 'edges': []}

    def node(self, name, status='critical', at=None):
        at = at or self.clock
        return {'service_id': str(self.sids[name]), 'service': name, 'status': status,
                'runtime_state': 'online', 'telemetry_state': 'fresh', 'labels': {},
                'metrics': {'request_rate_per_sec': 3, 'error_fraction': .5 if status == 'critical' else 0,
                            'latency_p95_ms': 100, 'cpu_cores': .1, 'memory_fraction': .2},
                'metric_timestamps': {'error_fraction': at.isoformat(), 'request_rate_per_sec': at.isoformat(),
                                      'latency_p95_ms': at.isoformat()}, 'evidence_event_ids': [], 'runtime_instances': []}

    def add_anomaly(self, conn, name='payment', identity=None, values=None, at=None):
        anomaly(conn, self.app, self.sids[name], 'verification:error:v1', 'static', at or self.clock,
                {'error_fraction': .5} if values is None else values, {}, score=.9, severity='critical', identity=identity)

    def incident(self, ranked=True):
        with db.pool.connection() as conn:
            self.add_anomaly(conn)
            correlate(conn, self.app, self.view)
            identity = one('SELECT incident_id FROM operational_incidents WHERE application_id=%s', (self.app,), conn)['incident_id']
            if ranked:
                rank(conn, self.app, identity, self.view)
        return identity

    def approved(self):
        incident_id = self.incident()
        proposal = propose(self.app, incident_id, self.actor)
        decide(self.app, proposal['proposal_id'], self.actor, 'administrator', 'approve', 'Isolated test')
        return incident_id, proposal['proposal_id']

    def observing(self):
        incident_id, proposal_id = self.approved()
        with patch('workflow_runtime.snapshot', return_value=self.view), patch('workflow_runtime.DockerRuntimeAdapter') as adapter:
            adapter.return_value.execute.return_value = {'command_accepted': True, 'recovery_verified': False}
            result = execute(self.app, proposal_id, self.actor)
            self.assertEqual(result['state'], 'VERIFYING')
        verification = one('SELECT * FROM recovery_verifications WHERE incident_id=%s', (incident_id,))
        return incident_id, verification

    def test_migration_replay_preserves_history_and_versions(self):
        identity = self.incident()
        with db.pool.connection() as conn:
            before = conn.execute('SELECT count(*) FROM incident_timeline WHERE incident_id=%s', (identity,)).fetchone()[0]
            migrate(conn)
            migrate(conn)
            self.assertEqual(conn.execute("SELECT count(*) FROM schema_migrations WHERE version='workflow-v1'").fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM incident_timeline WHERE incident_id=%s', (identity,)).fetchone()[0], before)

    def test_health_offline_stale_and_unknown_are_distinct(self):
        self.assertEqual(health({}, 'offline', 'not_observed', 'unknown')[:3], ('offline', 'Confirmed stopped or missing runtime', 0))
        self.assertIsNone(health({}, 'unknown', 'fresh', 'healthy')[2])
        self.assertEqual(health({}, 'online', 'stale', 'healthy')[0], 'stale')
        self.assertEqual(health({}, 'starting', 'fresh', 'healthy')[0], 'unknown')

    def test_health_penalties_are_reproducible(self):
        result = health({'error_fraction': .2, 'cpu_cores': 1.5}, 'online', 'fresh', 'healthy')
        self.assertEqual(result[0], 'critical')
        self.assertEqual(result[2], 20)
        self.assertEqual(sum(result[3].values()), 80)

    def test_anomaly_replay_is_idempotent_and_provenance_survives(self):
        with db.pool.connection() as conn:
            self.add_anomaly(conn, identity='same-observation')
            self.add_anomaly(conn, identity='same-observation')
        found = rows('SELECT * FROM operational_anomalies WHERE application_id=%s', (self.app,))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['current_values']['error_fraction'], .5)
        self.assertEqual(found[0]['category'], 'static')

    def test_correlation_groups_dependency_symptoms_but_not_unrelated_services(self):
        self.view['edges'] = [{'source': 'checkout', 'target': 'payment', 'state': 'observed'}]
        with db.pool.connection() as conn:
            for name in self.sids:
                self.add_anomaly(conn, name)
            correlate(conn, self.app, self.view)
            correlate(conn, self.app, self.view)
        self.assertEqual(len(rows('SELECT * FROM operational_incidents WHERE application_id=%s', (self.app,))), 2)
        self.assertEqual(len(rows('SELECT * FROM operational_anomalies WHERE application_id=%s', (self.app,))), 3)
        self.assertEqual(len(rows('SELECT l.* FROM incident_anomalies l JOIN operational_incidents i USING(incident_id) WHERE i.application_id=%s', (self.app,))), 3)

    def test_stale_edges_do_not_establish_correlation(self):
        a, b = ({'service_id': self.sids[name], 'evidence': {}} for name in ('payment', 'checkout'))
        self.view['edges'] = [{'source': 'checkout', 'target': 'payment', 'state': 'stale'}]
        self.assertIsNone(_related(a, b, self.view))

    def test_shared_trace_establishes_correlation(self):
        a, b = ({'service_id': self.sids[name], 'evidence': {'trace_ids': ['real-test-trace']}} for name in ('payment', 'checkout'))
        self.assertEqual(_related(a, b, self.view), 'shared_trace')

    def test_rca_repeated_evidence_produces_one_explainable_ranking(self):
        identity = self.incident()
        with db.pool.connection() as conn:
            rank(conn, self.app, identity, self.view)
        rankings = rows('SELECT * FROM rca_rankings WHERE incident_id=%s', (identity,))
        self.assertEqual(len(rankings), 1)
        top = rankings[0]['candidates'][0]
        self.assertEqual(top['service_id'], str(self.sids['payment']))
        self.assertEqual(top['score'], sum(top['score_breakdown'].values()))
        self.assertEqual(rankings[0]['state'], 'ranked')

    def test_rca_abstains_without_direct_evidence(self):
        with db.pool.connection() as conn:
            self.add_anomaly(conn, values={})
            correlate(conn, self.app, self.view)
            identity = one('SELECT incident_id FROM operational_incidents WHERE application_id=%s', (self.app,), conn)['incident_id']
            rank(conn, self.app, identity, self.view)
        self.assertEqual(one('SELECT state FROM rca_rankings WHERE incident_id=%s', (identity,))['state'], 'abstained')

    def test_invalid_lifecycle_transition_is_rejected(self):
        identity = self.incident()
        with self.assertRaises(HTTPException), db.pool.connection() as conn:
            transition(conn, identity, 'RESOLVED')
        self.assertEqual(detail(self.app, identity)['state'], 'ROOT_CAUSE_IDENTIFIED')

    def test_unapproved_execution_never_touches_docker(self):
        identity = self.incident()
        proposal = propose(self.app, identity, self.actor)
        with patch('workflow_runtime.snapshot', return_value=self.view), patch('workflow_runtime.DockerRuntimeAdapter') as adapter:
            with self.assertRaises(HTTPException):
                execute(self.app, proposal['proposal_id'], self.actor)
            adapter.assert_not_called()

    def test_operator_cannot_approve_service_change_and_rejection_persists(self):
        identity = self.incident()
        proposal = propose(self.app, identity, self.actor)
        with self.assertRaises(HTTPException) as caught:
            decide(self.app, proposal['proposal_id'], 'operator', 'operator', 'approve', '')
        self.assertEqual(caught.exception.status_code, 403)
        decide(self.app, proposal['proposal_id'], self.actor, 'administrator', 'reject', 'Do not restart')
        self.assertEqual(detail(self.app, identity)['proposals'][0]['decision'], 'reject')

    def test_expired_and_cross_application_proposals_are_rejected(self):
        identity, pid = self.approved()
        with self.assertRaises(HTTPException):
            decide(uuid4(), pid, self.actor, 'administrator', 'approve', '')
        with db.pool.connection() as conn:
            conn.execute("UPDATE remediation_proposals SET expires_at=NOW()-INTERVAL '1 second' WHERE proposal_id=%s", (pid,))
        with patch('workflow_runtime.snapshot', return_value=self.view), patch('workflow_runtime.DockerRuntimeAdapter') as adapter:
            with self.assertRaises(HTTPException):
                execute(self.app, pid, self.actor)
            adapter.assert_not_called()

    def test_execution_is_once_and_success_only_enters_verifying(self):
        identity, pid = self.approved()
        with patch('workflow_runtime.snapshot', return_value=self.view), patch('workflow_runtime.DockerRuntimeAdapter') as adapter:
            adapter.return_value.execute.return_value = {'command_accepted': True, 'recovery_verified': False}
            execute(self.app, pid, self.actor)
            with self.assertRaises(HTTPException):
                execute(self.app, pid, self.actor)
            self.assertEqual(adapter.return_value.execute.call_count, 1)
        self.assertEqual(detail(self.app, identity)['state'], 'VERIFYING')

    def test_interrupted_claim_is_escalated_and_never_reexecutes_docker(self):
        identity,pid=self.approved()
        with patch('workflow_runtime.snapshot',return_value=self.view),patch('workflow_runtime.DockerRuntimeAdapter') as adapter:
            adapter.return_value.execute.side_effect=SystemExit('simulated process interruption')
            with self.assertRaises(SystemExit):
                execute(self.app,pid,self.actor)
            self.assertEqual(adapter.return_value.execute.call_count,1)
        with db.pool.connection() as conn:
            conn.execute("UPDATE remediation_executions SET started_at=NOW()-INTERVAL '6 minutes' WHERE proposal_id=%s",(pid,))
        from workflow_worker import observe_application
        import catalog
        with patch('workflow_worker.collect',return_value=self.view),patch('workflow_worker.detect'),patch('workflow_worker.correlate'):
            observe_application(catalog.application(self.app),{},lambda payload:None)
        execution=one('SELECT state FROM remediation_executions WHERE proposal_id=%s',(pid,))
        self.assertEqual(execution['state'],'uncertain')
        self.assertEqual(detail(self.app,identity)['state'],'ESCALATED')
        with patch('workflow_runtime.snapshot',return_value=self.view),patch('workflow_runtime.DockerRuntimeAdapter') as adapter:
            with self.assertRaises(HTTPException):
                execute(self.app,pid,self.actor)
            adapter.assert_not_called()

    def test_protected_runtime_is_rejected_before_docker_lookup(self):
        with db.pool.connection() as conn:
            conn.execute("UPDATE services SET runtime_identifier='eios-postgres' WHERE service_id=%s", (self.sids['payment'],))
        with patch('docker_router._get_client') as client, self.assertRaises(HTTPException) as caught:
            DockerRuntimeAdapter().resolve(self.app, self.sids['payment'])
        self.assertEqual(caught.exception.status_code, 403)
        client.assert_not_called()

    def test_sustained_recovery_requires_distinct_fresh_observations(self):
        identity, verification = self.observing()
        created = verification['created_at']
        for offset in (10, 10, 40, 70):
            at = created + timedelta(seconds=offset)
            view = {**self.view, 'observed_at': at.isoformat(), 'services': [self.node('payment', 'healthy', at)]}
            with patch('workflow_runtime.now', return_value=at), db.pool.connection() as conn:
                verify(conn, self.app, view)
            if offset < 70:
                self.assertEqual(detail(self.app, identity)['state'], 'VERIFYING')
        saved = one('SELECT * FROM recovery_verifications WHERE incident_id=%s', (identity,))
        self.assertEqual(len(saved['samples']), 3)
        self.assertEqual(saved['outcome'], 'RECOVERED')
        self.assertEqual(detail(self.app, identity)['state'], 'RESOLVED')

    def test_missing_telemetry_is_inconclusive_not_recovered(self):
        identity, verification = self.observing()
        view = {**self.view, 'services': []}
        with patch('workflow_runtime.now', return_value=verification['deadline'] + timedelta(seconds=1)), db.pool.connection() as conn:
            verify(conn, self.app, view)
        self.assertEqual(one('SELECT outcome FROM recovery_verifications WHERE incident_id=%s', (identity,))['outcome'], 'INCONCLUSIVE')
        self.assertEqual(detail(self.app, identity)['state'], 'ESCALATED')

    def test_post_deadline_samples_cannot_establish_recovery(self):
        identity,verification=self.observing()
        for offset in (10,40,190):
            at=verification['created_at']+timedelta(seconds=offset)
            view={**self.view,'observed_at':at.isoformat(),'services':[self.node('payment','healthy',at)]}
            with patch('workflow_runtime.now',return_value=at),db.pool.connection() as conn:
                verify(conn,self.app,view)
        saved=one('SELECT * FROM recovery_verifications WHERE incident_id=%s',(identity,))
        self.assertEqual(len(saved['samples']),2)
        self.assertNotEqual(saved['outcome'],'RECOVERED')
        self.assertEqual(detail(self.app,identity)['state'],'ESCALATED')

    def test_ineffective_remediation_fails_without_resolving(self):
        identity, verification = self.observing()
        for offset in (10, 40, 70, 190):
            at = verification['created_at'] + timedelta(seconds=offset)
            view = {**self.view, 'observed_at': at.isoformat(), 'services': [self.node('payment', 'critical', at)]}
            with patch('workflow_runtime.now', return_value=at), db.pool.connection() as conn:
                verify(conn, self.app, view)
        self.assertEqual(one('SELECT outcome FROM recovery_verifications WHERE incident_id=%s', (identity,))['outcome'], 'FAILED')
        self.assertEqual(detail(self.app, identity)['state'], 'ESCALATED')

    def test_unconfigured_ai_persists_failure_without_blocking_incident(self):
        identity = self.incident()
        with patch.dict(os.environ, {'EIOS_INVESTIGATION_URL': '', 'EIOS_INVESTIGATION_MODEL': ''}):
            result = investigate(self.app, identity, self.actor)
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(detail(self.app, identity)['state'], 'ROOT_CAUSE_IDENTIFIED')
        self.assertEqual(len(detail(self.app, identity)['investigations']), 1)

    def test_ai_tools_reject_actions_and_cross_application_services(self):
        identity = self.incident()
        self.assertTrue(all('docker' not in name and 'exec' not in name for name in TOOLS))
        with self.assertRaises(ValueError):
            retrieve(self.app, identity, 'restart_service', {})
        with self.assertRaises(ValueError):
            retrieve(self.app, identity, 'get_service_metrics', {'service_id': str(uuid4())})

    def test_ai_invalid_citations_cannot_be_saved_as_completed(self):
        identity = self.incident()
        output = {'summary': 'Synthetic provider contract test', 'affected_service_ids': [str(self.sids['payment'])],
                  'probable_root_cause_service_id': str(self.sids['payment']),
                  'supporting_evidence': [{'text': 'Unsupported claim', 'evidence_ids': [str(uuid4())]}],
                  'conflicting_evidence': [], 'suggested_next_step': 'Inspect evidence', 'uncertainty': 'Test only'}
        provider = MagicMock()
        provider.post.side_effect = [
            SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'message': {'role': 'assistant', 'tool_calls': [
                {'function': {'name': 'get_incident', 'arguments': {}}}]}}),
            SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'message': {'content': json.dumps(output)}}),
        ]
        with patch.dict(os.environ, {'EIOS_INVESTIGATION_URL': 'http://test-provider', 'EIOS_INVESTIGATION_MODEL': 'contract-test'}), patch('workflow_investigation.httpx.Client') as client:
            client.return_value.__enter__.return_value = provider
            result = investigate(self.app, identity, self.actor)
        self.assertEqual(result['state'], 'unavailable')

    def test_audit_history_rejects_update_delete_and_truncate(self):
        with db.pool.connection() as conn:
            audit(conn, self.actor, 'verification.audit', {'password': 'password=should-be-redacted'})
        row = one('SELECT * FROM governance_audit WHERE actor=%s', (self.actor,))
        self.assertNotIn('should-be-redacted', str(row['detail']))
        for sql in ('UPDATE governance_audit SET action=action WHERE sequence=%s',
                    'DELETE FROM governance_audit WHERE sequence=%s'):
            with self.assertRaises(psycopg.Error), db.pool.connection() as conn:
                conn.execute(sql, (row['sequence'],))
        with self.assertRaises(psycopg.Error), db.pool.connection() as conn:
            conn.execute('TRUNCATE governance_audit')

    def test_groq_adapter_preserves_tool_call_ids_and_validates_evidence(self):
        identity = self.incident()
        output = {'summary': 'Synthetic Groq contract test', 'affected_service_ids': [str(self.sids['payment'])],
                  'probable_root_cause_service_id': str(self.sids['payment']),
                  'supporting_evidence': [{'text': 'The incident contains measured errors', 'evidence_ids': [str(identity)]}],
                  'conflicting_evidence': [], 'suggested_next_step': 'Review evidence', 'uncertainty': 'Test only'}
        provider = MagicMock()
        provider.post.side_effect = [
            SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'choices': [{'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call-test', 'type': 'function',
                'function': {'name': 'get_incident', 'arguments': '{}'}}]}}]}),
            SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'choices': [{'message': {'role': 'assistant', 'content': json.dumps(output)}}]}),
        ]
        with patch.dict(os.environ, {'EIOS_INVESTIGATION_PROVIDER': 'groq', 'GROQ_API_KEY': 'disposable-test-value',
                                    'EIOS_INVESTIGATION_URL': '', 'EIOS_INVESTIGATION_MODEL': ''}), patch('workflow_investigation.httpx.Client') as client:
            client.return_value.__enter__.return_value = provider
            result = investigate(self.app, identity, self.actor)
        self.assertEqual(result['state'], 'completed')
        tool_messages=[m for m in provider.post.call_args_list[1].kwargs['json']['messages'] if m['role']=='tool']
        self.assertEqual(tool_messages[-1]['tool_call_id'], 'call-test')
        self.assertNotIn('tools',provider.post.call_args_list[1].kwargs['json'])
        saved = detail(self.app, identity)['investigations'][0]
        self.assertEqual(saved['provider'], 'groq')
        self.assertNotIn('disposable-test-value', json.dumps(saved, default=str))

    def test_baseline_does_not_create_an_injected_fault_window(self):
        body = SimpleNamespace(scenario='baseline', service_id=self.sids['payment'], duration_seconds=15,
                               load_profile={'mode': 'existing'}, variant=None)
        with patch('workflow_experiments.flags.available', return_value=False):
            run = start(self.app, body, self.actor)
        try:
            self.assertIsNone(run['fault_window_id'])
        finally:
            cleanup(run['experiment_id'], self.actor)

    def test_evaluation_requires_completed_runs_in_same_application(self):
        with self.assertRaises(HTTPException):
            evaluate(self.app, [uuid4()], self.actor)

    def test_evaluation_reproduces_positive_negative_episode_counts_and_latency(self):
        baseline_id, fault_id = uuid4(), uuid4()
        starts = (self.clock-timedelta(minutes=15), self.clock-timedelta(minutes=2))
        with db.pool.connection() as conn:
            for eid, scenario, start_at in zip((baseline_id, fault_id), ('baseline', 'paymentFailure'), starts):
                end_at = start_at+timedelta(seconds=60)
                conn.execute('''INSERT INTO experiment_runs(experiment_id,application_id,service_id,scenario,
                    expected_service_id,duration_seconds,load_profile,state,prior_state,actor,started_at,ended_at)
                    VALUES(%s,%s,%s,%s,%s,60,'{}','COMPLETED','{}',%s,%s,%s)''',
                    (eid, self.app, self.sids['payment'], scenario, self.sids['payment'], self.actor, start_at, end_at))
                for offset in (10, 40):
                    conn.execute('INSERT INTO topology_history(application_id,observed_at,snapshot) VALUES(%s,%s,%s)',
                                 (self.app, start_at+timedelta(seconds=offset), blob(self.view)))
            self.add_anomaly(conn, at=starts[1]+timedelta(seconds=5))
            conn.execute('UPDATE operational_anomalies SET detected_at=%s WHERE application_id=%s',
                         (starts[1]+timedelta(seconds=10), self.app))
            correlate(conn, self.app, self.view)
            iid = one('SELECT incident_id FROM operational_incidents WHERE application_id=%s', (self.app,), conn)['incident_id']
            rank(conn, self.app, iid, self.view)
        first = evaluate(self.app, [baseline_id, fault_id], self.actor)
        second = evaluate(self.app, [baseline_id, fault_id], self.actor)
        self.assertEqual(first['metrics'], second['metrics'])
        self.assertEqual(first['inputs'], second['inputs'])
        result = first['metrics']
        for category in ('static', 'hybrid'):
            self.assertEqual({k: result['detectors'][category][k] for k in ('TP','FP','FN','TN')},
                             {'TP': 1, 'FP': 0, 'FN': 0, 'TN': 1})
            self.assertEqual(result['detectors'][category]['F1'], 1)
        self.assertEqual(result['MTTD_seconds'], 10)
        self.assertEqual(result['RCA_top1_accuracy'], 1)
        self.assertEqual(result['detectors']['ml']['excluded'], 2)

    def test_cleanup_failure_keeps_fault_open_and_retry_restores_exact_variant(self):
        eid, wid = uuid4(), uuid4()
        with db.pool.connection() as conn:
            conn.execute("INSERT INTO fault_windows(window_id,flag_key,variant,started_at) VALUES(%s,'paymentFailure','on',NOW())", (wid,))
            conn.execute('''INSERT INTO experiment_runs(experiment_id,application_id,service_id,scenario,
                expected_service_id,duration_seconds,load_profile,state,fault_window_id,prior_state,actor,started_at)
                VALUES(%s,%s,%s,'paymentFailure',%s,60,'{}','RUNNING',%s,%s,%s,NOW())''',
                (eid,self.app,self.sids['payment'],self.sids['payment'],wid,
                 blob({'flag_key':'paymentFailure','variant':'off','load':{'changed':False}}),self.actor))
        try:
            with patch('workflow_experiments.flags.set_variant', side_effect=OSError('test restore failure')):
                failed = cleanup(eid, self.actor)
            self.assertEqual(failed['state'], 'CLEANUP_FAILED')
            self.assertIsNone(one('SELECT ended_at FROM fault_windows WHERE window_id=%s',(wid,))['ended_at'])
            with patch('workflow_experiments.flags.set_variant') as restore:
                recovered = cleanup(eid, self.actor)
            restore.assert_called_once_with('paymentFailure','off')
            self.assertEqual(recovered['state'], 'COMPLETED')
        finally:
            with patch('workflow_experiments.flags.set_variant'):
                cleanup(eid, self.actor)

    def test_runtime_rejects_unsupported_action(self):
        with self.assertRaises(HTTPException) as caught:
            DockerRuntimeAdapter().execute('arbitrary_shell', MagicMock())
        self.assertEqual(caught.exception.status_code, 400)

    def test_statistical_detection_requires_distinct_minute_history(self):
        view = {**self.view, 'services': [self.node('payment', 'healthy')]}
        node = view['services'][0]
        node['metrics'] = {'cpu_cores': .7}
        node['metric_timestamps'] = {'cpu_cores': self.clock.isoformat()}
        with db.pool.connection() as conn:
            detect(conn, self.app, view)
            self.assertEqual(rows('SELECT * FROM operational_anomalies WHERE application_id=%s',(self.app,),conn),[])
            # Repeated observations inside one minute must not train a baseline.
            for offset in list(range(20))+[minute*60 for minute in range(3,16)]:
                at = self.clock-timedelta(seconds=offset+180)
                conn.execute('''INSERT INTO events(event_id,schema_version,domain,source,observed_at,ingested_at,
                    entity_kind,entity_id,entity_service,application_id,service_id,metrics)
                    VALUES(%s,'1.0','infrastructure','prometheus',%s,NOW(),'service','payment','payment',%s,%s,%s)''',
                    (uuid4(),at,self.app,self.sids['payment'],blob({'cpu_cores':.1})))
            detect(conn,self.app,view)
        found = rows('SELECT * FROM operational_anomalies WHERE application_id=%s',(self.app,))
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['category'],'statistical')
        self.assertGreaterEqual(found[0]['baseline']['samples'],12)
        self.assertEqual(found[0]['current_values']['cpu_cores'],.7)

    def test_legacy_fault_window_invalidates_a_baseline_negative_control(self):
        eid,wid=uuid4(),uuid4()
        start_at=self.clock-timedelta(minutes=2)
        with db.pool.connection() as conn:
            conn.execute('''INSERT INTO experiment_runs(experiment_id,application_id,service_id,scenario,
                expected_service_id,duration_seconds,load_profile,state,prior_state,actor,started_at,ended_at)
                VALUES(%s,%s,%s,'baseline',%s,60,'{}','COMPLETED','{}',%s,%s,%s)''',
                (eid,self.app,self.sids['payment'],self.sids['payment'],self.actor,start_at,start_at+timedelta(seconds=60)))
            for offset in (10,40):
                conn.execute('INSERT INTO topology_history(application_id,observed_at,snapshot) VALUES(%s,%s,%s)',
                    (self.app,start_at+timedelta(seconds=offset),blob(self.view)))
            conn.execute("INSERT INTO fault_windows(window_id,flag_key,started_at,ended_at) VALUES(%s,'legacy-test',%s,%s)",
                (wid,start_at-timedelta(minutes=1),start_at-timedelta(seconds=30)))
        with patch.dict(os.environ,{'EIOS_FLAGD_APPLICATION_ID':str(self.app)}):
            result=evaluate(self.app,[eid],self.actor)
        self.assertFalse(result['metrics']['episodes'][0]['eligible'])
        self.assertEqual(result['metrics']['detectors']['static']['excluded'],1)


if __name__ == '__main__':
    unittest.main()
