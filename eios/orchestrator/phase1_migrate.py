"""Versioned, atomic Phase 1 migration and legacy identity backfill."""
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

DEFAULT_APPLICATION_ID = UUID("6b42866e-e214-57e4-a7bd-e0ce18ade732")
HISTORY_TABLES = ("events", "incidents", "cases", "feature_windows", "model_registry",
                  "intelligence_insights", "intelligence_forecasts", "evaluation_runs")


def service_id(application_id, name):
    return uuid5(UUID(str(application_id)), name)


def migrate(conn):
    from psycopg import sql
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(71023002)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        if conn.execute("SELECT 1 FROM schema_migrations WHERE version='phase1-v1'").fetchone():
            return
        directory = Path(__file__).resolve().parent
        # Docker flattens orchestrator/*.py into /app; source checkouts retain
        # the orchestrator/ directory. Both layouts use the same migration.
        path = directory / "db/migrate_phase1.sql"
        if not path.is_file():
            path = directory.parent / "db/migrate_phase1.sql"
        conn.execute(path.read_text(encoding="utf-8"), prepare=False)
        scope = {"compose_project": os.getenv("EIOS_DEMO_COMPOSE_PROJECT", "opentelemetry-demo"),
                 "exclude_services": ["eios-postgres", "eios-ingest", "eios-detect", "eios-intelligence", "eios-orchestrator", "eios-dashboard"]}
        telemetry = {"prometheus_url": os.getenv("PROMETHEUS_URL", "http://prometheus:9090"),
                     "jaeger_url": os.getenv("JAEGER_URL", "http://jaeger:16686"),
                     "assignment": "legacy_pipeline"}
        conn.execute("""INSERT INTO applications(application_id,name,environment,runtime_type,discovery_scope,telemetry_config)
            VALUES(%s,'Astronomy Shop','demo','docker',%s::jsonb,%s::jsonb)""",
            (DEFAULT_APPLICATION_ID, json.dumps(scope), json.dumps(telemetry)))
        names = conn.execute("""SELECT DISTINCT name FROM (
            SELECT entity_service AS name FROM events UNION SELECT entity_service FROM incidents
            UNION SELECT entity_id FROM events WHERE entity_kind IN ('container','service') AND entity_service IS NULL
            UNION SELECT entity_id FROM incidents WHERE entity_kind IN ('container','service') AND entity_service IS NULL
            UNION SELECT service FROM feature_windows UNION SELECT service FROM model_registry
            UNION SELECT service FROM intelligence_insights UNION SELECT service FROM intelligence_forecasts
            UNION SELECT enrichment->>'service' FROM cases
        ) names WHERE name IS NOT NULL AND name <> ''""").fetchall()
        for row in names:
            name = row[0] if not isinstance(row, dict) else row["name"]
            conn.execute("INSERT INTO services(service_id,application_id,name) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                         (service_id(DEFAULT_APPLICATION_ID, name), DEFAULT_APPLICATION_ID, name))
        for table in HISTORY_TABLES:
            conn.execute(sql.SQL("UPDATE {} SET application_id=%s WHERE application_id IS NULL").format(sql.Identifier(table)),
                         (DEFAULT_APPLICATION_ID,))
        conn.execute("INSERT INTO schema_migrations(version) VALUES('phase1-v1')")
