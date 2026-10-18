-- Additive and repeatable; existing events, incidents, and database volume survive.
CREATE TABLE IF NOT EXISTS feature_windows (
    service TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    feature_version TEXT NOT NULL,
    features JSONB NOT NULL,
    quality JSONB NOT NULL,
    evidence_event_ids UUID[] NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (service, window_start, feature_version)
);
CREATE INDEX IF NOT EXISTS feature_windows_end_idx ON feature_windows(window_end DESC);
CREATE TABLE IF NOT EXISTS model_registry (
    model_id UUID PRIMARY KEY,
    service TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    feature_names JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('candidate', 'active', 'retired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    train_start TIMESTAMPTZ NOT NULL,
    train_end TIMESTAMPTZ NOT NULL,
    validation JSONB NOT NULL,
    dependencies JSONB NOT NULL,
    baseline JSONB NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    artifact_name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    last_inference_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS model_registry_active_idx ON model_registry(service, algorithm)
    WHERE state = 'active';
CREATE TABLE IF NOT EXISTS intelligence_insights (
    insight_id UUID PRIMARY KEY,
    incident_id UUID REFERENCES incidents(incident_id),
    service TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    detector TEXT NOT NULL,
    model_id UUID REFERENCES model_registry(model_id),
    feature_version TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    measurements JSONB NOT NULL,
    baseline JSONB NOT NULL DEFAULT '{}',
    analysis JSONB NOT NULL DEFAULT '{}',
    evidence_event_ids UUID[] NOT NULL DEFAULT '{}',
    recommendation JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    UNIQUE(service, window_end, detector)
);
CREATE INDEX IF NOT EXISTS intelligence_insights_created_idx ON intelligence_insights(created_at DESC);
CREATE INDEX IF NOT EXISTS intelligence_insights_incident_idx ON intelligence_insights(incident_id);
CREATE TABLE IF NOT EXISTS intelligence_forecasts (
    forecast_id UUID PRIMARY KEY,
    service TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    horizon_minutes INTEGER NOT NULL,
    state TEXT NOT NULL,
    reason TEXT,
    algorithm TEXT NOT NULL,
    values JSONB NOT NULL DEFAULT '{}',
    evidence_event_ids UUID[] NOT NULL DEFAULT '{}',
    UNIQUE(service, observed_at, horizon_minutes, algorithm)
);
CREATE INDEX IF NOT EXISTS intelligence_forecasts_time_idx ON intelligence_forecasts(observed_at DESC);
ALTER TABLE intelligence_forecasts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE TABLE IF NOT EXISTS intelligence_feedback (
    feedback_id UUID PRIMARY KEY,
    insight_id UUID NOT NULL REFERENCES intelligence_insights(insight_id),
    verdict TEXT NOT NULL CHECK(verdict IN ('confirm','dismiss','useful','not_useful')),
    operator TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
    evaluation_id UUID PRIMARY KEY,
    model_id UUID REFERENCES model_registry(model_id),
    service TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    test_start TIMESTAMPTZ NOT NULL,
    test_end TIMESTAMPTZ NOT NULL,
    metrics JSONB NOT NULL,
    notes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intelligence_outbox (
    message_id UUID PRIMARY KEY,
    topic TEXT NOT NULL,
    message_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS intelligence_outbox_pending_idx ON intelligence_outbox(created_at)
    WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS intelligence_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS intelligence_rejections (
    topic TEXT NOT NULL,
    partition_id INTEGER NOT NULL,
    offset_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(topic, partition_id, offset_id)
);
CREATE INDEX IF NOT EXISTS events_service_time_idx ON events(entity_service, observed_at DESC);
CREATE INDEX IF NOT EXISTS cases_service_open_idx ON cases((enrichment->>'service'), opened_at DESC)
    WHERE closed_at IS NULL;
