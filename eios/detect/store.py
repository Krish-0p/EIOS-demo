"""Incident persistence, plus the ground-truth lookup that labels them.

An incident detected while a fault window is open is labelled with the flag
that caused it. That is what lets the Stage 3 harness score precision and
recall without anyone labelling by hand.
"""

from __future__ import annotations

import json
import logging
import threading

import psycopg
from confluent_kafka import Producer

import config
from schemas import Incident

log = logging.getLogger("eios.store")

_INSERT = """
INSERT INTO incidents (
    incident_id, schema_version, domain, entity_kind, entity_id, entity_service,
    detected_at, window_start, window_end, detector, score, severity, title,
    features, evidence_event_ids, labels, status, case_id
) VALUES (
    %(incident_id)s, %(schema_version)s, %(domain)s, %(entity_kind)s, %(entity_id)s,
    %(entity_service)s, %(detected_at)s, %(window_start)s, %(window_end)s,
    %(detector)s, %(score)s, %(severity)s, %(title)s, %(features)s,
    %(evidence)s, %(labels)s, %(status)s, %(case_id)s
)
ON CONFLICT (incident_id) DO NOTHING
"""

_OPEN_WINDOWS = """
SELECT flag_key, variant, expected_domain, expected_entity
FROM fault_windows
WHERE started_at <= NOW() AND (ended_at IS NULL OR ended_at >= NOW())
"""


class Store:
    def __init__(self) -> None:
        self._producer = Producer({"bootstrap.servers": config.KAFKA_ADDR})
        self._lock = threading.Lock()
        self._conn = psycopg.connect(config.POSTGRES_DSN, autocommit=True)

    def open_fault_labels(self, domain: str, entity_id: str) -> dict[str, str]:
        """Ground truth for this specific detection.

        A window only labels an incident whose domain and entity match what the
        fault was expected to affect. Labelling every incident that merely
        happened during the window would inflate the true-positive count and
        make the Stage 3 precision figure meaningless.
        """
        try:
            with self._lock, self._conn.cursor() as cur:
                cur.execute(_OPEN_WINDOWS)
                rows = cur.fetchall()
        except Exception:
            log.exception("could not read fault_windows")
            return {}

        matched = []
        for flag_key, _variant, expected_domain, expected_entity in rows:
            # A window with no expected domain cannot attribute anything: it
            # would label every unrelated incident that happened to overlap it.
            if not expected_domain:
                continue
            if expected_domain != domain:
                continue
            if expected_entity and expected_entity != entity_id:
                continue
            matched.append(flag_key)

        if not matched:
            return {}
        return {"injected_fault": ",".join(sorted(set(matched)))}

    def save(self, incident: Incident) -> None:
        self._producer.produce(
            config.INCIDENTS_TOPIC,
            key=incident.entity.key().encode(),
            value=incident.model_dump_json().encode(),
        )
        self._producer.poll(0)

        row = {
            "incident_id": str(incident.incident_id),
            "schema_version": incident.schema_version,
            "domain": incident.domain.value,
            "entity_kind": incident.entity.kind.value,
            "entity_id": incident.entity.id,
            "entity_service": incident.entity.service,
            "detected_at": incident.detected_at,
            "window_start": incident.window_start,
            "window_end": incident.window_end,
            "detector": incident.detector,
            "score": incident.score,
            "severity": incident.severity.value,
            "title": incident.title,
            "features": json.dumps(incident.features),
            "evidence": [str(e) for e in incident.evidence_event_ids],
            "labels": json.dumps(incident.labels),
            "status": incident.status.value,
            "case_id": str(incident.case_id) if incident.case_id else None,
        }
        try:
            with self._lock, self._conn.cursor() as cur:
                cur.execute(_INSERT, row)
        except Exception:
            log.exception("incident insert failed, it still went to kafka")

    def close(self) -> None:
        self._producer.flush(5)
        self._conn.close()
