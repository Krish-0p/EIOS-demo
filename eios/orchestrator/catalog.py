"""Persistent application membership, scoped runtime reconciliation, and freshness."""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import db
from phase1_migrate import service_id

log = logging.getLogger("eios.catalog")
DISCOVERY_STALE_SECONDS = 90
TELEMETRY_STALE_SECONDS = 240


def application(application_id):
    rows = db._rows("SELECT * FROM applications WHERE application_id=%(id)s", {"id": application_id})
    if not rows:
        raise HTTPException(404, "Application not found")
    return rows[0]


def discovery_state(app, now=None):
    now = now or datetime.now(timezone.utc)
    if app["discovery_error"]:
        return "unavailable"
    checked = app["discovery_checked_at"]
    if not checked:
        return "not_discovered"
    return "stale" if (now-checked).total_seconds() > DISCOVERY_STALE_SECONDS else "connected"


def application_view(app):
    return {**app, "status": discovery_state(app), "connection_state": discovery_state(app),
            "telemetry_connection_state": "configured" if app["telemetry_config"] else "not_configured"}


def matches_scope(container, scope):
    labels = container.get("labels") or {}
    project = scope.get("compose_project")
    expected = scope.get("labels") or {}
    names = scope.get("container_names") or []
    if not (project or expected or names):
        return False
    if project and labels.get("com.docker.compose.project") != project:
        return False
    if any(labels.get(key) != value for key, value in expected.items()):
        return False
    if names and container["name"] not in names:
        return False
    return labels.get("com.docker.compose.service", container["name"]) not in scope.get("exclude_services", [])


def docker_inventory(scope):
    from docker_router import _get_client, _parse_container
    client = _get_client()
    labels = [f"{key}={value}" for key, value in (scope.get("labels") or {}).items()]
    if scope.get("compose_project"):
        labels.append(f"com.docker.compose.project={scope['compose_project']}")
    # Docker applies project/label filters before inspecting containers. No stats calls.
    containers = client.containers.list(all=True, filters={"label": labels} if labels else {})
    result = []
    for container in containers:
        row = _parse_container(container)
        if matches_scope(row, scope):
            row["health_state"] = (container.attrs.get("State", {}).get("Health") or {}).get("Status", "unknown")
            row["language"] = next((value.split("=", 1)[1] for value in container.attrs.get("Config", {}).get("Env", [])
                                    if value.startswith("OTEL_RESOURCE_ATTRIBUTES=telemetry.sdk.language=")), None)
            result.append(row)
    return result


