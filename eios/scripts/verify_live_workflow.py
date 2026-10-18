"""Explicit, resumable local verification. Never stores credentials in evidence.

Run inside the orchestrator container. Faults use the supported Experiment API
and its persisted cleanup deadline. This script does not reset application data.
"""
import argparse
import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import auth
import db
from phase1_migrate import DEFAULT_APPLICATION_ID
from workflow_store import audit, clean, rows

EVIDENCE = Path(os.getenv('EIOS_VERIFICATION_EVIDENCE_FILE','/tmp/eios-live-verification-20261018.json'))
APP = str(DEFAULT_APPLICATION_ID)
BASE = f'/api/applications/{APP}/operations'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def compact_run(run):
    artifacts=run.get('artifacts') or {}
    linked=artifacts.get('linked') or {}
    references={name:[item[key] for item in linked.get(name,[]) if key in item]
                for name,key in (('anomalies','anomaly_id'),('rca','ranking_id'),
                                 ('remediation','proposal_id'),('verification','verification_id'))}
    references['incident_ids']=linked.get('incident_ids',[])
    return {**run,'artifacts':{key:value for key,value in artifacts.items() if key!='linked'},
            'linked_record_ids':references,'artifact_scope':'Full linked records remain in PostgreSQL and the experiment API.'}


def call(client, method, path, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f'{method} {path}: expected {expected}, received {response.status_code}: {response.text[:300]}')
    return response.json() if response.content else None


def client_for(user_id):
    with db.pool.connection() as conn:
        token, _ = auth.new_session(conn, user_id)
    client = httpx.Client(base_url=os.getenv('EIOS_VERIFICATION_API','http://127.0.0.1:8000'), timeout=40,
                         headers={'Origin': 'http://127.0.0.1:5173'})
    client.cookies.set(auth.COOKIE_NAME, token)
    return client, token


def snapshot(client):
    view = call(client, 'GET', BASE+'/topology')
    return {'at': stamp(), 'state': view['state'], 'observed_at': view['observed_at'],
            'dependency_state': view.get('dependency_state'), 'edge_count': len(view.get('edges', [])),
            'services': [{key: node.get(key) for key in ('service_id', 'service', 'status', 'runtime_state',
                'telemetry_state', 'health_score', 'metrics', 'metric_timestamps')}
                for node in view['services'] if node['service'] in ('payment', 'checkout', 'ad', 'email', 'quote', 'telemetry-docs')]}


async def websocket(token):
    from websockets.asyncio.client import connect
    async with connect('ws://eios-dashboard:5173/ws', origin='http://127.0.0.1:5173',
                       additional_headers={'Cookie': f'{auth.COOKIE_NAME}={token}'}, open_timeout=10) as ws:
        data = json.loads(await asyncio.wait_for(ws.recv(), timeout=55))
        return {key: data.get(key) for key in ('type', 'application_id', 'observed_at')}


def setup(state):
    if state.get('users'):
        return {'already_initialized': True}
    state['started_at'] = stamp()
    state['users'] = {}
    for role in ('administrator', 'operator', 'viewer'):
        password, uid = secrets.token_urlsafe(24), uuid4()
        username = f'verification-20261018-{role}'
        with db.pool.connection() as conn:
            conn.execute('INSERT INTO users(user_id,username,password_hash,role) VALUES(%s,%s,%s,%s)',
                         (uid, username, auth.password_hash(password), role))
            audit(conn, username, 'verification.account_created', {'user_id': str(uid), 'role': role})
        state['users'][role] = {'user_id': str(uid), 'username': username}
        with httpx.Client(base_url='http://eios-dashboard:5173', timeout=30,
                          headers={'Origin': 'http://127.0.0.1:5173'}) as client:
            call(client, 'POST', '/api/auth/login', expected=401,
                 json={'username': username, 'password': 'incorrect-test-password'})
            call(client, 'POST', '/api/auth/login', json={'username': username, 'password': password})
            assert client.cookies.get(auth.COOKIE_NAME)
            me = call(client, 'GET', '/api/auth/me')
            state.setdefault('login', {})[role] = {'authenticated': True, 'me': me}
            call(client, 'POST', '/api/auth/logout')
            call(client, 'GET', '/api/auth/me', expected=401)
    state['database_before'] = counts()
    return {'users_created': list(state['users']), 'login_logout_verified': True}


