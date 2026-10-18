"""Rehearse against a restored backup and prove historical identities survive."""
import hashlib
import json
import os
import time

import psycopg
from intelligence.migrate import migrate as intelligence_migrate
from phase1_migrate import migrate, HISTORY_TABLES

dsn = os.environ["EIOS_POSTGRES_DSN"]
if "eios_phase1_test_" not in dsn:
    raise RuntimeError("Migration rehearsal requires an isolated test database")
KEYS = {"events": "event_id", "incidents": "incident_id", "cases": "case_id", "approvals": "approval_id",
        "fault_windows": "window_id", "intelligence_insights": "insight_id", "intelligence_forecasts": "forecast_id",
        "model_registry": "model_id", "evaluation_runs": "evaluation_id",
        "feature_windows": "service || ':' || window_start::text || ':' || feature_version"}


def snapshot(conn):
    result = {}
    for table, key in KEYS.items():
        values = [str(row[0]) for row in conn.execute(f"SELECT {key} FROM {table}").fetchall()]
        result[table] = {"rows": len(values), "identity_digest": hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()}
    return result


with psycopg.connect(dsn) as conn:
    before = snapshot(conn)
    start = time.monotonic()
    intelligence_migrate(conn)
    migrate(conn)
    first_seconds = time.monotonic()-start
    migrate(conn)
    after = snapshot(conn)
    if before != after:
        raise AssertionError("Historical identities changed during migration")
    unassigned = {table: conn.execute(f"SELECT count(*) FROM {table} WHERE application_id IS NULL").fetchone()[0]
                  for table in HISTORY_TABLES}
    if any(unassigned.values()):
        raise AssertionError(f"Unassigned legacy history: {unassigned}")
    print(json.dumps({"migration_seconds": round(first_seconds, 2), "identity_preservation": before,
                      "unassigned_history": unassigned, "repeatable": True}, indent=2))
