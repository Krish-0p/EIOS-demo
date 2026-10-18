"""eios-orchestrator: the API and live feed the dashboard reads.

Stage 2 scope. It serves incidents, events and stats, records fault windows,
and pushes new incidents to connected clients over a WebSocket.

Coordinating the investigation, correlation and threat-intel agents is Stage 4;
this is the process those agents will live in.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from typing import Any
from uuid import UUID

from confluent_kafka import Consumer, KafkaError
import os
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import db
import flags
from middleware import SecurityMiddleware, RequestSizeLimitMiddleware
from security_router import router as security_router
from docker_router import router as docker_router
from system_router import router as system_router
from terminal_router import router as terminal_router
from fs_router import router as fs_router
from services_router import router as services_router
from agents_router import router as agents_router
from auth_router import router as auth_router
from intelligence_router import router as intelligence_router
from intelligence.migrate import migrate
from phase1_migrate import migrate as migrate_phase1
from auth_recovery_migrate import migrate as migrate_auth_recovery
from registry_router import router as registry_router
import auth
import catalog
from telemetry.migrate import migrate as migrate_phase2
from telemetry_router import router as telemetry_router, source_loop
from workflow_migrate import migrate as migrate_workflow
from workflow_router import router as workflow_router, governance as governance_router
from workflow_worker import run as workflow_loop

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
log = logging.getLogger("eios.orchestrator")


class Hub:
    """Fans incidents out to every connected dashboard.

    The Kafka consumer runs in a plain thread, so it hands messages to the
    event loop with call_soon_threadsafe rather than touching sockets itself.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        log.info("dashboard connected, %d total", len(self._clients))

    async def leave(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._clients)
        dead = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    def publish_threadsafe(self, payload: dict[str, Any]) -> None:
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), self.loop)


hub = Hub()
_stop = threading.Event()


def consume_incidents() -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": config.KAFKA_ADDR,
            "group.id": config.CONSUMER_GROUP,
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )
    intelligence_topic = os.getenv("EIOS_INTELLIGENCE_TOPIC", "eios.intelligence")
    consumer.subscribe([config.INCIDENTS_TOPIC, intelligence_topic])
    log.info("consuming %s", config.INCIDENTS_TOPIC)
    try:
        while not _stop.is_set():
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.error("kafka error: %s", msg.error())
                continue
            try:
                incident = json.loads(msg.value())
            except Exception:
                log.exception("bad incident payload")
                continue
            kind = "incident" if msg.topic() == config.INCIDENTS_TOPIC else "intelligence"
            hub.publish_threadsafe({"type": kind, "data": incident})
    finally:
        consumer.close()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.pool.open()
    with db.pool.connection() as conn:
        migrate(conn)
        migrate_phase1(conn)
        migrate_auth_recovery(conn)
        migrate_phase2(conn)
        migrate_workflow(conn)
    _stop.clear()
    hub.loop = asyncio.get_running_loop()
    worker = threading.Thread(target=consume_incidents, name="incidents", daemon=True)
    worker.start()
    catalog_worker = threading.Thread(target=catalog.discovery_loop, args=(_stop,), name="catalog-discovery", daemon=True)
    catalog_worker.start()
    telemetry_worker = threading.Thread(target=source_loop,args=(_stop,),name='telemetry-sources',daemon=True)
    telemetry_worker.start()
    workflow_worker = threading.Thread(target=workflow_loop,args=(_stop,hub.publish_threadsafe),name='operations-workflow',daemon=True)
    workflow_worker.start()
    log.info("orchestrator ready")
    yield
    _stop.set()
    worker.join(timeout=5)
    catalog_worker.join(timeout=15)
    telemetry_worker.join(timeout=20)
    workflow_worker.join(timeout=20)
    db.pool.close()


app = FastAPI(title="EIOS Orchestrator", version="0.2.0", lifespan=lifespan)