def counts():
    tables = ('events', 'incidents', 'cases', 'approvals', 'feature_windows', 'intelligence_insights',
              'model_registry', 'operational_anomalies', 'operational_incidents', 'rca_rankings')
    result = {name: rows(f'SELECT count(*) AS n FROM {name}')[0]['n'] for name in tables}
    result['recent_events'] = rows("SELECT count(*) AS n,max(ingested_at) AS latest FROM events WHERE ingested_at>NOW()-INTERVAL '2 minutes'")[0]
    return clean(result)


def checks(client, token, state):
    call(client, 'GET', '/health')
    for path in ('/api/stats', '/api/events?limit=2', '/api/incidents?limit=2', '/api/cases',
                 '/api/intelligence/status', '/api/intelligence/insights?limit=2',
                 '/api/intelligence/models', '/api/intelligence/kpis', BASE+'/overview', BASE+'/actions'):
        body = call(client, 'GET', path)
        state.setdefault('apis', {})[path] = {'status': 200, 'items': len(body) if isinstance(body, list) else None}
    from telemetry.health import view as source_view
    sources = [{k: v for k, v in source_view(s).items() if k in ('kind', 'state', 'connection_state',
                'freshness', 'last_success_at', 'last_data_at', 'last_error')}
               for s in rows('SELECT * FROM telemetry_sources WHERE application_id=%s', (APP,))]
    state['sources'] = clean(sources)
    state['snapshot'] = snapshot(client)
    for role in ('viewer', 'operator'):
        other, other_token = client_for(state['users'][role]['user_id'])
        try:
            call(other, 'GET', '/api/governance/permissions')
            call(other, 'GET', '/api/governance/audit', expected=403)
            if role == 'viewer':
                service_id = next(n['service_id'] for n in state['snapshot']['services'] if n['service'] == 'payment')
                call(other, 'POST', BASE+'/experiments', expected=403,
                     json={'scenario': 'baseline', 'service_id': service_id, 'duration_seconds': 15})
            state.setdefault('rbac', {})[role] = 'passed'
        finally:
            other.close()
            revoke(other_token)
    state['websocket'] = asyncio.run(websocket(token))
    return {'apis': len(state['apis']), 'rbac': state['rbac'], 'websocket': state['websocket'],
            'sources': state['sources'], 'snapshot': state['snapshot']}


def revoke(token):
    with db.pool.connection() as conn:
        conn.execute('UPDATE user_sessions SET revoked_at=NOW() WHERE token_hash=%s', (auth.token_hash(token),))


