"""Versioned additive migration; source snapshots never rewrite historical IDs."""
import os
from pathlib import Path
from . import DEFAULT_APPLICATION_ID, source_id


def migrate(conn):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(71023004)")
        if conn.execute("SELECT 1 FROM schema_migrations WHERE version='phase2-v1'").fetchone():
            return
        path = Path(__file__).resolve().parents[1] / 'db/migrate_phase2.sql'
        conn.execute(path.read_text(encoding='utf-8'), prepare=False)
        endpoints = {'kafka': os.getenv('KAFKA_ADDR','kafka:9092'),
            'prometheus': os.getenv('PROMETHEUS_URL','http://prometheus:9090'),
            'jaeger': os.getenv('JAEGER_URL','http://jaeger:16686'),
            'opensearch': os.getenv('OPENSEARCH_URL','http://opensearch:9200')}
        for kind, endpoint in endpoints.items():
            conn.execute("""INSERT INTO telemetry_sources(source_id,application_id,kind,endpoint,scope)
                VALUES(%s,%s,%s,%s,%s::jsonb)""",(source_id(DEFAULT_APPLICATION_ID,kind),DEFAULT_APPLICATION_ID,kind,endpoint,
                    '{"topic":"orders"}' if kind=='kafka' else '{}'))
        # Separate updates avoid an accidental many-to-many source join.
        conn.execute("""UPDATE events e SET environment=a.environment FROM applications a
            WHERE a.application_id=e.application_id""")
        conn.execute("""UPDATE events e SET source_id=t.source_id FROM telemetry_sources t
            WHERE t.application_id=e.application_id AND t.kind=CASE
                WHEN e.source LIKE 'prometheus%' THEN 'prometheus'
                WHEN e.source LIKE 'kafka:%' THEN 'kafka' ELSE NULL END""")
        conn.execute("INSERT INTO schema_migrations(version) VALUES('phase2-v1')")
