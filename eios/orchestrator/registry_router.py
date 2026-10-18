"""Application-scoped persistent catalog APIs, separate from legacy health APIs."""
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

import auth
import catalog
import db
from phase1_migrate import service_id

router = APIRouter(prefix="/api/applications", tags=["applications"])


class DiscoveryScope(BaseModel):
    compose_project: str | None = Field(default=None, max_length=128)
    labels: dict[str, str] = Field(default_factory=dict)
    container_names: list[str] = Field(default_factory=list, max_length=100)
    exclude_services: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def bounded(self):
        if self.compose_project:
            self.compose_project = self.compose_project.strip()
        if not (self.compose_project or self.labels or self.container_names):
            raise ValueError("Choose a Compose project, labels, or explicit container names")
        if any(not name.strip() for name in self.container_names) or any(not key.strip() or not value.strip() for key, value in self.labels.items()):
            raise ValueError("Discovery selectors must not be empty")
        return self


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="development", min_length=1, max_length=64)
    runtime_type: Literal["docker"] = "docker"
    discovery_scope: DiscoveryScope
    telemetry_config: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)


class ApplicationUpdate(BaseModel):
    discovery_scope: DiscoveryScope
    telemetry_config: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    runtime_identifier: str | None = Field(default=None, max_length=128)
    language: str | None = Field(default=None, max_length=64)
    labels: dict[str, str] = Field(default_factory=dict)


@router.get("")
def list_applications():
    return [catalog.application_view(row) for row in db._rows("SELECT * FROM applications ORDER BY created_at")]


@router.post("", status_code=201)
def create_application(body: ApplicationCreate, request: Request):
    user = auth.require_role(request, "administrator")
    name, environment = body.name.strip(), body.environment.strip()
    if not name or not environment:
        raise HTTPException(400, "Application name and environment are required")
    application_id = uuid4()
    try:
        with db.pool.connection() as conn:
            conn.execute("""INSERT INTO applications(application_id,name,environment,runtime_type,telemetry_config,discovery_scope,labels)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""", (application_id, name, environment, body.runtime_type,
                    Jsonb(body.telemetry_config), Jsonb(body.discovery_scope.model_dump()), Jsonb(body.labels)))
            auth.audit(conn, user["username"], "catalog.application_created", "application", application_id)
    except UniqueViolation:
        raise HTTPException(409, "Application already exists in that environment")
    return catalog.application_view(catalog.application(application_id))


@router.get("/{application_id}")
def get_application(application_id: UUID):
    return catalog.application_view(catalog.application(application_id))


@router.patch("/{application_id}")
def update_application(application_id: UUID, body: ApplicationUpdate, request: Request):
    user = auth.require_role(request, "administrator")
    catalog.application(application_id)
    with db.pool.connection() as conn:
        conn.execute("""UPDATE applications SET discovery_scope=%s,telemetry_config=%s,labels=%s,
            discovery_checked_at=NULL,discovery_error=NULL,updated_at=NOW() WHERE application_id=%s""",
            (Jsonb(body.discovery_scope.model_dump()), Jsonb(body.telemetry_config), Jsonb(body.labels), application_id))
        auth.audit(conn, user["username"], "catalog.application_updated", "application", application_id)
    return catalog.application_view(catalog.application(application_id))


@router.get("/{application_id}/services")
def list_services(application_id: UUID):
    return catalog.services(application_id)


@router.post("/{application_id}/services", status_code=201)
def register_service(application_id: UUID, body: ServiceCreate, request: Request):
    user = auth.require_role(request, "administrator", "operator")
    catalog.application(application_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Service name is required")
    stable = service_id(application_id, name)
    with db.pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"discovery:{application_id}",))
        aliases = [name, body.runtime_identifier or name]
        conflict = conn.execute("""SELECT name FROM services WHERE application_id=%s AND name<>%s
            AND (name=ANY(%s) OR runtime_identifier=ANY(%s))""", (application_id, name, aliases, aliases)).fetchone()
        if conflict:
            raise HTTPException(409, "This runtime identity already belongs to another registered service")
        conn.execute("""INSERT INTO services(service_id,application_id,name,runtime_identifier,language,labels)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(application_id,name) DO NOTHING""",
            (stable, application_id, name, body.runtime_identifier, body.language, Jsonb(body.labels)))
        auth.audit(conn, user["username"], "catalog.service_registered", "service", stable)
    return next(row for row in catalog.services(application_id) if row["name"] == name)


@router.post("/{application_id}/discovery")
def discover(application_id: UUID, request: Request):
    user = auth.require_role(request, "administrator", "operator")
    return catalog.reconcile(application_id, actor=user["username"])


@router.get("/{application_id}/services/{service_id}/history")
def history(application_id: UUID, service_id: UUID):
    catalog.application(application_id)
    found = db._rows("SELECT 1 FROM services WHERE application_id=%(app)s AND service_id=%(svc)s",
                     {"app": application_id, "svc": service_id})
    if not found:
        raise HTTPException(404, "Service not found in this application")
    return {"service_id": service_id, "application_id": application_id,
            "events": db._rows("SELECT event_id,observed_at,source,metrics,attributes FROM events WHERE service_id=%(id)s ORDER BY observed_at DESC LIMIT 50", {"id": service_id}),
            "incidents": db._rows("SELECT * FROM incidents WHERE service_id=%(id)s ORDER BY detected_at DESC LIMIT 50", {"id": service_id})}
