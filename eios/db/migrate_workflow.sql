-- Additive operations control plane. Legacy record identifiers remain untouched.
-- Invalidate tokens previously exposed by the prototype demo recovery endpoint.
UPDATE password_reset_tokens SET used_at=NOW() WHERE used_at IS NULL;
CREATE TABLE IF NOT EXISTS topology_snapshots (
    application_id UUID PRIMARY KEY REFERENCES applications(application_id),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS topology_history (
    snapshot_id BIGSERIAL PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS topology_history_time_idx ON topology_history(application_id,observed_at DESC);
CREATE TABLE IF NOT EXISTS operational_anomalies (
    anomaly_id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    service_id UUID NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('static','statistical','ml','forecast')),
    detector TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    observed_at TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL CHECK(score BETWEEN 0 AND 1),
    title TEXT NOT NULL,
    evidence JSONB NOT NULL,
    baseline JSONB NOT NULL DEFAULT '{}',
    current_values JSONB NOT NULL DEFAULT '{}',
    legacy_incident_id UUID REFERENCES incidents(incident_id),
    legacy_insight_id UUID REFERENCES intelligence_insights(insight_id),
    FOREIGN KEY(application_id,service_id) REFERENCES services(application_id,service_id)
);
CREATE INDEX IF NOT EXISTS operational_anomalies_time_idx ON operational_anomalies(application_id,observed_at DESC);
CREATE TABLE IF NOT EXISTS operational_incidents (
    incident_id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    case_id UUID NOT NULL REFERENCES cases(case_id),
    title TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'DETECTED' CHECK(state IN ('DETECTED','CORRELATING','INVESTIGATING','ROOT_CAUSE_IDENTIFIED','ACTION_RECOMMENDED','AWAITING_APPROVAL','REMEDIATING','VERIFYING','RESOLVED','ESCALATED')),
    severity TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS operational_incidents_app_idx ON operational_incidents(application_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS incident_anomalies (
    incident_id UUID NOT NULL REFERENCES operational_incidents(incident_id),
    anomaly_id UUID NOT NULL UNIQUE REFERENCES operational_anomalies(anomaly_id),
    correlation JSONB NOT NULL,
    PRIMARY KEY(incident_id,anomaly_id)
);
CREATE TABLE IF NOT EXISTS incident_timeline (
    event_id BIGSERIAL PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES operational_incidents(incident_id),
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS rca_rankings (
    ranking_id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES operational_incidents(incident_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    algorithm TEXT NOT NULL,
    state TEXT NOT NULL,
    candidates JSONB NOT NULL,
    explanation TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigation_runs (
    investigation_id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES operational_incidents(incident_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    tool_records JSONB NOT NULL,
    output JSONB NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS remediation_proposals (
    proposal_id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES operational_incidents(incident_id),
    application_id UUID NOT NULL REFERENCES applications(application_id),
    service_id UUID NOT NULL,
    approval_id UUID NOT NULL UNIQUE REFERENCES approvals(approval_id),
    action_type TEXT NOT NULL CHECK(action_type IN ('restart_service','start_service','stop_service','run_health_check','capture_diagnostics')),
    parameters JSONB NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL,
    expected_effect TEXT NOT NULL,
    risk TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    policy JSONB NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW()+INTERVAL '15 minutes',
    FOREIGN KEY(application_id,service_id) REFERENCES services(application_id,service_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS investigation_active_idx ON investigation_runs(incident_id) WHERE state='running';
CREATE TABLE IF NOT EXISTS remediation_executions (
    execution_id UUID PRIMARY KEY,
    proposal_id UUID NOT NULL UNIQUE REFERENCES remediation_proposals(proposal_id),
    approved_by TEXT NOT NULL,
    executed_by TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    state TEXT NOT NULL,
    result JSONB NOT NULL DEFAULT '{}',
    error TEXT,
    before_snapshot JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS recovery_verifications (
    verification_id UUID PRIMARY KEY,
    execution_id UUID NOT NULL UNIQUE REFERENCES remediation_executions(execution_id),
    incident_id UUID NOT NULL REFERENCES operational_incidents(incident_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deadline TIMESTAMPTZ NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'OBSERVING',
    criteria JSONB NOT NULL,
    before_snapshot JSONB NOT NULL,
    samples JSONB NOT NULL DEFAULT '[]',
    completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS experiment_runs (
    experiment_id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    service_id UUID,
    scenario TEXT NOT NULL,
    expected_service_id UUID,
    duration_seconds INTEGER NOT NULL CHECK(duration_seconds BETWEEN 15 AND 3600),
    load_profile JSONB NOT NULL,
    state TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    deadline TIMESTAMPTZ,
    fault_window_id UUID REFERENCES fault_windows(window_id),
    prior_state JSONB NOT NULL DEFAULT '{}',
    artifacts JSONB NOT NULL DEFAULT '{}',
    error TEXT,
    actor TEXT NOT NULL,
    FOREIGN KEY(application_id,service_id) REFERENCES services(application_id,service_id),
    FOREIGN KEY(application_id,expected_service_id) REFERENCES services(application_id,service_id)
);
-- The flagd substrate is shared: conservatively allow one active experiment globally.
CREATE UNIQUE INDEX IF NOT EXISTS experiment_exclusive_idx ON experiment_runs((1))
    WHERE state IN ('PREPARING','RUNNING','CLEANING','CLEANUP_FAILED');
CREATE TABLE IF NOT EXISTS experiment_annotations (
    annotation_id UUID PRIMARY KEY,
    experiment_id UUID NOT NULL REFERENCES experiment_runs(experiment_id),
    anomaly_id UUID REFERENCES operational_anomalies(anomaly_id),
    verdict TEXT NOT NULL CHECK(verdict IN ('true_positive','false_positive','exclude')),
    actor TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS operational_evaluations (
    evaluation_id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    inputs JSONB NOT NULL,
    metrics JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS governance_audit (
    sequence BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail JSONB NOT NULL,
    previous_hash TEXT NOT NULL,
    integrity_hash TEXT NOT NULL UNIQUE
);
CREATE OR REPLACE FUNCTION eios_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Append-only history cannot be modified'; END $$;
CREATE TRIGGER governance_append_only BEFORE UPDATE OR DELETE ON governance_audit
    FOR EACH ROW EXECUTE FUNCTION eios_append_only();
CREATE TRIGGER timeline_append_only BEFORE UPDATE OR DELETE ON incident_timeline
    FOR EACH ROW EXECUTE FUNCTION eios_append_only();
CREATE TRIGGER governance_no_truncate BEFORE TRUNCATE ON governance_audit
    FOR EACH STATEMENT EXECUTE FUNCTION eios_append_only();
CREATE TRIGGER timeline_no_truncate BEFORE TRUNCATE ON incident_timeline
    FOR EACH STATEMENT EXECUTE FUNCTION eios_append_only();
CREATE TRIGGER evaluations_append_only BEFORE UPDATE OR DELETE ON operational_evaluations
    FOR EACH ROW EXECUTE FUNCTION eios_append_only();
CREATE TRIGGER annotations_append_only BEFORE UPDATE OR DELETE ON experiment_annotations
    FOR EACH ROW EXECUTE FUNCTION eios_append_only();
