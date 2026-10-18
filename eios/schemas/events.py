"""Normalized event contract.

Every EIOS signal source — Kafka orders, Prometheus metrics, the attack
generator — is flattened into this one shape before anything downstream sees
it. Detection, correlation and the dashboard all read NormalizedEvent and
never touch a source-specific format.

Bump SCHEMA_VERSION on any breaking field change.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Domain(str, Enum):
    """Which detection domain a signal belongs to."""

    ATTACK = "attack"
    ECOMMERCE = "ecommerce"
    INFRASTRUCTURE = "infrastructure"


class EntityKind(str, Enum):
    """What kind of thing an event is about.

    This is the join key for correlation: two events about the same entity are
    candidates for the same incident.
    """

    SERVICE = "service"
    CONTAINER = "container"
    SESSION = "session"
    ORDER = "order"
    ENDPOINT = "endpoint"


class Entity(BaseModel):
    kind: EntityKind
    id: str
    service: str | None = None

    def key(self) -> str:
        return f"{self.kind.value}:{self.id}"


class NormalizedEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    schema_version: str = SCHEMA_VERSION

    domain: Domain
    source: str
    """Where this came from, e.g. 'kafka:orders' or 'prometheus'."""

    observed_at: datetime
    """When the signal actually happened, not when we read it."""
    ingested_at: datetime = Field(default_factory=_now)

    entity: Entity

    metrics: dict[str, float] = Field(default_factory=dict)
    """Numeric features. Detection reads only this."""
    attributes: dict[str, str] = Field(default_factory=dict)
    """Categorical context. Investigation and correlation read this."""

    trace_id: str | None = None
    """Links back to the substrate's own trace in Jaeger, when known."""
    raw_ref: str | None = None

    # Additive wire fields: 1.0 consumers can still read the original shape.
    application_id: uuid.UUID | None = None
    service_id: uuid.UUID | None = None
    service_name: str | None = None
    environment: str | None = None
    source_id: uuid.UUID | None = None
    signal_type: str | None = None
    source_observed_at: datetime | None = None
