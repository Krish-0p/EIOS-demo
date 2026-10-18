"""Serialize additive schema migrations across API and worker startup."""
from pathlib import Path


def migrate(conn):
    path = Path(__file__).resolve().parents[1] / "db" / "migrate_intelligence.sql"
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(71023001)")
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
        if conn.execute("SELECT 1 FROM schema_migrations WHERE version='intelligence-v1'").fetchone():
            return
        conn.execute(path.read_text(encoding="utf-8"), prepare=False)
        conn.execute("INSERT INTO schema_migrations(version) VALUES('intelligence-v1')")


if __name__ == "__main__":
    import psycopg
    from .config import POSTGRES_DSN
    with psycopg.connect(POSTGRES_DSN) as connection:
        migrate(connection)