app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SecurityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("EIOS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(security_router)
app.include_router(docker_router)
app.include_router(system_router)
app.include_router(terminal_router)
app.include_router(fs_router)
app.include_router(services_router)
app.include_router(agents_router)
app.include_router(auth_router)
app.include_router(intelligence_router)
app.include_router(registry_router)
app.include_router(telemetry_router)
app.include_router(workflow_router)
app.include_router(governance_router)


class StartFault(BaseModel):
    flag_key: str
    variant: str = "on"
    expected_domain: str | None = None
    expected_entity: str | None = None
    notes: str | None = None
    apply: bool = True
    """Flip the flag in flagd as well as recording the window."""


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats")
def get_stats() -> dict:
    return db.stats()


@app.get("/api/incidents")
def get_incidents(
    limit: int = Query(50, ge=1, le=500),
    domain: str | None = None,
    application_id: UUID | None = None,
) -> list[dict]:
    return db.incidents(limit=limit, domain=domain, application_id=application_id)


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict:
    found = db.incident(incident_id)
    if not found:
        raise HTTPException(status_code=404, detail="No incident with that id")
    found["evidence"] = db.evidence_events(incident_id)
    return found


@app.get("/api/events")
def get_events(
    limit: int = Query(100, ge=1, le=1000),
    domain: str | None = None,
    application_id: UUID | None = None,
) -> list[dict]:
    return db.events(limit=limit, domain=domain, application_id=application_id)


@app.get("/api/faults")
def get_faults() -> list[dict]:
    return db.fault_windows()


@app.post("/api/faults/start")
def post_fault_start(body: StartFault, request: Request) -> dict:
    """Record that a fault is being injected.

    This writes the ground-truth window only. Toggle the flag itself in the
    flagd UI - an unrecorded fault cannot be scored later.
    """
    user=auth.require_role(request,'administrator')
    from workflow_fault_control import start_legacy
    return start_legacy(body,user['username'])


def _deprecated_fault_start(body, user):
    """Former adapter retained as internal reference; HTTP path uses durable control."""
    from workflow_store import rows as workflow_rows, audit as workflow_audit
    if workflow_rows("SELECT 1 FROM experiment_runs WHERE state IN ('PREPARING','RUNNING','CLEANING','CLEANUP_FAILED') LIMIT 1"):
        raise HTTPException(409,'An experiment owns fault control; stop/clean it in Experiment Lab first')
    applied = None
    if body.apply:
        if not flags.available():
            raise HTTPException(
                status_code=503,
                detail="flagd config is not mounted; toggle in the flagd UI instead",
            )
        try:
            applied = flags.set_variant(body.flag_key, body.variant)
        except flags.FlagError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Fall back to the known expectation for this flag, so a window recorded
    # from the dashboard is still scoped enough to attribute incidents.
    default_domain, default_entity = flags.expectation(body.flag_key)
    try:
        row = db.start_fault(body.flag_key,body.variant,body.expected_domain or default_domain,
            body.expected_entity or default_entity,body.notes)
        with db.pool.connection() as conn:
            workflow_audit(conn,user['username'],'fault.started',{'window_id':row['window_id'],'flag':body.flag_key,'applied':applied})
    except Exception:
        if applied and applied.get('previous'):
            flags.set_variant(body.flag_key,applied['previous'])
        raise
    return {**row, "applied": applied, "toggle_at": config.FLAGD_UI_URL}


@app.post("/api/faults/{window_id}/stop")
def post_fault_stop(window_id: str, request: Request) -> dict:
    user=auth.require_role(request,'administrator')
    from workflow_store import rows as workflow_rows, audit as workflow_audit
    runs=workflow_rows('SELECT experiment_id FROM experiment_runs WHERE fault_window_id=%s',(window_id,))
    if runs:
        from workflow_experiments import cleanup
        return cleanup(runs[0]['experiment_id'],user['username'])
    found=workflow_rows('SELECT * FROM fault_windows WHERE window_id=%s AND ended_at IS NULL',(window_id,))
    if not found:
        raise HTTPException(status_code=404, detail="No open fault window with that id")
    row=found[0]
    cleared = None
    if flags.available():
        try:
            cleared = flags.turn_off(row["flag_key"])
        except (flags.FlagError,OSError):
            raise HTTPException(502,'Fault restore failed; ground-truth window remains open')
    elif row['variant']:
        raise HTTPException(503,'Cannot confirm fault cleared while flagd configuration is unavailable')
    row=db.stop_fault(window_id)
    with db.pool.connection() as conn:
        workflow_audit(conn,user['username'],'fault.stopped',{'window_id':window_id,'cleared':cleared})
    return {**row, "cleared": cleared}


@app.get("/api/flags")
def get_flags() -> list[dict]:
    if not flags.available():
        raise HTTPException(status_code=503, detail="flagd config is not mounted")
    return flags.list_flags()


@app.get("/api/scoreboard")
def get_scoreboard() -> list[dict]:
    return db.scoreboard()


@app.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    if not await auth.authorize_websocket(ws):
        return
    await hub.join(ws)
    try:
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                pass
            if not await asyncio.to_thread(auth.current_user, ws.cookies.get(auth.COOKIE_NAME)):
                await ws.close(code=1008)
                break
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave(ws)
