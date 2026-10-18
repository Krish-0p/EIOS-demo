"""Incident contract.

What a detector emits and every downstream agent consumes. Detection writes
it; investigation, correlation, threat-intel and the dashboard read it.

The `labels` field is what makes the Stage 3 evaluation harness possible: when
a fault is injected via flagd the window is recorded as ground truth, so a
detected incident can be scored as true or false positive without anyone
labelling by hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .events import Domain, Entity

SCHEMA_VERSION = "1.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    CORRELATED = "correlated"
    AWAITING_APPROVAL = "awaiting_approval"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Incident(BaseModel):
    incident_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    schema_version: str = SCHEMA_VERSION

    domain: Domain
    entity: Entity

    detected_at: datetime = Field(default_factory=_now)
    window_start: datetime
    window_end: datetime

    detector: str
    """Which detector fired, e.g. 'rule:payment_failure_rate' or
    'ml:iforest_v1'. Kept so rule and model results stay comparable on the
    same windows."""

    score: float = Field(ge=0.0, le=1.0)
    severity: Severity
    title: str

    features: dict[str, float] = Field(default_factory=dict)
    """The feature vector that triggered this. Needed to explain the call."""

    evidence_event_ids: list[uuid.UUID] = Field(default_factory=list)

    labels: dict[str, str] = Field(default_factory=dict)
    """Ground truth when known, e.g. {'injected_fault': 'paymentFailure'}."""

    status: IncidentStatus = IncidentStatus.OPEN
    case_id: uuid.UUID | None = None
    """Set by the correlation agent once grouped into a case."""