def reconcile(application_id, actor="discovery"):
    app = application(application_id)
    try:
        with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"discovery:{application_id}",))
            containers = docker_inventory(app["discovery_scope"])
            cur.execute("""UPDATE service_runtime_instances r SET runtime_state='missing',checked_at=NOW()
                FROM services s WHERE s.service_id=r.service_id AND s.application_id=%s""", (application_id,))
            for container in containers:
                runtime_key = container.get("compose_service") or container["name"]
                cur.execute("SELECT name FROM services WHERE application_id=%s AND runtime_identifier=%s", (application_id, runtime_key))
                binding = cur.fetchone()
                name = binding["name"] if binding else runtime_key
                stable = service_id(application_id, name)
                cur.execute("""INSERT INTO services(service_id,application_id,name,runtime_identifier,language,version,labels,last_seen_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,NOW()) ON CONFLICT(application_id,name) DO UPDATE
                    SET runtime_identifier=EXCLUDED.runtime_identifier,labels=services.labels||EXCLUDED.labels,
                        language=COALESCE(EXCLUDED.language,services.language),version=EXCLUDED.version,last_seen_at=NOW()
                    RETURNING service_id""", (stable, application_id, name, runtime_key, container.get("language"),
                        container["image"], Jsonb(container.get("labels") or {})))
                stable = cur.fetchone()["service_id"]
                cur.execute("""INSERT INTO service_runtime_instances(container_id,service_id,container_name,image,ports,runtime_state,health_state)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(container_id) DO UPDATE SET container_name=EXCLUDED.container_name,
                        image=EXCLUDED.image,ports=EXCLUDED.ports,runtime_state=EXCLUDED.runtime_state,
                        health_state=EXCLUDED.health_state,checked_at=NOW(),last_seen_at=NOW()
                    WHERE service_runtime_instances.service_id=EXCLUDED.service_id RETURNING container_id""",
                    (container.get("full_id") or container["id"], stable, container["name"], container["image"],
                     container.get("ports"), container["state"], container.get("health_state", "unknown")))
                if cur.fetchone() is None:
                    raise HTTPException(409, "A matched container is already registered to another application. Narrow the discovery scope.")
            cur.execute("UPDATE applications SET discovery_checked_at=NOW(),discovery_error=NULL,updated_at=NOW() WHERE application_id=%s",
                        (application_id,))
            if actor != "discovery":
                import auth
                auth.audit(conn, actor, "catalog.discovered", "application", application_id)
        return {"status": "discovered", "matched_containers": len(containers), "application_id": str(application_id)}
    except Exception as exc:
        # A failed observation cannot establish that any registered service went down.
        message = exc.detail if isinstance(exc, HTTPException) and exc.status_code == 409 else "Docker discovery unavailable"
        db._rows("UPDATE applications SET discovery_error=%(error)s,updated_at=NOW() WHERE application_id=%(id)s RETURNING application_id",
                 {"id": application_id, "error": message})
        if isinstance(exc, HTTPException) and exc.status_code == 409:
            raise
        log.warning("Docker discovery failed for application %s (%s)", application_id, type(exc).__name__)
        raise HTTPException(503, message) from exc


def services(application_id):
    app = application(application_id)
    rows = db._rows("""SELECT s.*,
        (SELECT max(e.observed_at) FROM events e WHERE e.service_id=s.service_id) AS last_telemetry_at,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('container_id',r.container_id,'container_name',r.container_name,
            'runtime_state',r.runtime_state,'health_state',r.health_state,'image',r.image,'ports',r.ports,'checked_at',r.checked_at))
            FROM service_runtime_instances r WHERE r.service_id=s.service_id),'[]') AS runtime_instances
        FROM services s WHERE s.application_id=%(id)s ORDER BY s.name""", {"id": application_id})
    now = datetime.now(timezone.utc)
    connection = discovery_state(app, now)
    for row in rows:
        instances = row["runtime_instances"]
        states = {item["runtime_state"] for item in instances}
        last_state = "online" if "running" in states else "starting" if states & {"created", "restarting"} else "offline" if instances else "unknown"
        row["last_runtime_state"] = last_state
        row["runtime_state"] = last_state if connection == "connected" else "unknown"
        health = {item["health_state"] for item in instances if item["runtime_state"] == "running"}
        row["health_state"] = "unknown" if row["runtime_state"] != "online" else "unhealthy" if "unhealthy" in health else "healthy" if "healthy" in health else "unknown"
        row["connection_state"] = connection
        observed = row["last_telemetry_at"]
        row["telemetry_state"] = "not_observed" if not observed else "stale" if (now-observed).total_seconds() > TELEMETRY_STALE_SECONDS else "fresh"
        row["dependencies_state"] = "not_collected"
    return rows


def discovery_loop(stop):
    while not stop.is_set():
        try:
            applications = db._rows("SELECT application_id FROM applications ORDER BY created_at")
        except Exception:
            log.exception("Catalog database temporarily unavailable")
            stop.wait(30)
            continue
        for row in applications:
            if stop.is_set():
                return
            try:
                reconcile(row["application_id"])
            except HTTPException:
                pass
            except Exception:
                log.exception("Catalog reconciliation failed")
        stop.wait(30)
