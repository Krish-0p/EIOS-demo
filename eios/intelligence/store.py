"""Durable inputs, replay-safe results, incident cases, and an acknowledged outbox."""
from datetime import datetime, timedelta, timezone
import json
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from schemas import Incident, Domain, Entity, EntityKind
from security.redactor import redact_event
from . import config
from .features import FEATURE_VERSION
from .migrate import migrate
from .recommendations import recommendation

NAMESPACE = uuid.UUID("9a31aec1-547f-4ec8-a01c-41506380e4f1")


def stable_id(key):
    return uuid.uuid5(NAMESPACE, key)


def save_incident(conn, incident):
    data = incident.model_dump(mode="json")
    entity = data.pop("entity")
    for name in ("features", "labels"):
        data[name] = Jsonb(data[name])
    data.update(entity_kind=entity["kind"], entity_id=entity["id"], entity_service=entity["service"])
    conn.execute("""INSERT INTO incidents(incident_id,schema_version,domain,entity_kind,entity_id,entity_service,
        detected_at,window_start,window_end,detector,score,severity,title,features,evidence_event_ids,labels,status,case_id)
        VALUES(%(incident_id)s,%(schema_version)s,%(domain)s,%(entity_kind)s,%(entity_id)s,%(entity_service)s,
        %(detected_at)s,%(window_start)s,%(window_end)s,%(detector)s,%(score)s,%(severity)s,%(title)s,
        %(features)s,%(evidence_event_ids)s::uuid[],%(labels)s,%(status)s,%(case_id)s)
        ON CONFLICT(incident_id) DO NOTHING""", data)


