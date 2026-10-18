"""Additive intelligence contracts. Scores describe unusualness, not risk probabilities."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class Recommendation(BaseModel):
    catalog_version: str = "1.0"
    action: str
    target: str
    title: str
    rationale: str
    preconditions: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    execution: Literal["manual"] = "manual"


class IntelligenceInsight(BaseModel):
    insight_id: UUID
    incident_id: UUID | None = None
    service: str
    kind: Literal["anomaly", "kpi", "forecast", "rule_evidence"]
    created_at: datetime
    window_start: datetime
    window_end: datetime
    detector: str
    model_id: UUID | None = None
    feature_version: str = "2.0"
    severity: str
    title: str
    measurements: dict[str, float]
    baseline: dict = Field(default_factory=dict)
    analysis: dict = Field(default_factory=dict)
    evidence_event_ids: list[UUID] = Field(default_factory=list)
    recommendation: Recommendation
    status: str = "open"


class Forecast(BaseModel):
    forecast_id: UUID
    service: str
    observed_at: datetime
    created_at: datetime
    horizon_minutes: int
    state: Literal["ready", "abstained"]
    data_fresh: bool = True
    reason: str | None = None
    algorithm: str = "memory-linear-v1"
    values: dict = Field(default_factory=dict)
    evidence_event_ids: list[UUID] = Field(default_factory=list)


class ModelVersion(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: UUID
    service: str
    algorithm: str
    feature_version: str
    feature_names: list[str]
    state: Literal["candidate", "active", "retired"]
    created_at: datetime
    train_start: datetime
    train_end: datetime
    validation: dict
    dependencies: dict
    checksum: str
    last_inference_at: datetime | None = None


class IntelligenceFeedback(BaseModel):
    insight_id: UUID
    verdict: Literal["confirm", "dismiss", "useful", "not_useful"]
    operator: str = Field(default="operator", min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
