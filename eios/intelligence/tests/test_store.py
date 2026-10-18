"""Run against a disposable PostgreSQL database; every test rolls back its data."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg.types.json import Jsonb
from schemas import Domain, Entity, EntityKind, NormalizedEvent
from schemas.intelligence import IntelligenceInsight, ModelVersion
from intelligence import config
from intelligence.store import Store
from intelligence.models import train_candidate, promote, load, infer
from intelligence.migrate import migrate
from intelligence.evaluation import evaluate_model

DSN = os.getenv("EIOS_TEST_DSN")
START = datetime(2026,1,1,tzinfo=timezone.utc)


def sample(index=0,service="ad",cpu=.2):
    start = START+timedelta(minutes=index)
    return {"service":service,"window_start":start,"window_end":start+timedelta(minutes=1),
        "feature_version":"2.0","features":{"cpu_cores":cpu,"memory_fraction":.4+(index%5)*.001},
        "quality":{},"evidence_event_ids":[str(uuid.uuid4())]}


def finding():
    return {"kind":"anomaly","detector":"ml:test:v1","severity":"medium","title":"CPU anomaly",
        "measurements":{"cpu_cores":2.0},"baseline":{},"analysis":{"candidate_cause":"Review CPU evidence"},
        "score":.9,"signal":"cpu"}


class FakeProducer:
    def __init__(self,error=None):
        self.error = error
    def produce(self,topic,key,value,on_delivery):
        on_delivery(self.error,None)
    def flush(self,seconds):
        return 0


@unittest.skipUnless(DSN,"EIOS_TEST_DSN must point to a disposable database")
class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DSN,autocommit=True) as conn:
            name = conn.execute("SELECT current_database()").fetchone()[0]
            if not name.endswith("_test"):
                raise RuntimeError("Integration database name must end with _test")
            root = Path(__file__).resolve().parents[2]
            conn.execute((root/"db/init.sql").read_text(),prepare=False)
            migrate(conn)

    def setUp(self):
        self.store = Store(DSN)
        self.transaction = self.store.conn.transaction(force_rollback=True)
        self.transaction.__enter__()
        self.directory = tempfile.TemporaryDirectory()
        self.model_dir = patch.object(config,"ARTIFACT_DIR",Path(self.directory.name))
        self.model_dir.start()

    def tearDown(self):
        self.transaction.__exit__(None,None,None)
        self.store.close()
        self.model_dir.stop()
        self.directory.cleanup()

    def test_migration_repeatable_and_preserves_events(self):
        event = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="test",observed_at=START,
            entity=Entity(kind=EntityKind.CONTAINER,id="ad",service="ad"),metrics={"cpu_cores":.1})
        self.store.ingest(event)
        migrate(self.store.conn)
        migrate(self.store.conn)
        self.assertEqual(self.store.rows("SELECT count(*) AS count FROM events WHERE event_id=%s",(event.event_id,))[0]["count"],1)

    def test_input_redaction_before_storage(self):
        event = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="test",observed_at=START,
            entity=Entity(kind=EntityKind.CONTAINER,id="ad"),attributes={"detail":"password=secret"})
        self.store.ingest(event)
        row = self.store.rows("SELECT attributes FROM events WHERE event_id=%s",(event.event_id,))[0]
        self.assertNotIn("secret",row["attributes"]["detail"])

    def test_replay_deduplicates_incident_outbox_and_case(self):
        window = sample()
        first = self.store.save_finding(window,finding())
        self.assertIsNotNone(first)
        IntelligenceInsight.model_validate(first)
        incident_id = first["incident_id"]
        case_id = self.store.rows("SELECT case_id FROM incidents WHERE incident_id=%s",(incident_id,))[0]["case_id"]
        self.assertIsNone(self.store.save_finding(window,finding()))
        self.assertEqual(self.store.rows("SELECT count(*) AS count FROM cases WHERE case_id=%s",(case_id,))[0]["count"],1)
        self.assertEqual(self.store.rows("SELECT count(*) AS count FROM intelligence_outbox")[0]["count"],2)

    def test_same_service_episode_reuses_case_id(self):
        self.store.save_finding(sample(),finding())
        self.store.save_finding(sample(4),finding())
        self.assertEqual(self.store.rows("SELECT count(*) AS count FROM cases")[0]["count"],1)
        case = self.store.rows("SELECT * FROM cases")[0]
        self.assertEqual(len(case["timeline"]),2)

    def test_failed_transaction_does_not_advance_marker(self):
        with self.assertRaises(RuntimeError):
            with self.store.conn.transaction():
                self.store.save_finding(sample(),finding())
                self.store.state("test-window",{"done":True})
                raise RuntimeError("simulated failure before commit")
        self.assertFalse(self.store.is_processed("test-window"))
        self.assertEqual(self.store.rows("SELECT count(*) AS count FROM intelligence_outbox")[0]["count"],0)

    def test_outbox_retries_until_acknowledged(self):
        self.store.save_finding(sample(),finding())
        self.store.publish_pending(FakeProducer("unavailable"))
        pending = self.store.rows("SELECT * FROM intelligence_outbox WHERE published_at IS NULL")
        self.assertEqual(len(pending),2)
        self.assertGreater(max(r["attempts"] for r in pending),0)
        self.store.publish_pending(FakeProducer())
        self.assertEqual(self.store.rows("SELECT count(*) AS count FROM intelligence_outbox WHERE published_at IS NULL")[0]["count"],0)

    def training_windows(self):
        windows = [sample(i,cpu=.1+(i%10)*.01) for i in range(100)]
        self.store.upsert_windows(windows)
        return windows

    def test_train_promote_infer_and_rollback(self):
        self.training_windows()
        first = train_candidate(self.store,"ad",START,START+timedelta(minutes=100),["cpu_cores","memory_fraction"])
        second = train_candidate(self.store,"ad",START,START+timedelta(minutes=100),["cpu_cores","memory_fraction"])
        promote(self.store,first["model_id"])
        promote(self.store,second["model_id"])
        promote(self.store,first["model_id"])
        active = self.store.rows("SELECT * FROM model_registry WHERE state='active'")
        self.assertEqual(len(active),1)
        self.assertEqual(str(active[0]["model_id"]),first["model_id"])
        ModelVersion.model_validate(active[0])
        analysis,result = infer(load(active[0]),active[0],sample(110,cpu=4))
        self.assertTrue(analysis["anomalous"])
        self.assertIsNotNone(result)

    def test_promotion_rejects_bad_validation(self):
        self.training_windows()
        candidate = train_candidate(self.store,"ad",START,START+timedelta(minutes=100),["cpu_cores"])
        record = self.store.rows("SELECT * FROM model_registry WHERE model_id=%s",(candidate["model_id"],))[0]
        record["validation"]["healthy_alert_fraction"] = .5
        self.store.conn.execute("UPDATE model_registry SET validation=%s WHERE model_id=%s",(Jsonb(record["validation"]),candidate["model_id"]))
        with self.assertRaisesRegex(ValueError,"Promotion rejected"):
            promote(self.store,candidate["model_id"])

    def test_evaluation_uses_disjoint_fault_and_healthy_windows(self):
        self.training_windows()
        candidate = train_candidate(self.store,"ad",START,START+timedelta(minutes=100),["cpu_cores"])
        tests = [sample(i,cpu=4 if 130<=i<140 else .1+(i%10)*.01) for i in range(110,160)]
        self.store.upsert_windows(tests)
        self.store.conn.execute("""INSERT INTO fault_windows(window_id,flag_key,started_at,ended_at,expected_domain,expected_entity)
            VALUES(%s,'adHighCpu',%s,%s,'infrastructure','ad')""",(
            uuid.uuid4(),START+timedelta(minutes=130),START+timedelta(minutes=140)))
        result = evaluate_model(self.store,candidate["model_id"],START+timedelta(minutes=110),START+timedelta(minutes=160))
        self.assertEqual(result["model"]["episode_recall"],1)
        self.assertEqual(result["scoped_fault_episodes"],1)
        self.assertGreater(result["excluded_or_missing_windows"],0)
        with self.assertRaisesRegex(ValueError,"Test must follow"):
            evaluate_model(self.store,candidate["model_id"],START,START+timedelta(minutes=160))
