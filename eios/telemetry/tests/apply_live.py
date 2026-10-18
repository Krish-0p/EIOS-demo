"""Explicit live migration entry point used only after backup and writer pause."""
import json
import os
import time
import psycopg
from intelligence.migrate import migrate as migrate_intelligence
from telemetry.migrate import migrate
from .rehearse_migration import snapshot

if os.getenv('EIOS_PHASE2_LIVE_APPLY')!='1':
    raise RuntimeError('Live application requires explicit operator invocation and paused writers')
with psycopg.connect(os.environ['EIOS_POSTGRES_DSN']) as conn:
    before = snapshot(conn)
    start = time.monotonic()
    migrate_intelligence(conn)
    migrate(conn)
    after = snapshot(conn)
    assert before==after,'History preservation check failed; transaction will roll back'
    print(json.dumps({'duration_seconds':round(time.monotonic()-start,2),'preserved':before,'live':True,
        'all_original_values_preserved':True,'migration_versions':[row[0] for row in
            conn.execute('SELECT version FROM schema_migrations ORDER BY version')]},indent=2))
