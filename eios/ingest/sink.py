"""Persist events and their Kafka delivery intent in one PostgreSQL transaction."""
from __future__ import annotations
import json
import logging
import threading
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from confluent_kafka import Producer
import config
from schemas import NormalizedEvent
from security.redactor import redact_event
from intelligence.migrate import migrate
from telemetry.identity import resolve_event, persist_event
from telemetry.health import observe

log = logging.getLogger("eios.sink")

class Sink:
    def __init__(self):
        self._producer = Producer({"bootstrap.servers":config.KAFKA_ADDR,
            "enable.idempotence":True,"message.timeout.ms":10000})
        self._lock = threading.Lock()
        self._conn = psycopg.connect(config.POSTGRES_DSN,autocommit=True,row_factory=dict_row)
        migrate(self._conn)

    def _reconnect(self):
        if self._conn.closed:
            self._conn = psycopg.connect(config.POSTGRES_DSN,autocommit=True,row_factory=dict_row)

    def emit(self,event: NormalizedEvent):
        safe = redact_event(event)
        with self._lock:
            self._reconnect()
            with self._conn.transaction():
                safe = resolve_event(self._conn,safe)
                persist_event(self._conn,safe)
                payload = safe.model_dump(mode="json")
                message_id = uuid.uuid5(uuid.NAMESPACE_URL,f"{config.EVENTS_TOPIC}:{safe.event_id}")
                self._conn.execute("""INSERT INTO intelligence_outbox(message_id,topic,message_key,payload)
                    VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(
                    message_id,config.EVENTS_TOPIC,f"{safe.application_id}:{safe.service_id}:{safe.entity.key()}",Jsonb(payload)))
                if safe.signal_type != 'source_health':
                    self._conn.execute('''UPDATE telemetry_sources SET last_data_at=GREATEST(last_data_at,%s)
                        WHERE source_id=%s''',(safe.source_observed_at,safe.source_id))

    def sources(self, kind):
        with self._lock:
            self._reconnect()
            return self._conn.execute('SELECT * FROM telemetry_sources WHERE kind=%s AND enabled', (kind,)).fetchall()

    def source_health(self, source_id, error=None, data_at=None):
        try:
            with self._lock:
                self._reconnect()
                observe(self._conn,source_id,error=error,data_at=data_at)
                self._conn.execute('''UPDATE telemetry_sources t SET checked_at=NOW(),last_error=%s,
                    last_success_at=CASE WHEN %s::text IS NULL THEN NOW() ELSE t.last_success_at END
                    FROM telemetry_sources parent WHERE parent.source_id=%s AND parent.kind='prometheus'
                    AND t.kind='prometheus' AND t.endpoint=parent.endpoint AND t.scope->>'derived_binding'='true' ''',
                    (error,error,source_id))
        except Exception:
            # Health persistence must not kill a tap or acknowledge an order.
            # With no new observation the API will age this source into stale.
            log.warning('Source-health observation could not be persisted')

    def publish_pending(self,limit=200):
        with self._lock:
            self._reconnect()
            messages = self._conn.execute("""SELECT * FROM intelligence_outbox
                WHERE topic=%s AND published_at IS NULL ORDER BY created_at LIMIT %s""",(config.EVENTS_TOPIC,limit)).fetchall()
        for message in messages:
            if not message['payload'].get('application_id'):
                # Unpublished pre-upgrade messages keep their IDs but receive
                # the same identity as their already-persisted event.
                with self._lock:
                    identity = self._conn.execute('''SELECT application_id,service_id,service_name,environment,
                        source_id,signal_type,source_observed_at FROM events WHERE event_id=%s''',
                        (message['payload']['event_id'],)).fetchone()
                    if identity:
                        for key,value in identity.items():
                            message['payload'][key] = value.isoformat() if hasattr(value,'isoformat') else (
                                str(value) if isinstance(value,uuid.UUID) else value)
                        self._conn.execute('UPDATE intelligence_outbox SET payload=%s WHERE message_id=%s',
                            (Jsonb(message['payload']),message['message_id']))
            acknowledged = []
            self._producer.produce(message["topic"],key=message["message_key"].encode(),
                value=json.dumps(message["payload"],allow_nan=False).encode(),
                on_delivery=lambda error,result,target=acknowledged:target.append(error))
            self._producer.flush(2)
            error = str(acknowledged[0]) if acknowledged and acknowledged[0] else None
            if not acknowledged:
                error = "delivery acknowledgement timed out"
            with self._lock:
                self._conn.execute("""UPDATE intelligence_outbox SET attempts=attempts+1,last_error=%s,
                    published_at=CASE WHEN %s::text IS NULL THEN NOW() ELSE NULL END WHERE message_id=%s""",
                    (error,error,message["message_id"]))
            if error:
                break

    def close(self):
        self._producer.flush(3)
        self._conn.close()
