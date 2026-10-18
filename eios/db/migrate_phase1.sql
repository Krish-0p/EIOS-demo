-- Additive control-plane schema. Existing primary keys and data are retained.
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('administrator', 'operator', 'viewer')),
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS user_sessions_user_idx ON user_sessions(user_id);

CREATE TABLE IF NOT EXISTS applications (
    application_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    environment TEXT NOT NULL,
    runtime_type TEXT NOT NULL CHECK (runtime_type = 'docker'),
    telemetry_config JSONB NOT NULL DEFAULT '{}',
    discovery_scope JSONB NOT NULL,
    labels JSONB NOT NULL DEFAULT '{}',
    discovery_checked_at TIMESTAMPTZ,
    discovery_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(name, environment)
);
CREATE TABLE IF NOT EXISTS services (
    service_id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(application_id),
    name TEXT NOT NULL,
    runtime_identifier TEXT,
    language TEXT,
    version TEXT,
    labels JSONB NOT NULL DEFAULT '{}',
    dependencies JSONB NOT NULL DEFAULT '[]',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ,
    UNIQUE(application_id, name),
    UNIQUE(application_id, service_id)
);
CREATE TABLE IF NOT EXISTS service_runtime_instances (
    container_id TEXT PRIMARY KEY,
    service_id UUID NOT NULL REFERENCES services(service_id),
    container_name TEXT NOT NULL,
    image TEXT,
    ports TEXT,
    runtime_state TEXT NOT NULL,
    health_state TEXT NOT NULL DEFAULT 'unknown',
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS services_runtime_identity_idx ON services(application_id,runtime_identifier)
    WHERE runtime_identifier IS NOT NULL;
CREATE INDEX IF NOT EXISTS runtime_instances_service_idx ON service_runtime_instances(service_id);

-- These fields are deliberately additive. Legacy producers keep their existing
-- contracts; the database associates their single-application source explicitly.
CREATE OR REPLACE FUNCTION eios_assign_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    data JSONB := to_jsonb(NEW);
    service_name TEXT;
    explicit_application TEXT;
BEGIN
    explicit_application := COALESCE(data->'attributes'->>'application_id', data->'labels'->>'application_id');
    IF NEW.application_id IS NULL AND explicit_application IS NOT NULL THEN
        -- Invalid explicit identities fail rather than silently mixing applications.
        NEW.application_id := explicit_application::uuid;
    END IF;
    NEW.application_id := COALESCE(NEW.application_id, '6b42866e-e214-57e4-a7bd-e0ce18ade732'::uuid);
    service_name := COALESCE(NULLIF(data->>'entity_service', ''), data->>'service',
        data->'enrichment'->>'service',
        CASE WHEN data->>'entity_kind' IN ('service', 'container') THEN data->>'entity_id' END);
    IF NEW.service_id IS NULL THEN
        SELECT service_id INTO NEW.service_id FROM services
        WHERE application_id = NEW.application_id AND (name = service_name OR runtime_identifier = service_name)
        ORDER BY (name = service_name) DESC LIMIT 1;
    END IF;
    RETURN NEW;
END $$;

DO $$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['events','incidents','cases','feature_windows','model_registry',
        'intelligence_insights','intelligence_forecasts','evaluation_runs'] LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS application_id UUID REFERENCES applications(application_id)', target);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS service_id UUID', target);
        EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (application_id,service_id) REFERENCES services(application_id,service_id)', target, target || '_catalog_service_fk');
        EXECUTE format('CREATE TRIGGER phase1_identity BEFORE INSERT OR UPDATE OF application_id,service_id ON %I FOR EACH ROW EXECUTE FUNCTION eios_assign_identity()', target);
    END LOOP;
END $$;
CREATE INDEX IF NOT EXISTS events_catalog_time_idx ON events(service_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS events_application_time_idx ON events(application_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS incidents_application_time_idx ON incidents(application_id, detected_at DESC);