def enqueue(conn, topic, key, payload):
    message_id = stable_id(f"{topic}:{key}")
    conn.execute("""INSERT INTO intelligence_outbox(message_id,topic,message_key,payload)
        VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (message_id, topic, key, Jsonb(payload)))


def correlate(conn, incident, insight):
    """Same-service episode grouping; no dependency relationship proves a cause."""
    service = insight["service"]
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"case:{service}",))
    existing = conn.execute("""SELECT c.* FROM cases c
        WHERE c.enrichment->>'service'=%s AND c.closed_at IS NULL
        AND EXISTS(SELECT 1 FROM incidents i WHERE i.case_id=c.case_id
            AND i.window_end >= %s AND i.window_end <= %s)
        ORDER BY c.opened_at DESC LIMIT 1 FOR UPDATE""",
        (service, incident.window_end-timedelta(minutes=30), incident.window_end)).fetchone()
    enrichment = {"service": service, "affected_services": [service],
        "root_cause": "Candidate cause requires investigation; see stored evidence",
        "anomaly_score": incident.score, "score_meaning": "Unusualness, not failure probability",
        "recommendation": insight["recommendation"], "latest_insight_id": str(insight["insight_id"])}
    entry = {"time": incident.detected_at.isoformat(), "event": incident.title,
             "incident_id": str(incident.incident_id), "insight_id": str(insight["insight_id"])}
    if existing:
        case_id = existing["case_id"]
        timeline = (existing["timeline"] + [entry])[-100:]
        order = ["info", "low", "medium", "high", "critical"]
        severity = max((existing["severity"], incident.severity.value), key=order.index)
        conn.execute("""UPDATE cases SET severity=%s,timeline=%s,enrichment=%s,
            summary=%s WHERE case_id=%s""", (severity, Jsonb(timeline), Jsonb(enrichment),
            f"Evidence grouped for {service} within a 30-minute episode. No automatic action executed.", case_id))
    else:
        case_id = stable_id(f"case:{service}:{incident.incident_id}")
        conn.execute("""INSERT INTO cases(case_id,opened_at,severity,title,summary,timeline,enrichment,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'open') ON CONFLICT DO NOTHING""", (
            case_id, incident.detected_at, incident.severity.value, f"Investigation: {service}",
            "Stored findings require evidence review; no automatic action executed.", Jsonb([entry]), Jsonb(enrichment)))
    conn.execute("UPDATE incidents SET case_id=%s WHERE incident_id=%s", (case_id, incident.incident_id))


class Store:
    def __init__(self, dsn=None):
        self.conn = psycopg.connect(dsn or config.POSTGRES_DSN, autocommit=True, row_factory=dict_row)
        migrate(self.conn)

    def rows(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def state(self, key, value):
        self.conn.execute("""INSERT INTO intelligence_state(key,value) VALUES(%s,%s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()""", (key, Jsonb(value)))

    def ingest(self, event):
        safe = redact_event(event)
        with self.conn.transaction():
            if safe.application_id is not None:
                from telemetry.identity import resolve_event, persist_event
                persist_event(self.conn,resolve_event(self.conn,safe))
                return
            self.conn.execute("""INSERT INTO events(event_id,schema_version,domain,source,observed_at,ingested_at,
                entity_kind,entity_id,entity_service,metrics,attributes,trace_id,raw_ref)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (
                safe.event_id, safe.schema_version, safe.domain.value, safe.source, safe.observed_at,
                safe.ingested_at, safe.entity.kind.value, safe.entity.id, safe.entity.service,
                Jsonb(safe.metrics), Jsonb(safe.attributes), safe.trace_id, safe.raw_ref))

    def reject(self, msg, reason):
        # Store coordinates/reason only; malformed input may contain secrets.
        self.conn.execute("""INSERT INTO intelligence_rejections(topic,partition_id,offset_id,reason)
            VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (
            msg.topic(), msg.partition(), msg.offset(), reason[:500]))

    def upsert_windows(self, windows):
        with self.conn.transaction():
            for window in windows:
                self.conn.execute("""INSERT INTO feature_windows(service,window_start,window_end,feature_version,
                    features,quality,evidence_event_ids) VALUES(%s,%s,%s,%s,%s,%s,%s::uuid[])
                    ON CONFLICT(service,window_start,feature_version) DO NOTHING""", (
                    window["service"], window["window_start"], window["window_end"], window["feature_version"],
                    Jsonb(window["features"]), Jsonb(window["quality"]), window["evidence_event_ids"]))

    def history(self, service, minutes=60):
        return self.rows("""SELECT * FROM feature_windows WHERE service=%s AND feature_version=%s
            AND window_end > NOW() - (%s * INTERVAL '1 minute') ORDER BY window_end""", (service, FEATURE_VERSION, minutes))

    def is_processed(self, key):
        return bool(self.rows("SELECT 1 FROM intelligence_state WHERE key=%s", (key,)))

    def window_processed(self, key, end):
        found = self.rows("SELECT value FROM intelligence_state WHERE key=%s",(key,))
        previous = found[0]["value"].get("window_end") if found else None
        return bool(previous and datetime.fromisoformat(previous) >= end)

    def save_finding(self, window, finding, model_id=None, incident=None):
        detector = finding["detector"]
        service = window["service"]
        end = window["window_end"]
        insight_id = stable_id(f"insight:{service}:{end.isoformat()}:{detector}")
        if self.rows("SELECT 1 FROM intelligence_insights WHERE insight_id=%s", (insight_id,)):
            return None
        if incident is None and self.rows("""SELECT 1 FROM intelligence_insights WHERE service=%s AND detector=%s
            AND window_end > %s AND window_end <= %s LIMIT 1""",
            (service, detector, end-timedelta(seconds=config.COOLDOWN_SECONDS), end)):
            return None
        evidence = [uuid.UUID(str(e)) for e in window["evidence_event_ids"]]
        if incident is None:
            incident = Incident(incident_id=stable_id(f"incident:{insight_id}"),
                domain=Domain.ECOMMERCE if finding["signal"]=="orders" else Domain.INFRASTRUCTURE,
                entity=Entity(kind=EntityKind.SERVICE, id=service, service=service),
                window_start=window["window_start"], window_end=end, detector=detector,
                score=finding["score"], severity=finding["severity"], title=finding["title"],
                features=finding["measurements"], evidence_event_ids=evidence,
                labels={"feature_version": FEATURE_VERSION, **({"model_id": str(model_id)} if model_id else {})})
        insight = {"insight_id": str(insight_id), "incident_id": str(incident.incident_id), "service": service,
            "kind": finding["kind"], "created_at": datetime.now(timezone.utc).isoformat(),
            "window_start": window["window_start"].isoformat(), "window_end": end.isoformat(),
            "detector": detector, "model_id": str(model_id) if model_id else None,
            "feature_version": "rule-v1" if finding["kind"]=="rule_evidence" else FEATURE_VERSION,
            "severity": finding["severity"], "title": finding["title"], "measurements": finding["measurements"],
            "baseline": finding.get("baseline", {}), "analysis": finding["analysis"],
            "evidence_event_ids": [str(e) for e in evidence],
            "recommendation": recommendation(service, finding["signal"]), "status": "open"}
        with self.conn.transaction():
            save_incident(self.conn, incident)
            self.conn.execute("""INSERT INTO intelligence_insights(insight_id,incident_id,service,kind,created_at,
                window_start,window_end,detector,model_id,feature_version,severity,title,measurements,baseline,analysis,
                evidence_event_ids,recommendation,status)
                VALUES(%(insight_id)s,%(incident_id)s,%(service)s,%(kind)s,%(created_at)s,%(window_start)s,%(window_end)s,
                %(detector)s,%(model_id)s,%(feature_version)s,%(severity)s,%(title)s,%(measurements)s,%(baseline)s,
                %(analysis)s,%(evidence_event_ids)s::uuid[],%(recommendation)s,%(status)s) ON CONFLICT DO NOTHING""",
                {k: Jsonb(v) if k in ("measurements", "baseline", "analysis", "recommendation") else v for k,v in insight.items()})
            correlate(self.conn, incident, insight)
            if finding["kind"] != "rule_evidence":
                enqueue(self.conn, config.INCIDENTS_TOPIC, str(incident.incident_id), incident.model_dump(mode="json"))
            enqueue(self.conn, config.INSIGHTS_TOPIC, str(insight_id), insight)
        return insight

    def enrich_incident(self, incident):
        if incident.labels.get('application_id','6b42866e-e214-57e4-a7bd-e0ce18ade732') != '6b42866e-e214-57e4-a7bd-e0ce18ade732':
            return
        if incident.detector.startswith(("ml:", "kpi:", "forecast:")):
            return
        window = {"service": incident.entity.service or incident.entity.id,
            "window_start": incident.window_start, "window_end": incident.window_end,
            "evidence_event_ids": incident.evidence_event_ids}
        signal = "memory" if "memory" in incident.detector else "cpu" if "cpu" in incident.detector else "orders"
        self.save_finding(window, {"kind": "rule_evidence", "detector": incident.detector,
            "title": incident.title, "severity": incident.severity.value, "score": incident.score,
            "measurements": incident.features, "baseline": {}, "signal": signal,
            "analysis": {"candidate_cause": "Rule observed a sustained change; verify cause against evidence",
                "limitation": "Rule output, not model inference"}}, incident=incident)

    def save_forecast(self, window, horizon, result):
        fid = stable_id(f"forecast:{window['service']}:{window['window_end'].isoformat()}:{horizon}")
        self.conn.execute("""INSERT INTO intelligence_forecasts(forecast_id,service,observed_at,horizon_minutes,
            state,reason,algorithm,values,evidence_event_ids) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid[])
            ON CONFLICT DO NOTHING""", (fid, window["service"], window["window_end"], horizon,
            result["state"], result["reason"], "memory-linear-v1", Jsonb(result["values"]), result["evidence_event_ids"]))

    def publish_pending(self, producer, limit=20):
        for row in self.rows("SELECT * FROM intelligence_outbox WHERE published_at IS NULL AND topic<>%s ORDER BY created_at LIMIT %s", (config.EVENTS_TOPIC,limit)):
            delivered = []
            producer.produce(row["topic"], key=row["message_key"].encode(),
                value=json.dumps(row["payload"], allow_nan=False).encode(),
                on_delivery=lambda error, message, target=delivered: target.append(error))
            producer.flush(2)
            error = str(delivered[0]) if delivered and delivered[0] else None
            if not delivered:
                error = "delivery acknowledgement timed out"
            self.conn.execute("""UPDATE intelligence_outbox SET attempts=attempts+1,last_error=%s,
                published_at=CASE WHEN %s::text IS NULL THEN NOW() ELSE NULL END WHERE message_id=%s""", (error, error, row["message_id"]))
            if error:
                break

    def close(self):
        self.conn.close()
