CREATE TABLE telemetry_sources (
    source_id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    kind TEXT NOT NULL CHECK(kind IN ('kafka','prometheus','jaeger','opensearch')),
    endpoint TEXT NOT NULL,
    scope JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    checked_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_data_at TIMESTAMPTZ,
    last_error TEXT,
    freshness_seconds INTEGER NOT NULL DEFAULT 240 CHECK(freshness_seconds BETWEEN 30 AND 86400),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(application_id,kind),
    UNIQUE(application_id,source_id)
);
ALTER TABLE events ADD COLUMN environment TEXT;
ALTER TABLE events ADD COLUMN service_name TEXT;
ALTER TABLE events ADD COLUMN source_id UUID;
ALTER TABLE events ADD COLUMN signal_type TEXT;
ALTER TABLE events ADD COLUMN source_observed_at TIMESTAMPTZ;
ALTER TABLE events ADD CONSTRAINT events_source_identity_fk FOREIGN KEY(application_id,source_id)
    REFERENCES telemetry_sources(application_id,source_id);
CREATE INDEX events_signal_time_idx ON events(application_id,signal_type,observed_at DESC);

-- Bounded evidence snapshots, not a second full trace/log warehouse.
CREATE TABLE telemetry_evidence (
    evidence_id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    service_id UUID NOT NULL,
    service_name TEXT NOT NULL,
    environment TEXT NOT NULL,
    source_id UUID NOT NULL,
    signal_type TEXT NOT NULL CHECK(signal_type IN ('trace','log')),
    observed_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trace_id TEXT,
    raw_ref TEXT NOT NULL,
    evidence JSONB NOT NULL,
    FOREIGN KEY(application_id,service_id) REFERENCES services(application_id,service_id),
    FOREIGN KEY(application_id,source_id) REFERENCES telemetry_sources(application_id,source_id),
    UNIQUE(source_id,raw_ref)
);
CREATE INDEX telemetry_evidence_lookup_idx ON telemetry_evidence(application_id,service_id,signal_type,observed_at DESC);

-- Preserve the Phase 1 trigger for incidents and intelligence. Telemetry gets
-- stricter validation and explicit metadata without changing existing IDs.
CREATE FUNCTION eios_telemetry_metadata() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE app_environment TEXT; bound_application UUID; bound_name TEXT;
BEGIN
    SELECT environment INTO app_environment FROM applications WHERE application_id=NEW.application_id;
    IF NEW.environment IS NOT NULL AND NEW.environment<>app_environment THEN
        RAISE EXCEPTION 'Telemetry environment does not match application';
    END IF;
    NEW.environment := app_environment;
    NEW.service_name := COALESCE(NEW.service_name,NEW.entity_service,
        CASE WHEN NEW.entity_kind IN ('service','container') THEN NEW.entity_id END);
    IF NEW.service_id IS NOT NULL THEN
        SELECT application_id,name INTO bound_application,bound_name FROM services WHERE service_id=NEW.service_id;
        IF bound_application IS DISTINCT FROM NEW.application_id OR
           (NEW.service_name IS NOT NULL AND NEW.service_name<>bound_name AND NOT EXISTS(
               SELECT 1 FROM services WHERE service_id=NEW.service_id AND runtime_identifier=NEW.service_name)) THEN
            RAISE EXCEPTION 'Telemetry service does not match application/name';
        END IF;
        NEW.service_name := bound_name;
    END IF;
    NEW.signal_type := COALESCE(NEW.signal_type,CASE WHEN NEW.source LIKE 'prometheus%' THEN 'metric'
        WHEN NEW.source LIKE 'kafka:%:health' THEN 'source_health'
        WHEN NEW.source LIKE 'kafka:%' THEN 'business_event' ELSE 'unknown' END);
    IF NEW.source_id IS NULL THEN
        SELECT source_id INTO NEW.source_id FROM telemetry_sources WHERE application_id=NEW.application_id
            AND kind=CASE WHEN NEW.source LIKE 'prometheus%' THEN 'prometheus'
                WHEN NEW.source LIKE 'kafka:%' THEN 'kafka' ELSE NULL END;
    END IF;
    NEW.source_observed_at := COALESCE(NEW.source_observed_at,
        NULLIF(NEW.attributes->>'source_observed_at','')::timestamptz, NEW.observed_at);
    RETURN NEW;
END $$;
CREATE TRIGGER phase2_metadata BEFORE INSERT OR UPDATE ON events FOR EACH ROW EXECUTE FUNCTION eios_telemetry_metadata();
