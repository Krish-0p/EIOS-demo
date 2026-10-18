"""Read live APIs using a temporary server session; never print credentials."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import sys

import httpx
import psycopg
from psycopg.rows import dict_row
import auth
from telemetry import DEFAULT_APPLICATION_ID

MODE = sys.argv[1] if len(sys.argv)>1 else 'baseline'
APP = str(DEFAULT_APPLICATION_ID)
output = {'mode':MODE,'started_at':datetime.now(timezone.utc).isoformat()}


def counts(conn):
    tables = ('events','incidents','feature_windows','intelligence_insights','cases','approvals')
    return {table:conn.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] for table in tables}


with psycopg.connect(os.environ['EIOS_POSTGRES_DSN'],autocommit=True,row_factory=dict_row) as conn:
    user = conn.execute("SELECT user_id FROM users WHERE role='administrator' AND NOT disabled ORDER BY created_at LIMIT 1").fetchone()
    token,expires = auth.new_session(conn,user['user_id'])
    try:
        with httpx.Client(base_url='http://eios-dashboard:5173',cookies={auth.COOKIE_NAME:token},
                headers={'origin':'http://localhost:5173'},timeout=30) as client:
            def get(path):
                response = client.get(path)
                response.raise_for_status()
                return response.json()
            output['session_validated'] = get('/api/auth/me')['role']=='administrator'
            path = f'/api/applications/{APP}/telemetry'
            output['counts_before'] = counts(conn)
            expected = 'disconnected' if MODE=='source-down' else 'connected'
            deadline = time.monotonic()+100
            while True:
                sources = get(path+'/sources')
                prom = next(row for row in sources if row['kind']=='prometheus')
                if prom['state']==expected:
                    break
                if time.monotonic()>deadline:
                    raise AssertionError(f'Expected Prometheus {expected}, got {prom["state"]}')
                time.sleep(2)
            output['sources'] = [{k:row[k] for k in ('kind','state','connection_state','freshness','checked_at','last_data_at','last_error')}
                for row in sources]
            if MODE!='source-down':
                metrics = get(path+'/records?signal_type=metric&limit=10')
                orders = get(path+'/records?signal_type=business_event&minutes=60&limit=5')
                assert metrics and orders,'Expected real metrics and order history'
                for row in metrics+orders:
                    assert all(row.get(key) for key in ('application_id','service_id','service_name','environment','source_id',
                        'signal_type','timestamp','freshness','raw_ref'))
                    assert row['application_id']==APP
                output['metric_example'] = {k:metrics[0][k] for k in ('event_id','service_id','service_name','signal_type','source_type','timestamp','freshness','raw_ref')}
                output['business_event_example'] = {k:orders[0][k] for k in ('event_id','service_id','service_name','signal_type','source_type','timestamp','raw_ref')}
                catalog = get(f'/api/applications/{APP}/services')
                for signal,name in (('trace','ad'),('log','recommendation')):
                    service = next(row for row in catalog if row['name']==name)
                    response = get(path+f'/services/{service["service_id"]}/evidence/{signal}?minutes=15&limit=3')
                    assert response['records'],f'No real {signal} evidence returned: {response.get("reason")}'
                    assert not response['cached'],response
                    output[signal] = {'state':response['state'],'records':len(response['records']),
                        'service_id':service['service_id'],'raw_ref':response['records'][0]['raw_ref'],
                        'observed_at':response['records'][0]['observed_at']}
                apps = get('/api/applications')
                other = next(row for row in apps if row['name']=='EIOS Platform')
                routed = get(f'/api/applications/{other["application_id"]}/telemetry/records?signal_type=metric&limit=5')
                assert routed and all(row['application_id']==other['application_id'] for row in routed)
                assert all(row['service_name'] in ('eios-orchestrator','eios-dashboard') for row in routed)
                output['runtime_owner_mapping'] = {'application_id':other['application_id'],
                    'service_names':sorted({row['service_name'] for row in routed}),'records':len(routed)}
                output['legacy_apis'] = {'services':len(get('/api/services')['services']),
                    'graph_available':get('/api/services/graph')['available'],
                    'intelligence':get('/api/intelligence/status')}
            else:
                output['kafka_still_observed'] = next(row for row in sources if row['kind']=='kafka')['state']
                assert output['kafka_still_observed']=='connected'
                time.sleep(8)
            output['counts_after'] = counts(conn)
            output['latest_incident'] = conn.execute('SELECT incident_id,detector,detected_at,application_id FROM incidents ORDER BY detected_at DESC LIMIT 1').fetchone()
            output['latest_window'] = conn.execute('SELECT service,window_end,application_id FROM feature_windows ORDER BY window_end DESC LIMIT 1').fetchone()
            outbox = conn.execute('''SELECT e.event_id,e.application_id,e.service_id,o.payload->>'application_id' AS wire_app,
                o.payload->>'service_id' AS wire_service,o.published_at FROM intelligence_outbox o JOIN events e
                ON o.payload->>'event_id'=e.event_id::text WHERE o.topic='eios.events' AND o.payload ? 'application_id'
                AND o.published_at IS NOT NULL ORDER BY o.created_at DESC LIMIT 1''').fetchone()
            assert outbox and str(outbox['application_id'])==outbox['wire_app'] and str(outbox['service_id'])==outbox['wire_service']
            output['published_identity_matches_database'] = outbox
    finally:
        conn.execute('UPDATE user_sessions SET revoked_at=NOW() WHERE token_hash=%s',(auth.token_hash(token),))
    output['finished_at'] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(output,default=str,indent=2))
