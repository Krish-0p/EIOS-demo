"""Read queries and fault-window control.

Endpoints are defined with `def` rather than `async def`, so FastAPI runs them
in a worker thread and this synchronous pool is safe.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config

pool = ConnectionPool(config.POSTGRES_DSN, min_size=1, max_size=6, open=False)


def _rows(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def incidents(limit: int = 50, domain: str | None = None, application_id=None) -> list[dict]:
    sql = """
        SELECT incident_id, application_id, service_id, domain, entity_kind, entity_id, entity_service,
               detected_at, window_start, window_end, detector, score, severity,
               title, features, labels, status,
               cardinality(evidence_event_ids) AS evidence_count
        FROM incidents
        WHERE (%(domain)s::text IS NULL OR domain = %(domain)s::text)
          AND (%(application_id)s::uuid IS NULL OR application_id=%(application_id)s::uuid)
        ORDER BY detected_at DESC
        LIMIT %(limit)s
    """
    return _rows(sql, {"limit": limit, "domain": domain, "application_id": application_id})


def incident(incident_id: str) -> dict | None:
    sql = "SELECT * FROM incidents WHERE incident_id = %(id)s"
    found = _rows(sql, {"id": incident_id})
    return found[0] if found else None


def evidence_events(incident_id: str) -> list[dict]:
    """The events an incident actually cited, in order."""
    sql = """
        SELECT e.event_id, e.application_id, e.service_id, e.domain, e.source, e.observed_at,
               e.entity_kind, e.entity_id, e.metrics, e.attributes
        FROM events e
        JOIN incidents i ON e.event_id = ANY (i.evidence_event_ids)
        WHERE i.incident_id = %(id)s
        ORDER BY e.observed_at
    """
    return _rows(sql, {"id": incident_id})


def events(limit: int = 100, domain: str | None = None, application_id=None) -> list[dict]:
    sql = """
        SELECT event_id, application_id, service_id, domain, source, observed_at, entity_kind, entity_id,
               entity_service, metrics, attributes
        FROM events
        WHERE (%(domain)s::text IS NULL OR domain = %(domain)s::text)
          AND (%(application_id)s::uuid IS NULL OR application_id=%(application_id)s::uuid)
        ORDER BY observed_at DESC
        LIMIT %(limit)s
    """
    return _rows(sql, {"limit": limit, "domain": domain, "application_id": application_id})


def stats() -> dict:
    by_domain = _rows(
        """
        SELECT domain, count(*) AS events,
               max(observed_at) AS latest
        FROM events GROUP BY domain ORDER BY domain
        """
    )
    by_severity = _rows(
        """
        SELECT severity, count(*) AS incidents
        FROM incidents
        WHERE detected_at > NOW() - INTERVAL '24 hours'
        GROUP BY severity
        """
    )
    totals = _rows(
        """
        SELECT
          (SELECT count(*) FROM events)    AS events,
          (SELECT count(*) FROM incidents) AS incidents,
          (SELECT count(*) FROM fault_windows WHERE ended_at IS NULL) AS open_faults
        """
    )[0]
    return {
        "totals": totals,
        "events_by_domain": by_domain,
        "incidents_by_severity": by_severity,
    }


def fault_windows(limit: int = 50) -> list[dict]:
    sql = """
        SELECT window_id, flag_key, variant, started_at, ended_at,
               expected_domain, expected_entity, notes
        FROM fault_windows
        ORDER BY started_at DESC
        LIMIT %(limit)s
    """
    return _rows(sql, {"limit": limit})


def start_fault(
    flag_key: str,
    variant: str | None,
    expected_domain: str | None,
    expected_entity: str | None,
    notes: str | None,
) -> dict:
    window_id = uuid.uuid4()
    sql = """
        INSERT INTO fault_windows (
            window_id, flag_key, variant, started_at,
            expected_domain, expected_entity, notes
        ) VALUES (
            %(window_id)s, %(flag_key)s, %(variant)s, %(started_at)s,
            %(expected_domain)s, %(expected_entity)s, %(notes)s
        )
        RETURNING window_id, flag_key, started_at
    """
    params = {
        "window_id": str(window_id),
        "flag_key": flag_key,
        "variant": variant,
        "started_at": datetime.now(timezone.utc),
        "expected_domain": expected_domain,
        "expected_entity": expected_entity,
        "notes": notes,
    }
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.execute(
            """
            INSERT INTO audit_log (actor, action, subject_kind, subject_id, detail)
            VALUES ('operator', 'fault.start', 'fault_window', %(id)s, %(detail)s)
            """,
            {"id": str(window_id), "detail": f'{{"flag_key": "{flag_key}"}}'},
        )
    return row


def stop_fault(window_id: str) -> dict | None:
    sql = """
        UPDATE fault_windows
        SET ended_at = %(ended_at)s
        WHERE window_id = %(id)s AND ended_at IS NULL
        RETURNING window_id, flag_key, started_at, ended_at
    """
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"id": window_id, "ended_at": datetime.now(timezone.utc)})
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                INSERT INTO audit_log (actor, action, subject_kind, subject_id, detail)
                VALUES ('operator', 'fault.stop', 'fault_window', %(id)s, '{}')
                """,
                {"id": window_id},
            )
    return row


def scoreboard() -> list[dict]:
    """Detections grouped by whether a fault was open at the time.

    Not the Stage 3 harness, but it makes the labelling visible now and proves
    the ground-truth mechanism works before models depend on it.
    """
    sql = """
        SELECT detector,
               count(*) FILTER (WHERE labels ? 'injected_fault') AS during_fault,
               count(*) FILTER (WHERE NOT (labels ? 'injected_fault')) AS unlabelled,
               count(*) AS total
        FROM incidents
        GROUP BY detector
        ORDER BY total DESC
    """
    return _rows(sql)


def audit_entries(limit: int = 100) -> list[dict]:
    return _rows("SELECT * FROM audit_log ORDER BY at DESC LIMIT %(limit)s", {"limit": limit})


def security_alerts(limit: int = 50) -> list[dict]:
    return _rows(
        "SELECT * FROM audit_log WHERE action LIKE 'security.%%' OR action LIKE 'auth.%%' ORDER BY at DESC LIMIT %(limit)s",
        {"limit": limit},
    )
