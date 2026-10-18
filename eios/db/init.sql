-- EIOS store. Applied once on first start of the eios-postgres container.

CREATE TABLE IF NOT EXISTS events (
    event_id        UUID PRIMARY KEY,
    schema_version  TEXT        NOT NULL,
    domain          TEXT        NOT NULL,
    source          TEXT        NOT NULL,
    observed_at     TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL,
    entity_kind     TEXT        NOT NULL,
    entity_id       TEXT        NOT NULL,
    entity_service  TEXT,
    metrics         JSONB       NOT NULL DEFAULT '{}',
    attributes      JSONB       NOT NULL DEFAULT '{}',
    trace_id        TEXT,
    raw_ref         TEXT
);

CREATE INDEX IF NOT EXISTS events_observed_at_idx ON events (observed_at DESC);
CREATE INDEX IF NOT EXISTS events_domain_observed_idx ON events (domain, observed_at DESC);
CREATE INDEX IF NOT EXISTS events_entity_idx ON events (entity_kind, entity_id, observed_at DESC);

-- Ground truth for the Stage 3 evaluation harness. One row per injected fault.
-- Any incident detected between started_at and ended_at for a matching entity
-- is a true positive; anything outside every window is a false positive.
CREATE TABLE IF NOT EXISTS fault_windows (
    window_id       UUID PRIMARY KEY,
    flag_key        TEXT        NOT NULL,
    variant         TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    expected_domain TEXT,
    expected_entity TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS fault_windows_started_idx ON fault_windows (started_at DESC);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id     UUID PRIMARY KEY,
    schema_version  TEXT        NOT NULL,
    domain          TEXT        NOT NULL,
    entity_kind     TEXT        NOT NULL,
    entity_id       TEXT        NOT NULL,
    entity_service  TEXT,
    detected_at     TIMESTAMPTZ NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    detector        TEXT        NOT NULL,
    score           DOUBLE PRECISION NOT NULL,
    severity        TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    features        JSONB       NOT NULL DEFAULT '{}',
    evidence_event_ids UUID[]   NOT NULL DEFAULT '{}',
    labels          JSONB       NOT NULL DEFAULT '{}',
    status          TEXT        NOT NULL DEFAULT 'open',
    case_id         UUID
);

CREATE INDEX IF NOT EXISTS incidents_detected_at_idx ON incidents (detected_at DESC);
CREATE INDEX IF NOT EXISTS incidents_detector_idx ON incidents (detector, detected_at DESC);
CREATE INDEX IF NOT EXISTS incidents_case_idx ON incidents (case_id);

-- Stages 4 and 5. Created now so the schema is agreed once, not renegotiated.
CREATE TABLE IF NOT EXISTS cases (
    case_id         UUID PRIMARY KEY,
    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    severity        TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    summary         TEXT,
    timeline        JSONB       NOT NULL DEFAULT '[]',
    enrichment      JSONB       NOT NULL DEFAULT '{}',
    status          TEXT        NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id     UUID PRIMARY KEY,
    case_id         UUID        NOT NULL REFERENCES cases (case_id),
    action          TEXT        NOT NULL,
    rationale       TEXT        NOT NULL,
    destructive     BOOLEAN     NOT NULL DEFAULT TRUE,
    requested_at    TIMESTAMPTZ NOT NULL,
    decided_at      TIMESTAMPTZ,
    decision        TEXT,
    decided_by      TEXT,
    modification    JSONB
);

CREATE INDEX IF NOT EXISTS approvals_pending_idx ON approvals (requested_at DESC)
    WHERE decided_at IS NULL;

-- Append only. Never updated, never deleted.
CREATE TABLE IF NOT EXISTS audit_log (
    entry_id        BIGSERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor           TEXT        NOT NULL,
    action          TEXT        NOT NULL,
    subject_kind    TEXT,
    subject_id      TEXT,
    detail          JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS audit_log_at_idx ON audit_log (at DESC);
