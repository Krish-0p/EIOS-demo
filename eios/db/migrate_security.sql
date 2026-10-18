-- EIOS audit_log security column additions (idempotent, run on existing DBs)
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS tenant_id      TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip             TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS request_id     TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS integrity_hash TEXT;

CREATE INDEX IF NOT EXISTS audit_log_tenant_idx  ON audit_log (tenant_id, at DESC);
CREATE INDEX IF NOT EXISTS audit_log_action_idx  ON audit_log (action, at DESC);
CREATE INDEX IF NOT EXISTS incidents_severity_idx ON incidents (severity, detected_at DESC);
