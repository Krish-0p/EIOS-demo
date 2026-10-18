"""EIOS Services & Workload Router
Exposes microservices RED health, dependency topology graph,
per-service operation breakdowns, and OpenTelemetry workload connection.
"""
from __future__ import annotations

import logging
import time
from uuid import UUID
from typing import Any
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import config
import db
import topology
import auth
import catalog
from phase1_migrate import DEFAULT_APPLICATION_ID
from psycopg.types.json import Jsonb

log = logging.getLogger("eios.services")

router = APIRouter(prefix="/api", tags=["services"])

@router.get("/services")
def get_services(window: str | None = None, application_id: UUID = DEFAULT_APPLICATION_ID) -> dict:
    """Returns RED telemetry and status for all microservices in the substrate."""
    from workflow_topology import snapshot
    current = snapshot(application_id)
    from workflow_store import rows
    active_faults=rows('''SELECT f.* FROM fault_windows f LEFT JOIN experiment_runs r ON r.fault_window_id=f.window_id
        WHERE f.ended_at IS NULL AND (r.application_id=%s OR r.experiment_id IS NULL AND %s::uuid=%s::uuid)''',
        (application_id,application_id,DEFAULT_APPLICATION_ID))
    fault_map={f['expected_entity']:f for f in active_faults if f['expected_entity']}
    for node in current['services']:
        node['injected_fault']=fault_map.get(node['service'])
    # The persistent catalog is authoritative; missing telemetry never removes a node.
    return {**current,'window':window or '5m','degraded_sources':[] if current.get('dependency_state')=='available' else ['jaeger'],
            'jaeger_ui':config.JAEGER_UI_URL,'open_faults':active_faults}


def legacy_services_telemetry(window: str | None = None) -> dict:
    """Retained legacy collector for integrations that explicitly need raw RED queries."""
    view = topology.collect(window=window)
    open_faults = db.fault_windows()
    active_faults = [f for f in open_faults if f.get("ended_at") is None]

    # Map faults by targeted service or entity
    fault_map = {}
    for f in active_faults:
        ent = f.get("expected_entity")
        if ent:
            fault_map[ent] = f

    # Enrich each service with injected_fault and recent incident count
    all_incidents = db.incidents(limit=200)
    incident_counts: dict[str, int] = {}
    for inc in all_incidents:
        srv = inc.get("entity_service") or inc.get("entity_id")
        if srv:
            incident_counts[srv] = incident_counts.get(srv, 0) + 1

    for s in view.get("services", []):
        name = s["service"]
        s["incidents_24h"] = incident_counts.get(name, 0)
        s["injected_fault"] = fault_map.get(name, None)

    view["open_faults"] = active_faults
    view["application_id"] = str(DEFAULT_APPLICATION_ID)
    identities = {row["name"]: str(row["service_id"]) for row in db._rows("SELECT name,service_id FROM services WHERE application_id=%(id)s", {"id": DEFAULT_APPLICATION_ID})}
    for row in view.get("services", []):
        row["application_id"] = str(DEFAULT_APPLICATION_ID)
        row["service_id"] = identities.get(row["service"])
    return view


@router.get("/services/graph")
def get_services_graph(hours: int = Query(1, ge=1, le=24), application_id: UUID = DEFAULT_APPLICATION_ID) -> dict:
    """Returns the service call graph derived from Jaeger traces."""
    from workflow_topology import snapshot
    current = snapshot(application_id)
    return {'nodes':[s['service'] for s in current['services']],'edges':current['edges'],
        'available':bool(current['services']),'reason':current.get('reason'),
        'dependency_state':current.get('dependency_state','unknown'),'application_id':str(application_id)}


@router.get("/services/{service_name}")
def get_service_detail(service_name: str, window: str | None = None, application_id: UUID = DEFAULT_APPLICATION_ID) -> dict:
    """Returns detailed metrics, operations, dependency edges, and incidents for one service."""
    coll = get_services(window,application_id)
    found_service = None
    for s in coll.get("services", []):
        if s["service"] == service_name:
            found_service = s
            break

    if not found_service:
        found_service = topology._blank_row(service_name)
        found_service["status"] = "unknown"
        found_service["reason"] = "no telemetry recorded yet"

    ops = topology.operations(service_name, window=window, limit=12) if application_id==DEFAULT_APPLICATION_ID else []
    g = {'edges':coll.get('edges',[])}

    upstreams = [e["source"] for e in g.get("edges", []) if e.get("target") == service_name]
    downstreams = [e["target"] for e in g.get("edges", []) if e.get("source") == service_name]

    service_incidents = [
        inc for inc in db.incidents(limit=100,application_id=application_id)
        if (inc.get("entity_service") == service_name or inc.get("entity_id") == service_name)
    ]

    traces_url = f"{config.JAEGER_UI_URL}/search?service={service_name}"

    return {
        "service": found_service,
        "window": coll.get("window", "5m"),
        "operations": ops,
        "upstreams": sorted(set(upstreams)),
        "downstreams": sorted(set(downstreams)),
        "incidents": service_incidents,
        "traces_url": traces_url,
    }


class ConnectWorkloadRequest(BaseModel):
    workload_type: str = "opentelemetry-demo"
    name: str = "OpenTelemetry Demo / Online Boutique"
    collector_endpoint: str | None = None
    prometheus_url: str | None = None
    jaeger_url: str | None = None


@router.post("/workloads/connect")
def connect_workload(req: ConnectWorkloadRequest, request: Request) -> dict:
    """Compatibility adapter: persist endpoint configuration without claiming activation."""
    user = auth.require_role(request, "administrator")
    current = catalog.application(DEFAULT_APPLICATION_ID)
    settings = dict(current["telemetry_config"])
    for name, value in (("collector_endpoint", req.collector_endpoint), ("prometheus_url", req.prometheus_url), ("jaeger_url", req.jaeger_url)):
        if value:
            settings[name] = value
    with db.pool.connection() as conn:
        conn.execute("UPDATE applications SET telemetry_config=%s,updated_at=NOW() WHERE application_id=%s",
                     (Jsonb(settings), DEFAULT_APPLICATION_ID))
        auth.audit(conn, user["username"], "catalog.telemetry_configured", "application", DEFAULT_APPLICATION_ID)
    return {"status": "configured", "message": "Endpoint configuration saved; no collector was reconfigured.",
            "workload": get_workload_status()}


@router.get("/workloads/status")
def get_workload_status() -> dict:
    """Compatibility view backed by persisted registration and observations."""
    app = catalog.application(DEFAULT_APPLICATION_ID)
    registered = catalog.services(DEFAULT_APPLICATION_ID)
    fresh = sum(service["telemetry_state"] == "fresh" for service in registered)
    return {"application_id": DEFAULT_APPLICATION_ID, "workload_name": app["name"], "workload_type": app["runtime_type"],
            "connected": catalog.discovery_state(app) == "connected", "status": catalog.discovery_state(app),
            "connected_at": app["discovery_checked_at"], "services_count": len(registered),
            "services_with_fresh_telemetry": fresh, **app["telemetry_config"]}
