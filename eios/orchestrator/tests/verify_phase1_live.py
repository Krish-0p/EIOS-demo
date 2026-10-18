"""Explicit live Phase 1 acceptance run; credentials come from the environment.

The optional stop/start test uses the existing runtime APIs and always attempts
to restore the selected service. Run only against an authorized demo instance.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from websockets.sync.client import connect

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:5173")
parser.add_argument("--username", default="admin")
parser.add_argument("--stop-service")
parser.add_argument("--pause-for-restart", action="store_true")
parser.add_argument("--evidence", default="/evidence/live-verification.json")
args = parser.parse_args()
password = os.environ["EIOS_VERIFY_PASSWORD"]
origin = "http://localhost:5173"
default_id = "6b42866e-e214-57e4-a7bd-e0ce18ade732"
evidence = {"started_at": datetime.now(timezone.utc).isoformat()}

def log(message):
    print(message, flush=True)

def save_evidence():
    Path(args.evidence).write_text(json.dumps(evidence, indent=2))

def later(value, reference):
    return bool(value) and datetime.fromisoformat(value.replace("Z", "+00:00")) > datetime.fromisoformat(reference)

with httpx.Client(base_url=args.base_url, headers={"Origin": origin}, timeout=60) as client:
    def api(method, path, body=None):
        response = client.request(method, path, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code} {response.text[:180]}")
        return response.json()

    anonymous = client.get("/api/applications")
    assert anonymous.status_code == 401
    evidence["anonymous_access"] = anonymous.status_code
    if api("GET", "/api/auth/status")["setup_required"]:
        api("POST", "/api/auth/register", {"username": args.username, "password": password})
        log("Persisted the existing demo administrator with its existing password.")
    login = api("POST", "/api/auth/login", {"username": args.username, "password": password})
    assert "token" not in login and "api_key" not in login
    user = api("GET", "/api/auth/me")
    assert user["username"] == args.username
    evidence["authenticated_user"] = {"username": user["username"], "role": user["role"]}
    evidence["initial_totals"] = api("GET", "/api/stats")["totals"]
    evidence["default_discovery"] = api("POST", f"/api/applications/{default_id}/discovery")
    baseline_services = api("GET", f"/api/applications/{default_id}/services")
    evidence["default_registered_services"] = len(baseline_services)

    applications = api("GET", "/api/applications")
    platform = next((app for app in applications if app["name"] == "EIOS Platform" and app["environment"] == "demo"), None)
    if not platform:
        platform = api("POST", "/api/applications", {"name": "EIOS Platform", "environment": "demo", "runtime_type": "docker",
            "discovery_scope": {"compose_project": os.getenv("EIOS_DEMO_COMPOSE_PROJECT", "opentelemetry-demo"),
                                "container_names": ["eios-orchestrator", "eios-dashboard"]},
            "labels": {"owner": "eios"}, "telemetry_config": {}})
    platform_id = platform["application_id"]
    manual = api("POST", f"/api/applications/{platform_id}/services", {"name": "eios-orchestrator"})
    discovery = api("POST", f"/api/applications/{platform_id}/discovery")
    platform_services = api("GET", f"/api/applications/{platform_id}/services")
    assert len(platform_services) == 2
    assert next(row for row in platform_services if row["name"] == "eios-orchestrator")["service_id"] == manual["service_id"]
    assert all(row["runtime_state"] == "online" for row in platform_services)
    evidence["created_application"] = {"application_id": platform_id, "name": platform["name"],
                                       "discovery": discovery, "services": [{"name": row["name"], "service_id": row["service_id"]} for row in platform_services]}
    log(json.dumps({"stage": "registry_verified", "application_id": platform_id, "scoped_containers": discovery["matched_containers"],
                    "default_services": len(baseline_services)}))
    save_evidence()

    if args.pause_for_restart:
        gate = uuid4().hex
        evidence["restart_gate"] = gate
        save_evidence()
        log("READY_FOR_RESTART")
        deadline = time.monotonic() + 300
        while True:
            marker = Path("/evidence/restart-ready.txt")
            if marker.is_file() and marker.read_text().strip() == gate:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Timed out waiting for restart verification")
            time.sleep(2)
    # Same cookie must work after API/database/worker restart; no new login.
    assert api("GET", "/api/auth/me")["username"] == args.username
    restored = api("GET", f"/api/applications/{platform_id}/services")
    assert {row["service_id"] for row in restored} == {row["service_id"] for row in platform_services}
    evidence["session_and_catalog_survived_restart"] = True
    api("POST", f"/api/applications/{default_id}/discovery")

    if args.stop_service:
        name = args.stop_service
        row = next(row for row in api("GET", f"/api/applications/{default_id}/services") if row["name"] == name)
        assert row["runtime_state"] == "online", "Target must be running before the controlled stop"
        instance = next(item for item in row["runtime_instances"] if item["runtime_state"] == "running")
        container_id = instance["container_id"]
        stable = row["service_id"]
        flags_before = {flag["key"]: flag["defaultVariant"] for flag in api("GET", "/api/flags")}
        window = api("POST", "/api/faults/start", {"flag_key": f"manual:{name}:service-stop", "apply": False,
            "expected_domain": "infrastructure", "expected_entity": name, "notes": "Phase 1 controlled service persistence stop/start verification"})
        fault = {"service": name, "service_id": stable, "container_id": container_id,
                 "window_id": window["window_id"], "start_time": datetime.now(timezone.utc).isoformat()}
        stopped = False
        try:
            stopped = True
            api("POST", f"/api/docker/containers/{container_id}/stop")
            api("POST", f"/api/applications/{default_id}/discovery")
            offline = next(item for item in api("GET", f"/api/applications/{default_id}/services") if item["service_id"] == stable)
            assert offline["runtime_state"] == "offline", offline["runtime_state"]
            fault["offline_observed_at"] = datetime.now(timezone.utc).isoformat()
            fault["offline_runtime_state"] = offline["runtime_state"]
            fault["offline_telemetry_state"] = offline["telemetry_state"]
            log(json.dumps({"stage": "offline_verified", "service": name, "service_id": stable}))
        finally:
            if stopped:
                api("POST", f"/api/docker/containers/{container_id}/start")
            api("POST", f"/api/faults/{window['window_id']}/stop")
            fault["end_time"] = datetime.now(timezone.utc).isoformat()
        api("POST", f"/api/applications/{default_id}/discovery")
        recovered = next(item for item in api("GET", f"/api/applications/{default_id}/services") if item["service_id"] == stable)
        assert recovered["runtime_state"] == "online"
        assert flags_before == {flag["key"]: flag["defaultVariant"] for flag in api("GET", "/api/flags")}
        fault["recovered_runtime_state"] = recovered["runtime_state"]
        fault["runtime_recovered_at"] = datetime.now(timezone.utc).isoformat()
        evidence["controlled_stop"] = fault
        save_evidence()
        log(json.dumps({"stage": "recovery_verified", "service": name, "service_id": stable}))

    cookie = "; ".join(f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar)
    ws_url = args.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
    with connect(ws_url, origin=origin, additional_headers={"Cookie": cookie}, open_timeout=15) as ws:
        log("Waiting for a live WebSocket event; detector warm-up can exceed one minute.")
        payload = json.loads(ws.recv(timeout=200))
        evidence["websocket_message_type"] = payload["type"]
        log(json.dumps({"stage": "websocket_verified", "message_type": payload["type"]}))
    for _ in range(25):
        totals = api("GET", "/api/stats")["totals"]
        if totals["events"] > evidence["initial_totals"]["events"] and totals["incidents"] > evidence["initial_totals"]["incidents"]:
            break
        log(json.dumps({"stage": "waiting_for_pipeline", "totals": totals}))
        time.sleep(10)
    assert totals["events"] > evidence["initial_totals"]["events"], "No new persisted telemetry"
    assert totals["incidents"] > evidence["initial_totals"]["incidents"], "No new persisted detections"
    evidence["final_totals"] = totals
    evidence["latest_event"] = api("GET", f"/api/events?limit=1&application_id={default_id}")[0]
    evidence["latest_incident"] = api("GET", f"/api/incidents?limit=1&application_id={default_id}")[0]
    assert evidence["latest_event"]["application_id"] == default_id
    assert evidence["latest_incident"]["application_id"] == default_id
    if args.stop_service:
        for _ in range(13):
            recovered = next(item for item in api("GET", f"/api/applications/{default_id}/services") if item["service_id"] == stable)
            if later(recovered["last_telemetry_at"], fault["end_time"]):
                break
            time.sleep(10)
        assert later(recovered["last_telemetry_at"], fault["end_time"]), "No post-restart telemetry observed"
        fault["telemetry_recovered_at"] = recovered["last_telemetry_at"]
        fault["recovered_telemetry_state"] = recovered["telemetry_state"]
    evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_evidence()
    api("POST", "/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    log(json.dumps({"stage": "complete", "events": totals["events"], "incidents": totals["incidents"], "logout_revoked": True}))
