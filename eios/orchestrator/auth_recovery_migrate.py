from pathlib import Path

import config


def migrate(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version='auth-recovery-v1'").fetchone():
        return
    path = Path(__file__).resolve().parent.parent / "db/migrate_auth_recovery.sql"
    if not path.exists():
        path = Path(__file__).resolve().parent / "db/migrate_auth_recovery.sql"
    conn.execute(path.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO schema_migrations(version) VALUES('auth-recovery-v1')")
