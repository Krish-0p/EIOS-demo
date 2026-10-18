"""Additive operational workflow migration; never recreates telemetry/history."""
from pathlib import Path


def migrate(conn):
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(71023015)')
        if conn.execute("SELECT 1 FROM schema_migrations WHERE version='workflow-v1'").fetchone():
            return
        root = Path(__file__).resolve().parent
        path = root / 'db/migrate_workflow.sql'
        if not path.exists():
            path = root.parent / 'db/migrate_workflow.sql'
        conn.execute(path.read_text(encoding='utf-8'), prepare=False)
        conn.execute("INSERT INTO schema_migrations(version) VALUES('workflow-v1')")
