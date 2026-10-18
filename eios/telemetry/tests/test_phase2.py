"""Phase 2 integration checks: run only against a disposable database."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4, uuid5, NAMESPACE_URL

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from schemas import NormalizedEvent, Entity, EntityKind, Domain
from intelligence.migrate import migrate as intelligence_migrate
from phase1_migrate import migrate as phase1_migrate
from telemetry import DEFAULT_APPLICATION_ID, source_id
from telemetry.migrate import migrate
from telemetry.identity import resolve_event, persist_event, IdentityError
from telemetry.health import view, observe
from telemetry.evidence import traces, logs, bounded_json
from telemetry.queries import vector
import db
from telemetry_router import router

DSN = os.getenv('EIOS_POSTGRES_DSN','')


class Phase2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'eios_phase2_test_' not in DSN:
            raise RuntimeError('Use an isolated eios_phase2_test_* database')
        cls.conn = psycopg.connect(DSN,autocommit=True,row_factory=dict_row)
        cls.conn.execute(Path('/app/db/init.sql').read_text(),prepare=False)
        intelligence_migrate(cls.conn)
        cls.legacy = uuid4()
        cls.conn.execute('''INSERT INTO events(event_id,schema_version,domain,source,observed_at,ingested_at,
            entity_kind,entity_id,entity_service) VALUES(%s,'1.0','infrastructure','prometheus',NOW(),NOW(),
            'service','payment','payment')''',(cls.legacy,))
        phase1_migrate(cls.conn)
        migrate(cls.conn)
        from auth_recovery_migrate import migrate as recovery_migrate
        from workflow_migrate import migrate as workflow_migrate
        recovery_migrate(cls.conn)
        workflow_migrate(cls.conn)
        db.pool.open(wait=True)
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        db.pool.close()
        cls.conn.close()

    def new_app(self):
        aid = uuid4()
        self.conn.execute('''INSERT INTO applications(application_id,name,environment,runtime_type,discovery_scope)
            VALUES(%s,%s,'test','docker','{"container_names":["test"]}')''',(aid,str(aid)))
        return aid

    def source(self, aid, kind='prometheus', url=None, scope=None):
        sid = source_id(aid,kind)
        self.conn.execute('''INSERT INTO telemetry_sources(source_id,application_id,kind,endpoint,scope)
            VALUES(%s,%s,%s,%s,%s)''',(sid,aid,kind,url or f'http://{aid}:9090',Jsonb(scope or {})))
        return self.conn.execute('SELECT * FROM telemetry_sources WHERE source_id=%s',(sid,)).fetchone()

    def event(self,aid=DEFAULT_APPLICATION_ID,**kwargs):
        return NormalizedEvent(application_id=aid,domain=Domain.INFRASTRUCTURE,source='prometheus',
            observed_at=datetime.now(timezone.utc),entity=Entity(kind=EntityKind.SERVICE,id='payment',service='payment'),
            metrics={'cpu_cores':.25,'cpu_ratio':25},**kwargs)

    def test_migration_replay_and_original_event_preserved(self):
        before = self.conn.execute('SELECT event_id,metrics FROM events WHERE event_id=%s',(self.legacy,)).fetchone()
        migrate(self.conn)
        after = self.conn.execute('SELECT * FROM events WHERE event_id=%s',(self.legacy,)).fetchone()
        self.assertEqual(before['event_id'],after['event_id'])
        self.assertEqual(before['metrics'],after['metrics'])
        self.assertEqual(after['application_id'],DEFAULT_APPLICATION_ID)
        self.assertEqual(after['signal_type'],'metric')
        self.assertIsNotNone(after['source_id'])

    def test_identity_in_payload_matches_persisted_identity_and_units(self):
        safe = resolve_event(self.conn,self.event())
        persist_event(self.conn,safe)
        row = self.conn.execute('SELECT * FROM events WHERE event_id=%s',(safe.event_id,)).fetchone()
        payload = safe.model_dump(mode='json')
        for key in ('application_id','service_id','source_id'):
            self.assertEqual(str(row[key]),payload[key])
        self.assertEqual(row['metrics'],{'cpu_cores':.25,'cpu_ratio':25})
        self.assertEqual(row['environment'],'demo')
        self.assertEqual(row['service_name'],'payment')

    def test_equal_service_names_in_different_apps_have_different_identity(self):
        first,second = self.new_app(),self.new_app()
        self.source(first); self.source(second)
        a,b = resolve_event(self.conn,self.event(first)),resolve_event(self.conn,self.event(second))
        self.assertNotEqual(a.service_id,b.service_id)
        self.assertNotEqual(a.source_id,b.source_id)
        persist_event(self.conn,a); persist_event(self.conn,b)
        url = f'/api/applications/{first}/telemetry/records'
        rows = self.client.get(url).json()
        self.assertTrue(rows)
        self.assertTrue(all(row['application_id']==str(first) for row in rows))
        self.assertEqual(self.client.get(f'/api/applications/{first}/telemetry/records?service_id={b.service_id}').status_code,404)

    def test_event_uuid_cannot_be_reused_in_another_app(self):
        aid = self.new_app(); self.source(aid)
        first = resolve_event(self.conn,self.event())
        persist_event(self.conn,first)
        second = resolve_event(self.conn,self.event(aid,event_id=first.event_id))
        with self.assertRaises(IdentityError):
            persist_event(self.conn,second)

    def test_kafka_replay_keeps_legacy_id_but_recreated_topic_order_is_distinct(self):
        reference = f'kafka:orders:0:{uuid4().int}'
        at = datetime.now(timezone.utc)
        original = NormalizedEvent(event_id=uuid5(NAMESPACE_URL,reference),domain=Domain.ECOMMERCE,
            source='kafka:orders',observed_at=at,entity=Entity(kind=EntityKind.ORDER,id='original-order',service='checkout'),
            raw_ref=reference)
        safe = resolve_event(self.conn,original)
        persist_event(self.conn,safe)
        replay = original.model_copy(update={'event_id':uuid4()})
        self.assertEqual(resolve_event(self.conn,replay).event_id,original.event_id)
        new_order = original.model_copy(update={'event_id':uuid4(),
            'entity':Entity(kind=EntityKind.ORDER,id='different-order',service='checkout')})
        resolved = resolve_event(self.conn,new_order)
        self.assertEqual(resolved.event_id,new_order.event_id)
        persist_event(self.conn,resolved)

    def test_existing_container_collector_routes_registered_runtime_owner(self):
        aid = self.new_app()
        sid = uuid4()
        name = f'owned-{aid}'
        self.conn.execute('INSERT INTO services(service_id,application_id,name) VALUES(%s,%s,%s)',(sid,aid,name))
        self.conn.execute('''INSERT INTO service_runtime_instances(container_id,service_id,container_name,runtime_state)
            VALUES(%s,%s,%s,'running')''',(str(uuid4()),sid,name))
        event = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source='prometheus',observed_at=datetime.now(timezone.utc),
            entity=Entity(kind=EntityKind.CONTAINER,id=name,service=name),metrics={'cpu_cores':.2})
        safe = resolve_event(self.conn,event)
        self.assertEqual(safe.application_id,aid)
        self.assertEqual(safe.service_id,sid)
        persist_event(self.conn,safe)

    def test_conflicting_source_service_environment_or_attribute_rejected(self):
        aid = self.new_app(); source = self.source(aid)
        for event in (self.event(source_id=source['source_id']),self.event(environment='wrong'),
                      self.event(attributes={'application_id':str(aid)}),self.event(service_id=uuid4()),
                      self.event(signal_type='log')):
            with self.assertRaises(IdentityError):
                resolve_event(self.conn,event)

    def test_source_states_are_truthful_and_no_data_is_unknown(self):
        source = self.source(self.new_app())
        self.assertEqual(view(source)['state'],'unknown')
        observe(self.conn,source['source_id'])
        source = self.conn.execute('SELECT * FROM telemetry_sources WHERE source_id=%s',(source['source_id'],)).fetchone()
        self.assertEqual(view(source)['state'],'unknown')
        now = datetime.now(timezone.utc)
        observe(self.conn,source['source_id'],data_at=now)
        source = self.conn.execute('SELECT * FROM telemetry_sources WHERE source_id=%s',(source['source_id'],)).fetchone()
        self.assertEqual(view(source)['state'],'connected')
        self.assertEqual(view(source,now+timedelta(minutes=5))['state'],'stale')
        observe(self.conn,source['source_id'],error='down')
        source = self.conn.execute('SELECT * FROM telemetry_sources WHERE source_id=%s',(source['source_id'],)).fetchone()
        self.assertEqual(view(source)['state'],'disconnected')
        self.assertEqual(view(source)['freshness'],'fresh')

    def test_jaeger_probe_uses_registered_service_and_actual_trace_timestamp(self):
        from telemetry.sources import probe
        source = self.conn.execute("SELECT * FROM telemetry_sources WHERE application_id=%s AND kind='jaeger'",
            (DEFAULT_APPLICATION_ID,)).fetchone()
        now = datetime.now(timezone.utc)-timedelta(seconds=1)
        def handler(request):
            if request.url.path.endswith('/services'):
                return httpx.Response(200,json={'data':['payment']})
            self.assertEqual(request.url.params['service'],'payment')
            return httpx.Response(200,json={'data':[{'traceID':'b'*32,'processes':{'p':{'serviceName':'payment'}},
                'spans':[{'spanID':'a'*16,'processID':'p','startTime':int(now.timestamp()*1e6),'duration':100,'tags':[]}]}]})
        client = httpx.Client(base_url='http://jaeger',transport=httpx.MockTransport(handler))
        with patch('telemetry.sources.httpx.Client',return_value=client):
            probe(self.conn,source)
        result = self.conn.execute('SELECT * FROM telemetry_sources WHERE source_id=%s',(source['source_id'],)).fetchone()
        self.assertEqual(view(result)['state'],'connected')
        self.assertAlmostEqual(result['last_data_at'].timestamp(),now.timestamp(),places=5)

    def test_shared_backend_ambiguous_scope_rejected(self):
        aid = self.new_app()
        with patch('auth.require_role',return_value={'username':'test'}):
            result = self.client.post(f'/api/applications/{aid}/telemetry/sources',json={
                'kind':'prometheus','endpoint':'http://prometheus:9090','scope':{'matchers':{'application_id':str(aid)}}})
        self.assertEqual(result.status_code,409)

    def test_reserved_span_labels_cannot_bypass_application_scope(self):
        aid = self.new_app()
        with patch('auth.require_role',return_value={'username':'test'}):
            response = self.client.post(f'/api/applications/{aid}/telemetry/sources',json={
                'kind':'prometheus','endpoint':'http://different:9090','scope':{'matchers':{'span_kind':'other'}}})
        self.assertEqual(response.status_code,400)

    def test_shared_backend_disjoint_scopes_accepted_and_immutable(self):
        first,second = self.new_app(),self.new_app()
        url = f'http://shared-{first}.test:9090'
        self.source(first,url=url,scope={'matchers':{'app':'first'}})
        with patch('auth.require_role',return_value={'username':'test'}):
            result = self.client.post(f'/api/applications/{second}/telemetry/sources',json={
                'kind':'prometheus','endpoint':url,'scope':{'matchers':{'app':'second'}}})
            self.assertEqual(result.status_code,201,result.text)
            persist_event(self.conn,resolve_event(self.conn,self.event(second)))
            result = self.client.post(f'/api/applications/{second}/telemetry/sources',json={
                'kind':'prometheus','endpoint':'http://changed.test:9090'})
            self.assertEqual(result.status_code,409)

    def test_trace_query_and_response_are_scoped_and_bounded(self):
        now = datetime.now(timezone.utc)
        def handler(request):
            self.assertEqual(request.url.params['service'],'payment')
            self.assertEqual(request.url.params['limit'],'1')
            span = {'spanID':'a'*16,'processID':'p','startTime':int(now.timestamp()*1e6),'duration':100,
                'operationName':'payment','tags':[]}
            return httpx.Response(200,json={'data':[{'traceID':'b'*32,'processes':{'p':{'serviceName':'payment'}},
                'spans':[span,{**span,'processID':'other'}]}]})
        with httpx.Client(base_url='http://jaeger',transport=httpx.MockTransport(handler)) as client:
            rows = traces(client,{'scope':{}},'payment',now-timedelta(minutes=1),now+timedelta(seconds=1),1)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['evidence']['duration_us'],100)
        self.assertIn('jaeger:trace:',rows[0]['raw_ref'])

    def test_logs_exact_service_filter_redaction_and_limits(self):
        now = datetime.now(timezone.utc)
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body['size'],2)
            self.assertIn({'term':{'resource.service.name.keyword':'payment'}},body['query']['bool']['filter'])
            return httpx.Response(200,json={'hits':{'hits':[{'_index':'otel-logs-2026-10-18','_id':'doc',
                '_source':{'@timestamp':now.isoformat(),'resource':{'service.name':'payment'},
                    'body':'password=private person@example.org'}}]}})
        with httpx.Client(base_url='http://logs',transport=httpx.MockTransport(handler)) as client:
            rows = logs(client,{'scope':{}},'payment',now-timedelta(minutes=1),now+timedelta(seconds=1),2)
        self.assertNotIn('private',rows[0]['evidence']['message'])
        self.assertNotIn('person@example.org',rows[0]['evidence']['message'])

    def test_response_byte_limit_and_invalid_samples(self):
        with httpx.Client(base_url='http://source',transport=httpx.MockTransport(
                lambda request:httpx.Response(200,content=b'x'*100))) as client:
            with patch('telemetry.evidence.MAX_BYTES',50),self.assertRaises(ValueError):
                bounded_json(client,'GET','/')
        self.assertEqual(vector([{'metric':{'service':'ad'},'value':[1,'inf']}],'service'),{})

    def test_other_application_never_enters_legacy_rule_or_feature_state(self):
        import importlib.util
        import sys
        from intelligence.features import build_windows
        spec = importlib.util.spec_from_file_location('phase2_test_rules','/app/detect/rules.py')
        rules = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = rules
        spec.loader.exec_module(rules)
        state = rules.State()
        aid = self.new_app(); self.source(aid)
        event = self.event(aid).model_copy(update={'entity':Entity(kind=EntityKind.CONTAINER,id='payment',service='payment')})
        state.add(event)
        self.assertEqual(state.snapshot_infra(),{})
        row = {'application_id':aid,'observed_at':datetime.now(timezone.utc)-timedelta(minutes=5)}
        self.assertEqual(build_windows([row],datetime.now(timezone.utc)),[])

    def test_evidence_outage_retains_cached_rows_and_reports_disconnected(self):
        aid = self.new_app(); source = self.source(aid,kind='jaeger')
        # Give this application a logical service without a Prometheus binding.
        sid = uuid4()
        self.conn.execute('INSERT INTO services(service_id,application_id,name) VALUES(%s,%s,%s)',(sid,aid,'payment'))
        now = datetime.now(timezone.utc)
        self.conn.execute('''INSERT INTO telemetry_evidence(evidence_id,application_id,service_id,service_name,
            environment,source_id,signal_type,observed_at,raw_ref,evidence)
            VALUES(%s,%s,%s,'payment','test',%s,'trace',%s,'jaeger:test','{}')''',
            (uuid4(),aid,sid,source['source_id'],now))
        with patch('telemetry_router.traces',side_effect=httpx.ConnectError('down')):
            result = self.client.get(f'/api/applications/{aid}/telemetry/services/{sid}/evidence/trace')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['state'],'disconnected')
        self.assertTrue(result.json()['cached'])
        self.assertEqual(len(result.json()['records']),1)
