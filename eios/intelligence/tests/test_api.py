"""API compatibility checks in the disposable database, without Kafka consumers."""
from datetime import datetime, timedelta, timezone
import os
import unittest

DSN = os.getenv("EIOS_TEST_DSN")


@unittest.skipUnless(DSN and os.getenv("EIOS_API_TESTS"),"Run API tests inside the orchestrator test image")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import db
        from agents_router import router as agents
        from intelligence_router import router as intelligence
        from intelligence.store import Store
        from pathlib import Path
        import psycopg
        with psycopg.connect(DSN,autocommit=True) as conn:
            if not conn.execute("SELECT current_database()").fetchone()[0].endswith("_test"):
                raise RuntimeError("API tests require disposable database")
            conn.execute((Path(__file__).resolve().parents[2]/"db/init.sql").read_text(),prepare=False)
        cls.store = Store(DSN)
        from phase1_migrate import migrate as migrate_registry
        from auth_recovery_migrate import migrate as migrate_recovery
        from telemetry.migrate import migrate as migrate_telemetry
        from workflow_migrate import migrate as migrate_workflow
        for migration in (migrate_registry, migrate_recovery, migrate_telemetry, migrate_workflow):
            migration(cls.store.conn)
        now = datetime.now(timezone.utc)
        cls.insight = cls.store.save_finding({"service":"api-test","window_start":now-timedelta(minutes=3),
            "window_end":now-timedelta(minutes=2),"evidence_event_ids":[]},{
            "kind":"anomaly","detector":"ml:api-test:v1","severity":"medium","title":"Test insight",
            "measurements":{"cpu_cores":2},"baseline":{},"analysis":{"candidate_cause":"Inspect evidence"},
            "score":.8,"signal":"cpu"})
        cls.case_id = str(cls.store.rows("SELECT case_id FROM incidents WHERE incident_id=%s",(cls.insight["incident_id"],))[0]["case_id"])
        db.pool.open()
        cls.pool = db.pool
        app = FastAPI()
        # Router compatibility is isolated here; live authentication and RBAC
        # are exercised separately against the complete middleware stack.
        @app.middleware('http')
        async def test_actor(request, call_next):
            request.state.user = {'username': 'api-test', 'role': 'administrator'}
            return await call_next(request)
        app.include_router(agents)
        app.include_router(intelligence)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.pool.close()
        cls.store.close()
        # The entire disposable database is removed after the test run.

    def test_insight_typed_response_and_incident_link(self):
        response = self.client.get("/api/intelligence/insights?service=api-test")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()[0]["recommendation"]["execution"],"manual")
        incident = self.client.get(f"/api/incidents/{self.insight['incident_id']}/intelligence")
        self.assertEqual(incident.json()[0]["insight_id"],self.insight["insight_id"])

    def test_chat_preserves_contract_without_fabricated_health(self):
        response = self.client.post("/api/ai/chat",json={"query":"show anomalies","context":{"service":"api-test"}})
        body = response.json()
        self.assertEqual(response.status_code,200)
        self.assertTrue({"reply","timestamp","context_snapshot"} <= body.keys())
        self.assertEqual(body["engine"],"stored_analytics")
        self.assertNotIn("3800MB",body["reply"])
        self.assertNotIn("0.08",body["reply"])
        self.assertIn(self.insight["insight_id"],body["sources"])

    def test_feedback_persists_without_changing_model(self):
        response = self.client.post("/api/intelligence/feedback",json={
            "insight_id":self.insight["insight_id"],"verdict":"confirm","operator":"test"})
        self.assertEqual(response.status_code,201)
        self.assertFalse(response.json()["model_updated"])
        self.assertEqual(self.store.rows("SELECT status FROM intelligence_insights WHERE insight_id=%s",
            (self.insight["insight_id"],))[0]["status"],"confirmed")

    def test_invalid_verdict_and_limits_rejected(self):
        self.assertEqual(self.client.post("/api/intelligence/feedback",json={
            "insight_id":self.insight["insight_id"],"verdict":"unknown"}).status_code,422)
        self.assertEqual(self.client.get("/api/intelligence/history?service=ad&minutes=0").status_code,422)
        self.assertEqual(self.client.get("/api/intelligence/insights?limit=0").status_code,422)

    def test_cases_and_decisions_are_persistent_and_manual(self):
        case = self.client.get(f"/api/cases/{self.case_id}")
        self.assertEqual(case.status_code,200)
        self.assertEqual(case.json()["case_id"],self.case_id)
        response = self.client.post(f"/api/cases/{self.case_id}/approvals")
        self.assertEqual(response.status_code,201)
        approval_id = response.json()["approval_id"]
        response = self.client.post(f"/api/approvals/{approval_id}/action",json={"decision":"approve","operator":"test"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["approval"]["status"],"approved")
        self.assertIn("No resource action executed",response.json()["message"])
        self.assertEqual(self.client.post(f"/api/approvals/{approval_id}/action",json={"decision":"reject"}).status_code,409)

    def test_status_and_empty_model_registry_truthful(self):
        response = self.client.get("/api/intelligence/status")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["state"],"unavailable")
        self.assertTrue(response.json()["training_required"])
        self.assertEqual(self.client.get("/api/intelligence/models").json(),[])
