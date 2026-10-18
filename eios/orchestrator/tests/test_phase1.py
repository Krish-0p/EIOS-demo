"""Integration checks against an isolated PostgreSQL database, never the live store."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from starlette.websockets import WebSocketDisconnect

import auth
import catalog
import config
import db
from auth_router import router as auth_router
from registry_router import router as registry_router
from middleware import SecurityMiddleware
from intelligence.migrate import migrate as migrate_intelligence
from phase1_migrate import migrate, DEFAULT_APPLICATION_ID, service_id

ORIGIN = "http://localhost:5173"
PASSWORD = "test-password-for-phase1"
LEGACY_EVENT, LEGACY_INCIDENT, LEGACY_CASE, LEGACY_APPROVAL = (uuid4() for _ in range(4))


def test_app():
    app = FastAPI()
    app.add_middleware(SecurityMiddleware)
    app.include_router(auth_router)
    app.include_router(registry_router)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        if await auth.authorize_websocket(ws):
            await ws.accept()
            await ws.send_json({"status": "authenticated"})
            await ws.close()

    return app


class Phase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "eios_phase1_test_" not in config.POSTGRES_DSN:
            raise RuntimeError("Tests require an isolated eios_phase1_test_* database")
        db.pool.open(wait=True)
        with db.pool.connection() as conn:
            conn.execute(Path("/app/db/init.sql").read_text(), prepare=False)
            migrate_intelligence(conn)
            conn.execute("""INSERT INTO events(event_id,schema_version,domain,source,observed_at,ingested_at,entity_kind,entity_id,entity_service)
                VALUES(%s,'1.0','infrastructure','prometheus',NOW(),NOW(),'service','payment','payment')""", (LEGACY_EVENT,))
            conn.execute("INSERT INTO cases(case_id,opened_at,severity,title,enrichment) VALUES(%s,NOW(),'high','Existing case',%s)",
                         (LEGACY_CASE, Jsonb({"service": "payment"})))
            conn.execute("""INSERT INTO incidents(incident_id,schema_version,domain,entity_kind,entity_id,entity_service,detected_at,
                window_start,window_end,detector,score,severity,title,case_id,evidence_event_ids)
                VALUES(%s,'1.0','infrastructure','service','payment','payment',NOW(),NOW(),NOW(),'existing',1,'high','Existing incident',%s,%s)""",
                (LEGACY_INCIDENT, LEGACY_CASE, [LEGACY_EVENT]))
            conn.execute("INSERT INTO approvals(approval_id,case_id,action,rationale,requested_at) VALUES(%s,%s,'inspect','Existing approval',NOW())",
                         (LEGACY_APPROVAL, LEGACY_CASE))
            migrate(conn)
            from auth_recovery_migrate import migrate as recovery_migrate
            from telemetry.migrate import migrate as telemetry_migrate
            from workflow_migrate import migrate as workflow_migrate
            recovery_migrate(conn)
            telemetry_migrate(conn)
            workflow_migrate(conn)

    @classmethod
    def tearDownClass(cls):
        db.pool.close()

    def setUp(self):
        with db.pool.connection() as conn:
            conn.execute("TRUNCATE user_sessions,password_reset_tokens,users")
        self.client = TestClient(test_app())
        self.client.headers["origin"] = ORIGIN

    def tearDown(self):
        self.client.close()

    def sign_in(self, username="admin", role="administrator"):
        result = self.client.post("/api/auth/register", json={"username": username, "password": PASSWORD, "role": role})
        self.assertEqual(result.status_code, 201, result.text)
        result = self.client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        self.assertEqual(result.status_code, 200, result.text)
        return result

    def make_application(self):
        result = self.client.post("/api/applications", json={"name": f"Test {uuid4()}", "environment": "test",
            "discovery_scope": {"compose_project": "phase1-test"}})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["application_id"]

    def container(self, identity="instance-1", state="running"):
        return {"id": identity, "full_id": identity, "name": identity, "image": "test/payment:1", "state": state,
                "compose_service": "payment", "ports": "8080", "health_state": "unknown",
                "labels": {"com.docker.compose.project": "phase1-test", "com.docker.compose.service": "payment"}}

    def test_migration_is_repeatable_and_preserves_existing_ids(self):
        with db.pool.connection() as conn:
            migrate(conn)
            migrate(conn)
            for table, key, identity in (("events", "event_id", LEGACY_EVENT), ("incidents", "incident_id", LEGACY_INCIDENT),
                                        ("cases", "case_id", LEGACY_CASE), ("approvals", "approval_id", LEGACY_APPROVAL)):
                self.assertEqual(conn.execute(f"SELECT count(*) FROM {table} WHERE {key}=%s", (identity,)).fetchone()[0], 1)
            row = conn.execute("SELECT application_id,service_id FROM events WHERE event_id=%s", (LEGACY_EVENT,)).fetchone()
            self.assertEqual(row, (DEFAULT_APPLICATION_ID, service_id(DEFAULT_APPLICATION_ID, "payment")))
            self.assertEqual(conn.execute("SELECT count(*) FROM schema_migrations WHERE version='phase1-v1'").fetchone()[0], 1)

    def test_first_setup_is_atomic_and_later_registration_requires_administrator(self):
        self.assertTrue(self.client.get("/api/auth/status").json()["setup_required"])
        first = self.client.post("/api/auth/register", json={"username": "admin", "password": PASSWORD, "role": "viewer"})
        self.assertEqual(first.json()["role"], "administrator")
        denied = self.client.post("/api/auth/register", json={"username": "intruder", "password": PASSWORD, "role": "administrator"})
        self.assertEqual(denied.status_code, 401)
        self.assertFalse(self.client.get("/api/auth/status").json()["setup_required"])

    def test_cookie_session_is_hashed_validated_and_revoked(self):
        self.assertEqual(self.client.get("/api/protected").status_code, 401)
        login = self.sign_in()
        cookie = self.client.cookies.get(auth.COOKIE_NAME)
        self.assertIn("HttpOnly", login.headers["set-cookie"])
        self.assertIn("SameSite=lax", login.headers["set-cookie"])
        self.assertNotIn("token", login.json())
        self.assertNotIn("api_key", login.json())
        self.assertEqual(self.client.get("/api/auth/me?username=intruder").json()["username"], "admin")
        stored = db._rows("SELECT token_hash FROM user_sessions")[0]["token_hash"]
        self.assertEqual(stored, auth.token_hash(cookie))
        self.assertNotEqual(stored, cookie)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.client.cookies.set(auth.COOKIE_NAME, cookie)
        self.assertEqual(self.client.get("/api/protected").status_code, 401)

    def test_wrong_credentials_expiration_and_disabled_users_are_rejected(self):
        self.sign_in()
        wrong = self.client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
        self.assertEqual(wrong.status_code, 401)
        with db.pool.connection() as conn:
            conn.execute("UPDATE user_sessions SET expires_at=NOW()-INTERVAL '1 second'")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        with db.pool.connection() as conn:
            conn.execute("UPDATE users SET disabled=TRUE")
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code, 401)

    def test_persistent_passwords_and_viewer_permissions(self):
        self.sign_in()
        stored = db._rows("SELECT password_hash FROM users WHERE username='admin'")[0]["password_hash"]
        self.assertNotEqual(stored, PASSWORD)
        self.assertTrue(auth.password_matches(PASSWORD, stored))
        self.assertEqual(self.client.post("/api/auth/register", json={"username": "reader", "password": PASSWORD, "role": "viewer"}).status_code, 201)
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"username": "reader", "password": PASSWORD})
        self.assertEqual(self.client.get("/api/applications").status_code, 200)
        self.assertEqual(self.client.post("/api/applications", json={"name": "Forbidden", "discovery_scope": {"compose_project": "x"}}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/register", json={"username": "elevated", "password": PASSWORD, "role": "administrator"}).status_code, 403)
        self.assertEqual(self.client.get("/api/auth/me?username=admin").json()["username"], "reader")

    def test_browser_origins_are_enforced(self):
        self.sign_in()
        self.assertEqual(self.client.post("/api/auth/logout", headers={"origin": "https://other.invalid"}).status_code, 403)
        del self.client.headers["origin"]
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"origin": ORIGIN}).status_code, 200)

    def test_signup_cannot_claim_administrator_or_race_first_setup(self):
        body = {'username':'signup-user','password':PASSWORD,'role':'administrator'}
        self.assertEqual(self.client.post('/api/auth/signup',json=body).status_code,409)
        self.sign_in()
        result = self.client.post('/api/auth/signup',json=body)
        self.assertEqual(result.status_code,201)
        self.assertEqual(result.json()['role'],'viewer')

    def test_recovery_is_private_one_time_and_revokes_existing_sessions(self):
        self.sign_in()
        self.client.post('/api/auth/register',json={'username':'recovery-user','password':PASSWORD,'role':'viewer'})
        uid = db._rows("SELECT user_id FROM users WHERE username='recovery-user'")[0]['user_id']
        with TestClient(test_app()) as reader:
            reader.headers['origin']=ORIGIN
            reader.post('/api/auth/login',json={'username':'recovery-user','password':PASSWORD})
            public = reader.post('/api/auth/forgot-password',json={'username':'recovery-user'})
            self.assertNotIn('token',public.json())
            self.assertEqual(reader.post(f'/api/auth/users/{uid}/password-reset').status_code,403)
            result = self.client.post(f'/api/auth/users/{uid}/password-reset')
            self.assertEqual(result.status_code,200)
            token = result.json()['reset_token']
            stored = db._rows('SELECT token_hash FROM password_reset_tokens WHERE user_id=%(uid)s',{'uid':uid})[0]['token_hash']
            self.assertEqual(stored,auth.token_hash(token))
            reset = {'token':token,'password':'replacement-test-password'}
            self.assertEqual(self.client.post('/api/auth/reset-password',json=reset).status_code,200)
            self.assertEqual(reader.get('/api/auth/me').status_code,401)
            self.assertEqual(self.client.post('/api/auth/reset-password',json=reset).status_code,400)
            self.assertEqual(reader.post('/api/auth/login',json={'username':'recovery-user','password':'replacement-test-password'}).status_code,200)
            expired=self.client.post(f'/api/auth/users/{uid}/password-reset').json()['reset_token']
            with db.pool.connection() as conn:
                conn.execute("UPDATE password_reset_tokens SET expires_at=NOW()-INTERVAL '1 second' WHERE token_hash=%s",
                    (auth.token_hash(expired),))
            self.assertEqual(self.client.post('/api/auth/reset-password',json={'token':expired,'password':PASSWORD}).status_code,400)

    def test_role_change_revokes_sessions_and_self_administration_is_rejected(self):
        self.sign_in()
        self.client.post('/api/auth/register',json={'username':'role-user','password':PASSWORD,'role':'operator'})
        uid = db._rows("SELECT user_id FROM users WHERE username='role-user'")[0]['user_id']
        admin_id = db._rows("SELECT user_id FROM users WHERE username='admin'")[0]['user_id']
        with TestClient(test_app()) as other:
            other.headers['origin']=ORIGIN
            other.post('/api/auth/login',json={'username':'role-user','password':PASSWORD})
            response=self.client.patch(f'/api/auth/users/{uid}/role',json={'role':'viewer'})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()['sessions_revoked'])
            self.assertEqual(other.get('/api/auth/me').status_code,401)
        self.assertEqual(self.client.patch(f'/api/auth/users/{admin_id}/role',json={'role':'viewer'}).status_code,400)
        self.assertEqual(self.client.post(f'/api/auth/users/{admin_id}/disable').status_code,400)

    def test_configured_api_rate_limit_is_enforced_by_actual_middleware(self):
        self.sign_in(username='limit-'+uuid4().hex[:12])
        with patch.dict(os.environ,{'EIOS_RATE_LIMIT_REQUESTS':'2','EIOS_RATE_LIMIT_WINDOW':'60'}):
            self.assertEqual(self.client.get('/api/protected').status_code,200)
            self.assertEqual(self.client.get('/api/protected').status_code,200)
            blocked=self.client.get('/api/protected')
            self.assertEqual(blocked.status_code,429)
            self.assertEqual(blocked.headers['retry-after'],'60')

    def test_discovery_scope_is_required_and_exact(self):
        self.sign_in()
        result = self.client.post("/api/applications", json={"name": "Broad scan", "discovery_scope": {}})
        self.assertEqual(result.status_code, 422)
        container = self.container()
        self.assertTrue(catalog.matches_scope(container, {"compose_project": "phase1-test"}))
        self.assertFalse(catalog.matches_scope(container, {"compose_project": "another-project"}))
        self.assertFalse(catalog.matches_scope(container, {}))
        self.assertFalse(catalog.matches_scope(container, {"container_names": ["other-container"]}))
        self.assertFalse(catalog.matches_scope(container, {"labels": {"team": "other"}}))

    def test_runtime_offline_recreation_and_replicas_preserve_service_identity(self):
        self.sign_in()
        app = self.make_application()
        instance = str(uuid4())
        with patch("catalog.docker_inventory", return_value=[self.container(instance), self.container(instance+"-replica")]):
            catalog.reconcile(app)
        initial = catalog.services(app)
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial[0]["runtime_state"], "online")
        self.assertEqual(initial[0]["telemetry_state"], "not_observed")
        stable = initial[0]["service_id"]
        with patch("catalog.docker_inventory", return_value=[]):
            catalog.reconcile(app)
        offline = catalog.services(app)
        self.assertEqual(offline[0]["runtime_state"], "offline")
        self.assertEqual(offline[0]["service_id"], stable)
        with patch("catalog.docker_inventory", return_value=[self.container(instance+"-recreated")]):
            catalog.reconcile(app)
        recovered = catalog.services(app)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["service_id"], stable)
        self.assertEqual(recovered[0]["runtime_state"], "online")

    def test_failed_discovery_is_unknown_and_keeps_last_runtime_observation(self):
        self.sign_in()
        app = self.make_application()
        with patch("catalog.docker_inventory", return_value=[self.container(str(uuid4()))]):
            catalog.reconcile(app)
        with patch("catalog.docker_inventory", side_effect=RuntimeError("unreachable")):
            with self.assertRaises(HTTPException):
                catalog.reconcile(app)
        row = catalog.services(app)[0]
        self.assertEqual(row["runtime_state"], "unknown")
        self.assertEqual(row["last_runtime_state"], "online")
        self.assertEqual(row["connection_state"], "unavailable")

    def test_cross_application_runtime_ownership_cannot_be_stolen(self):
        self.sign_in()
        first, second = self.make_application(), self.make_application()
        with patch("catalog.docker_inventory", return_value=[self.container(str(uuid4()))]):
            catalog.reconcile(first)
            with self.assertRaises(HTTPException) as error:
                catalog.reconcile(second)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(catalog.services(second)), 0)

    def test_manual_runtime_alias_keeps_identity_when_discovered(self):
        self.sign_in()
        app = self.make_application()
        saved = self.client.post(f"/api/applications/{app}/services", json={"name": "billing", "runtime_identifier": "payment"})
        self.assertEqual(saved.status_code, 201)
        stable = saved.json()["service_id"]
        with patch("catalog.docker_inventory", return_value=[self.container(str(uuid4()))]):
            catalog.reconcile(app)
        result = catalog.services(app)
        self.assertEqual(len(result), 1)
        self.assertEqual(str(result[0]["service_id"]), stable)
        self.assertEqual(result[0]["runtime_state"], "online")
        self.assertEqual(self.client.post(f"/api/applications/{app}/services", json={"name": "payment"}).status_code, 409)

    def test_identity_routes_explicit_application_without_name_collision(self):
        self.sign_in()
        app = self.make_application()
        with patch("catalog.docker_inventory", return_value=[self.container(str(uuid4()))]):
            catalog.reconcile(app)
        identity = uuid4()
        with db.pool.connection() as conn:
            conn.execute("""INSERT INTO events(event_id,schema_version,domain,source,observed_at,ingested_at,entity_kind,entity_id,entity_service,attributes)
                VALUES(%s,'1.0','infrastructure','explicit-test',NOW(),NOW(),'service','payment','payment',%s)""",
                (identity, Jsonb({"application_id": app})))
        row = db._rows("SELECT application_id,service_id FROM events WHERE event_id=%(id)s", {"id": identity})[0]
        self.assertEqual(str(row["application_id"]), app)
        self.assertEqual(row["service_id"], service_id(app, "payment"))
        self.assertNotEqual(row["service_id"], service_id(DEFAULT_APPLICATION_ID, "payment"))
        self.assertEqual(catalog.services(app)[0]["telemetry_state"], "fresh")
        with db.pool.connection() as conn:
            conn.execute("UPDATE applications SET discovery_checked_at=NOW()-INTERVAL '10 minutes' WHERE application_id=%s", (app,))
            conn.execute("UPDATE events SET observed_at=NOW()-INTERVAL '1 hour' WHERE event_id=%s", (identity,))
        stale = catalog.services(app)[0]
        self.assertEqual(stale["runtime_state"], "unknown")
        self.assertEqual(stale["connection_state"], "stale")
        self.assertEqual(stale["telemetry_state"], "stale")

    def test_websocket_requires_valid_session_and_allowed_origin(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws", headers={"origin": ORIGIN}):
                pass
        self.sign_in()
        with self.client.websocket_connect("/ws", headers={"origin": ORIGIN}) as ws:
            self.assertEqual(ws.receive_json()["status"], "authenticated")
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws", headers={"origin": "https://other.invalid"}):
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
