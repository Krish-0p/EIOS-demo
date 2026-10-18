"""Compare keys and original event values before/after a restored migration."""
import hashlib
import json
import os
import time
import psycopg
from telemetry.migrate import migrate


KEYS = {'events':'event_id','incidents':'incident_id','cases':'case_id','approvals':'approval_id',
    'fault_windows':'window_id','intelligence_insights':'insight_id','intelligence_forecasts':'forecast_id',
    'model_registry':'model_id','evaluation_runs':'evaluation_id',
    'feature_windows':"service || ':' || window_start::text || ':' || feature_version"}


def snapshot(conn):
    result = {}
    for table,key in KEYS.items():
        values = [str(row[0]) for row in conn.execute(f'SELECT {key} FROM {table}')]
        result[table] = {'rows':len(values),'sha256':hashlib.sha256('\n'.join(sorted(values)).encode()).hexdigest()}
    # Metadata backfill must not alter source samples or their units/timestamps.
    values = [str(row[0]) for row in conn.execute('''SELECT jsonb_build_array(event_id,source,observed_at,
        entity_kind,entity_id,entity_service,metrics,attributes,trace_id,raw_ref)::text FROM events ORDER BY event_id''')]
    result['event_original_values'] = hashlib.sha256('\n'.join(values).encode()).hexdigest()
    return result


if __name__=='__main__':
    dsn = os.environ['EIOS_POSTGRES_DSN']
    if 'eios_phase2_test_' not in dsn:
        raise RuntimeError('Use an isolated restored Phase 2 test database')
    with psycopg.connect(dsn) as conn:
        before = snapshot(conn)
        start = time.monotonic()
        migrate(conn)
        migrate(conn)
        after = snapshot(conn)
        assert before==after,'History changed'
        print(json.dumps({'duration_seconds':round(time.monotonic()-start,2),'preserved':before,
            'replay_safe':True,'events_without_environment':conn.execute('SELECT count(*) FROM events WHERE environment IS NULL').fetchone()[0]},indent=2))