def run_command(args, client, token, state):
    if args.command == 'action-guards':
        proposal_id=args.proposal
        call(client,'POST',BASE+f'/proposals/{proposal_id}/execute',expected=409)
        wrong=next(a for a in rows('SELECT application_id FROM applications WHERE application_id<>%s LIMIT 1',(APP,)))
        path=f"/api/applications/{wrong['application_id']}/operations/proposals/{proposal_id}/decision"
        call(client,'POST',path,expected=404,json={'decision':'approve','notes':'Wrong-application negative check'})
        state['live_action_guards']={'repeated_execution':409,'wrong_application':404,'proposal_id':proposal_id}
        return state['live_action_guards']
    if args.command == 'annotate':
        notes={'dc771f58-bdd7-4159-9908-c1fb4a9584b5':'Exclude warm-up: checkout failures preceded activation, payment server telemetry was initially absent, and business traffic was blocked.',
               'a7d048cd-0dc9-4466-a31d-3dabf0846257':'Exclude from final detector comparison: CPU core unit defect was found during this run and corrected before the repeated CPU experiment.',
               '008b175e-d5f9-4756-8a8f-6cbdf87141b7':'Exclude cleanup diagnostic from detector benchmarking: fault was deliberately cleared immediately after a restore-path failure/retry check.'}
        result=[]
        for eid,note in notes.items():
            if rows('SELECT 1 FROM experiment_annotations WHERE experiment_id=%s AND notes=%s',(eid,note)):
                continue
            result.append(call(client,'POST',BASE+f'/experiments/{eid}/annotations',expected=201,
                json={'verdict':'exclude','notes':note}))
        state['exclusion_annotations']=result
        return {'annotated_experiments':list(notes),'reason':'Known measurement and warm-up confounders retained explicitly'}
    if args.command == 'audit':
        page,checked=0,0
        while True:
            result=call(client,'GET',f'/api/governance/audit/integrity?after={page}&limit=10000')
            assert result['valid'],result
            checked+=result['checked']
            if result['checked']<10000:
                break
            page=result['last_sequence']
        state['audit_integrity']={'valid':True,'checked':checked}
        return state['audit_integrity']
    if args.command == 'provider-diagnostic':
        import workflow_investigation as investigation
        from unittest.mock import patch
        original=httpx.Client
        exchanges=[]
        class Capture:
            def __init__(self, *a, **kw):
                self.transport=original(*a,**kw)
            def __enter__(self):
                self.transport.__enter__()
                return self
            def __exit__(self,*a):
                return self.transport.__exit__(*a)
            def post(self,*a,**kw):
                response=self.transport.post(*a,**kw)
                body=response.json()
                choices=body.get('choices',[])
                message=choices[0].get('message',{}) if choices else {}
                calls=[]
                for item in message.get('tool_calls',[]) or []:
                    function=item.get('function',{})
                    arguments=function.get('arguments','{}')
                    try:
                        arguments=json.loads(arguments) if isinstance(arguments,str) else arguments
                        keys=sorted(arguments) if isinstance(arguments,dict) else ['non_object']
                    except ValueError:
                        keys=['invalid_json']
                    calls.append({'name':function.get('name'),'argument_keys':keys})
                exchanges.append({'status':response.status_code,'message_keys':list(message),
                    'finish_reason':choices[0].get('finish_reason') if choices else None,
                    'calls':calls,'content_length':len(message.get('content') or '')})
                return response
        with patch.object(investigation.httpx,'Client',Capture):
            result=investigation.investigate(APP,args.incident,state['users']['administrator']['username'])
        state.setdefault('provider_diagnostics',[]).append({'result':result,'exchanges':exchanges})
        return {'result':result,'exchanges':exchanges}
    if args.command == 'provider-check':
        import os
        key=os.getenv('GROQ_API_KEY','')
        result={'key_configured':bool(key),'provider':os.getenv('EIOS_INVESTIGATION_PROVIDER','auto')}
        if key:
            with httpx.Client(timeout=15,headers={'Authorization':'Bearer '+key}) as provider:
                response=provider.get('https://api.groq.com/openai/v1/models')
                result['models_http_status']=response.status_code
                if response.status_code==200:
                    result['available_models']=[m['id'] for m in response.json()['data']]
                    result['default_model_available']='llama-3.3-70b-versatile' in result['available_models']
        state['provider_check']=result
        return result
    if args.command == 'cleanup-failure':
        import workflow_experiments
        run=next(r for r in call(client,'GET',BASE+'/experiments') if r['experiment_id']==args.experiment)
        if run['scenario'] in ('baseline','serviceStop') or run['state']!='RUNNING':
            raise ValueError('Choose an active Flagd experiment for this diagnostic')
        previous=workflow_experiments.flags.CONFIG_PATH
        try:
            workflow_experiments.flags.CONFIG_PATH='/tmp/eios-verification-intentionally-missing-flagd.json'
            failed=workflow_experiments.cleanup(run['experiment_id'],'verification-cleanup-diagnostic')
            assert failed['state']=='CLEANUP_FAILED'
            assert rows('SELECT ended_at FROM fault_windows WHERE window_id=%s',(run['fault_window_id'],))[0]['ended_at'] is None
            proof={'failure_state':failed['state'],'ground_truth_kept_open':True,
                'diagnostic':'Only this diagnostic process used a missing Flagd path; the main server configuration was unchanged.'}
        finally:
            workflow_experiments.flags.CONFIG_PATH=previous
            restored=call(client,'POST',BASE+f"/experiments/{run['experiment_id']}/stop")
        assert restored['state']=='COMPLETED'
        proof.update(experiment_id=run['experiment_id'],retry_state=restored['state'],ended_at=restored['ended_at'])
        state.setdefault('cleanup_failure_checks',[]).append(proof)
        return proof
    if args.command == 'stop':
        runs=call(client,'GET',BASE+'/experiments')
        run=next(r for r in runs if r['experiment_id']==args.experiment) if args.experiment else next(r for r in runs if r['state'] not in ('COMPLETED','FAILED'))
        result=call(client,'POST',BASE+f"/experiments/{run['experiment_id']}/stop")
        proof={'experiment_id':run['experiment_id'],'state':result['state'],'ended_at':result['ended_at'],
               'at':stamp(),'open_fault_windows':rows('SELECT count(*) AS n FROM fault_windows WHERE ended_at IS NULL')[0]['n']}
        state.setdefault('cleanup_checks',[]).append(proof)
        return proof
    if args.command == 'sync':
        runs=rows('SELECT * FROM experiment_runs WHERE actor=%s AND requested_at>=%s ORDER BY requested_at',
                  (state['users']['administrator']['username'],state['started_at']))
        saved={item['run']['experiment_id']:item for item in state.get('experiments',[])}
        for run in clean(runs):
            item=saved.setdefault(run['experiment_id'],{'before':None,'samples':[]})
            item['run']=compact_run(run)
            history=rows('''SELECT observed_at,jsonb_build_object('state',snapshot->'state',
                'observed_at',snapshot->'observed_at','services',(SELECT jsonb_agg(jsonb_build_object(
                    'service_id',n.value->'service_id','service',n.value->'service','status',n.value->'status',
                    'runtime_state',n.value->'runtime_state','telemetry_state',n.value->'telemetry_state',
                    'metrics',n.value->'metrics','metric_timestamps',n.value->'metric_timestamps'))
                FROM jsonb_array_elements(snapshot->'services') n(value)
                WHERE n.value->>'service' IN ('payment','checkout','ad','email','quote'))) AS snapshot
                FROM topology_history WHERE application_id=%s
                AND observed_at BETWEEN %s::timestamptz-INTERVAL '30 seconds' AND COALESCE(%s::timestamptz,NOW())+INTERVAL '5 minutes'
                ORDER BY observed_at LIMIT 100''',(APP,run['started_at'],run['ended_at']))
            item['persisted_topology_observations']=clean(history)
        state['experiments']=list(saved.values())
        state['persisted_actions']=clean(rows('''SELECT p.*,e.execution_id,e.state AS execution_state,e.result,e.started_at AS executed_at,
            v.outcome,v.completed_at FROM remediation_proposals p LEFT JOIN remediation_executions e USING(proposal_id)
            LEFT JOIN recovery_verifications v USING(execution_id) WHERE p.application_id=%s AND p.created_at>=%s ORDER BY p.created_at''',
            (APP,state['started_at'])))
        return {'experiments':len(runs),'actions':len(state['persisted_actions'])}
    if args.command == 'evidence':
        result = {}
        services=call(client,'GET',f'/api/applications/{APP}/services')
        for name in ('ad','checkout','payment'):
            sid=next(s['service_id'] for s in services if s['name']==name)
            for signal in ('trace','log'):
                body=call(client,'GET',f'/api/applications/{APP}/telemetry/services/{sid}/evidence/{signal}?limit=5')
                for record in body['records']:
                    assert record['application_id']==APP and record['service_id']==sid
                result[f'{name}:{signal}']={'state':body['state'],'cached':body['cached'],
                    'record_count':len(body['records']),'ids':[r['evidence_id'] for r in body['records']]}
        findings=call(client,'GET','/api/intelligence/insights?limit=3')
        for finding in findings:
            assert rows('SELECT 1 FROM intelligence_insights WHERE insight_id=%s',(finding['insight_id'],))
        result['report_rows_persisted']=len(findings)
        state['evidence_checks']=result
        return result
    if args.command == 'preservation':
        import psycopg
        result = {}
        with psycopg.connect('postgresql://eios:eios@eios-verification-postgres:5432/eios_preservation_test') as baseline:
            for table, key in (('events','event_id'),('incidents','incident_id'),('cases','case_id'),('approvals','approval_id'),
                               ('feature_windows',"jsonb_build_array(service,window_start,feature_version)"),('intelligence_insights','insight_id')):
                query = f'SELECT ({key})::text AS record_key FROM {table}'
                old = {row[0] for row in baseline.execute(query)}
                present = {row['record_key'] for row in rows(query)}
                missing = old-present
                result[table] = {'original_count':len(old),'current_count':len(present),'missing_original_ids':len(missing)}
                assert not missing, (table,len(missing))
        state['history_preservation'] = result
        return result
    if args.command == 'safety':
        path = f'/api/applications/{APP}/telemetry/sources'
        source = next(s for s in call(client, 'GET', path) if s['kind']=='jaeger')
        payload = {key: source[key] for key in ('kind','endpoint','scope','enabled','freshness_seconds')}
        try:
            disabled = call(client, 'POST', path, expected=201, json={**payload,'enabled':False})
            assert disabled['connection_state']=='unknown' and disabled['state']=='unknown'
        finally:
            call(client,'POST',path,expected=201,json=payload)
        call(client, 'POST', BASE+'/experiments', expected=403,
             headers={'Origin':'https://untrusted.invalid'},json={})
        call(client,'POST','/api/docker/containers/payment/restart',expected=403)
        with httpx.Client(base_url='http://127.0.0.1:8000',timeout=15) as public:
            call(public,'GET',BASE+'/overview',expected=401)
        terminal=call(client,'POST','/api/terminal/exec',json={'command':'docker ps'})
        state['safety']={'disabled_source':'unknown','source_restored':True,'invalid_origin':403,
                         'direct_runtime_bypass':403,'unauthenticated_read':401,
                         'docker_terminal':terminal}
        return state['safety']
    if args.command == 'diagnostics':
        result = {}
        with httpx.Client(timeout=15) as transport:
            for label, expression in (
                ('span_counts', 'sum by(service_name,span_kind)(traces_span_metrics_calls_total{service_name=~"payment|checkout|email|ad"})'),
                ('errors', 'sum by(service_name)(rate(traces_span_metrics_calls_total{status_code="STATUS_CODE_ERROR"}[5m]))')):
                result[label] = transport.get('http://prometheus:9090/api/v1/query', params={'query':expression}).json()['data']['result']
        result['catalog'] = rows('''SELECT s.name,s.service_id,s.runtime_identifier,count(r.container_id) AS runtime_count
            FROM services s LEFT JOIN service_runtime_instances r USING(service_id)
            WHERE s.application_id=%s AND s.name IN ('payment','email','ad','checkout','quote')
            GROUP BY s.service_id''', (APP,))
        result['active_faults'] = [f['key'] for f in call(client,'GET','/api/flags') if f['on']]
        state['diagnostics'] = clean(result)
        return result
    if args.command == 'checks':
        return checks(client, token, state)
    if args.command == 'clear-existing':
        active = [f for f in call(client, 'GET', '/api/flags') if f['on']]
        state['preexisting_flags'] = active
        for flag in active:
            record = call(client, 'POST', '/api/faults/start', json={'flag_key': flag['key'],
                'variant': flag['defaultVariant'], 'apply': False,
                'notes': 'Pre-verification active flag found without a recorded window; onset unknown. Record observation and clear for baseline.'})
            call(client, 'POST', f"/api/faults/{record['window_id']}/stop")
        state['preexisting_cleared_at'] = stamp()
        return {'cleared': [f['key'] for f in active], 'at': stamp()}
    if args.command == 'start':
        services = call(client, 'GET', f'/api/applications/{APP}/services')
        sid = next(s['service_id'] for s in services if s['name'] == args.service)
        before = snapshot(client)
        run = call(client, 'POST', BASE+'/experiments', expected=201,
                   json={'scenario': args.scenario, 'service_id': sid, 'duration_seconds': args.duration,
                         'variant':args.variant})
        state.setdefault('experiments', []).append({'run': run, 'before': before, 'samples': []})
        return {'experiment_id': run['experiment_id'], 'scenario': run['scenario'],
                'started_at': run['started_at'], 'deadline': run['deadline'],
                'before':[{k:n[k] for k in ('service','status','metrics')} for n in before['services']]}
    if args.command == 'observe':
        sample = snapshot(client)
        for item in state.get('experiments', []):
            item['run'] = call(client, 'GET', BASE+f"/experiments/{item['run']['experiment_id']}")
            item['samples'].append(sample)
        state['database_latest'] = counts()
        runs = [{'id': e['run']['experiment_id'], 'scenario': e['run']['scenario'], 'state': e['run']['state'],
                 'ended_at': e['run']['ended_at']} for e in state.get('experiments', [])]
        anomalies = rows('''SELECT a.anomaly_id,s.name AS service,a.category,a.detector,a.observed_at,a.detected_at,l.incident_id
            FROM operational_anomalies a JOIN services s USING(service_id) LEFT JOIN incident_anomalies l USING(anomaly_id)
            WHERE a.application_id=%s AND a.detected_at>=%s ORDER BY a.detected_at DESC LIMIT 25''', (APP, state['started_at']))
        state['observed_anomalies'] = clean(anomalies)
        return clean({'at':sample['at'],'topology':sample['state'],
            'services':[{k:n[k] for k in ('service','status','metrics')} for n in sample['services']],
            'runs': runs, 'recent_anomalies': anomalies[:6], 'database': state['database_latest']})
    if args.command == 'action':
        incident_id = args.incident
        proposal = call(client, 'POST', BASE+f'/incidents/{incident_id}/proposals', expected=201,
                        json={'action_type': args.action, 'service_id': args.service_id})
        pid = proposal['proposal_id']
        call(client, 'POST', BASE+f'/proposals/{pid}/execute', expected=409)
        operator, operator_token = client_for(state['users']['operator']['user_id'])
        try:
            call(operator, 'POST', BASE+f'/proposals/{pid}/decision', expected=403,
                 json={'decision': 'approve', 'notes': 'RBAC negative check'})
        finally:
            operator.close()
            revoke(operator_token)
        call(client, 'POST', BASE+f'/proposals/{pid}/decision', json={'decision': args.decision, 'notes': 'Explicit controlled verification of assisted remediation'})
        result = call(client, 'POST', BASE+f'/proposals/{pid}/execute', expected=409 if args.decision == 'reject' else 200)
        state.setdefault('actions', []).append({'incident_id': incident_id, 'proposal': proposal, 'decision': args.decision, 'result': result})
        return state['actions'][-1]
    if args.command == 'investigate':
        result = call(client, 'POST', BASE+f'/incidents/{args.incident}/investigate')
        state.setdefault('investigations', []).append(result)
        return result
    if args.command == 'evaluate':
        ids = [e['run']['experiment_id'] for e in state['experiments'] if e['run']['state'] == 'COMPLETED']
        result = call(client, 'POST', BASE+'/evaluations', expected=201, json={'experiment_ids': ids})
        eid = result['evaluation_id']
        exported = call(client, 'GET', BASE+f'/evaluations/{eid}/export')
        assert exported['metrics'] == result['metrics']
        csv = client.get(BASE+f'/evaluations/{eid}/export?format=csv')
        assert csv.status_code == 200 and 'metric,value,definition_version' in csv.text
        state['evaluation'] = result
        return {'evaluation_id':eid,'episodes':len(result['metrics']['episodes']),
                'detectors':result['metrics']['detectors'],'MTTD_seconds':result['metrics']['MTTD_seconds'],
                'MTTR_seconds':result['metrics']['MTTR_seconds'],'exports_match':True}
    if args.command == 'finish':
        active = [e['run'] for e in state.get('experiments', []) if e['run']['state'] not in ('COMPLETED', 'FAILED')]
        for run in active:
            call(client, 'POST', BASE+f"/experiments/{run['experiment_id']}/stop")
        page, checked = 0, 0
        while True:
            integrity = call(client, 'GET', f'/api/governance/audit/integrity?after={page}&limit=10000')
            assert integrity['valid'], integrity
            checked += integrity['checked']
            if integrity['checked'] < 10000:
                break
            page = integrity['last_sequence']
        state['audit_integrity'] = {'valid': True, 'checked': checked}
        state['finished_at'] = stamp()
        state['database_after'] = counts()
        with db.pool.connection() as conn:
            for user in state['users'].values():
                conn.execute('UPDATE users SET disabled=TRUE WHERE user_id=%s', (user['user_id'],))
                conn.execute('UPDATE user_sessions SET revoked_at=NOW() WHERE user_id=%s AND revoked_at IS NULL', (user['user_id'],))
                audit(conn, user['username'], 'verification.account_disabled', {'user_id': user['user_id']})
        return {'audit_integrity': state['audit_integrity'], 'temporary_accounts_disabled': True,
                'database': state['database_after']}
    raise ValueError('Unsupported command')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['setup', 'checks', 'safety', 'preservation', 'evidence', 'sync', 'stop', 'cleanup-failure', 'provider-check', 'provider-diagnostic', 'annotate', 'audit', 'action-guards', 'diagnostics', 'clear-existing', 'start', 'observe', 'action', 'investigate', 'evaluate', 'finish'])
    parser.add_argument('--scenario', default='baseline')
    parser.add_argument('--service', default='payment')
    parser.add_argument('--duration', type=int, default=120)
    parser.add_argument('--variant')
    parser.add_argument('--incident')
    parser.add_argument('--experiment')
    parser.add_argument('--action', default='start_service')
    parser.add_argument('--proposal')
    parser.add_argument('--service-id')
    parser.add_argument('--decision', choices=['approve', 'reject'], default='approve')
    args = parser.parse_args()
    db.pool.open(wait=True)
    state = json.loads(EVIDENCE.read_text()) if EVIDENCE.exists() else {}
    # Keep the resumable record bounded inside the 300 MB orchestrator limit.
    # Full topology observations remain persisted in PostgreSQL.
    for item in state.get('experiments', []):
        item.pop('persisted_topology_observations', None)
        item['run']=compact_run(item['run'])
    client, token = None, None
    try:
        if args.command == 'setup':
            result = setup(state)
        else:
            client, token = client_for(state['users']['administrator']['user_id'])
            result = run_command(args, client, token, state)
        print(json.dumps(clean(result), indent=2))
    finally:
        for item in state.get('experiments', []):
            item['run']=compact_run(item['run'])
        EVIDENCE.write_text(json.dumps(clean(state), indent=2))
        if client:
            client.close()
            revoke(token)
        db.pool.close()


if __name__ == '__main__':
    main()
