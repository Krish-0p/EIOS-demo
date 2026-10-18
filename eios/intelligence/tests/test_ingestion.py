"""Raw event outbox persists before source offsets may advance."""
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import psycopg
from schemas import Domain, Entity, EntityKind, NormalizedEvent

DSN = os.getenv("EIOS_TEST_DSN")


class FakeProducer:
    def __init__(self,*args):
        self.error = None
    def produce(self,topic,key,value,on_delivery):
        on_delivery(self.error,None)
    def flush(self,seconds):
        return 0


@unittest.skipUnless(DSN,"EIOS_TEST_DSN must point to a disposable database")
class IngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        with psycopg.connect(DSN,autocommit=True) as conn:
            if not conn.execute("SELECT current_database()").fetchone()[0].endswith("_test"):
                raise RuntimeError("Integration database name must end with _test")
            conn.execute((root/"db/init.sql").read_text(),prepare=False)
            from intelligence.migrate import migrate as migrate_intelligence
            from phase1_migrate import migrate as migrate_phase1
            from telemetry.migrate import migrate as migrate_phase2
            migrate_intelligence(conn)
            migrate_phase1(conn)
            migrate_phase2(conn)
        spec = importlib.util.spec_from_file_location("tested_durable_sink",root/"ingest/sink.py")
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with patch.dict(sys.modules,{"config":types.SimpleNamespace(POSTGRES_DSN=DSN,KAFKA_ADDR="unused",EVENTS_TOPIC="eios.events")}):
            spec.loader.exec_module(cls.module)
        cls.module.Producer = FakeProducer

    def setUp(self):
        self.sink = self.module.Sink()
        self.transaction = self.sink._conn.transaction(force_rollback=True)
        self.transaction.__enter__()

    def tearDown(self):
        self.transaction.__exit__(None,None,None)
        self.sink.close()

    def test_event_and_delivery_intent_deduplicate_together(self):
        event = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="prometheus",observed_at=datetime.now(timezone.utc),
            entity=Entity(kind=EntityKind.CONTAINER,id="ingestion-test"),attributes={"message":"password=secret"})
        self.sink.emit(event)
        self.sink.emit(event)
        conn = self.sink._conn
        self.assertEqual(conn.execute("SELECT count(*) AS count FROM events WHERE event_id=%s",(event.event_id,)).fetchone()["count"],1)
        messages = conn.execute("SELECT * FROM intelligence_outbox WHERE payload->>'event_id'=%s",(str(event.event_id),)).fetchall()
        self.assertEqual(len(messages),1)
        self.assertEqual(messages[0]['payload']['application_id'],'6b42866e-e214-57e4-a7bd-e0ce18ade732')
        self.assertIsNotNone(messages[0]['payload']['service_id'])
        self.assertNotIn("secret",messages[0]["payload"]["attributes"]["message"])
        self.sink._producer.error = "broker unavailable"
        self.sink.publish_pending()
        self.assertIsNone(conn.execute("SELECT published_at FROM intelligence_outbox WHERE message_id=%s",(messages[0]["message_id"],)).fetchone()["published_at"])
        self.sink._producer.error = None
        self.sink.publish_pending()
        self.assertIsNotNone(conn.execute("SELECT published_at FROM intelligence_outbox WHERE message_id=%s",(messages[0]["message_id"],)).fetchone()["published_at"])

    def test_pending_legacy_delivery_gets_persisted_identity_without_changing_event_id(self):
        event = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source='prometheus',observed_at=datetime.now(timezone.utc),
            entity=Entity(kind=EntityKind.CONTAINER,id='legacy-pending'))
        self.sink.emit(event)
        conn = self.sink._conn
        conn.execute("""UPDATE intelligence_outbox SET payload=payload - ARRAY['application_id','service_id','source_id',
            'service_name','environment','signal_type','source_observed_at'] WHERE payload->>'event_id'=%s""",(str(event.event_id),))
        self.sink.publish_pending()
        row = conn.execute("SELECT * FROM intelligence_outbox WHERE payload->>'event_id'=%s",(str(event.event_id),)).fetchone()
        self.assertEqual(row['payload']['event_id'],str(event.event_id))
        self.assertIsNotNone(row['payload']['service_id'])
        self.assertIsNotNone(row['published_at'])
