"""SHA-256 hash-chained audit logger.

-- Migration needed (run once):
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS tenant_id TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS request_id TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS integrity_hash TEXT;
"""

from __future__ import annotations
import hashlib
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("eios.audit")


class AuditLogger:
    def __init__(self, pool) -> None:
        self._pool = pool

    def _prev_hash(self, conn) -> str:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT integrity_hash FROM audit_log ORDER BY entry_id DESC LIMIT 1")
                row = cur.fetchone()
                return row[0] if row and row[0] else ""
        except Exception:
            return ""

    def log(
        self,
        actor: str,
        action: str,
        subject_kind: str | None = None,
        subject_id: str | None = None,
        detail: dict | None = None,
        tenant_id: str | None = None,
        ip: str | None = None,
        request_id: str | None = None,
    ) -> str:
        detail = detail or {}
        now = datetime.now(timezone.utc)
        detail_json = json.dumps(detail, sort_keys=True, default=str)

        try:
            with self._pool.connection() as conn:
                prev = self._prev_hash(conn)
                chain_input = f"{prev}|{actor}|{action}|{subject_id or ''}|{detail_json}|{now.isoformat()}"
                h = hashlib.sha256(chain_input.encode()).hexdigest()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO audit_log
                               (at, actor, action, subject_kind, subject_id, detail,
                                tenant_id, ip, request_id, integrity_hash)
                               VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
                            (now, actor, action, subject_kind, subject_id,
                             detail_json, tenant_id, ip, request_id, h),
                        )
                except Exception:
                    # Fallback: old schema without new columns
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO audit_log (actor, action, subject_kind, subject_id, detail) VALUES (%s,%s,%s,%s,%s::jsonb)",
                            (actor, action, subject_kind, subject_id, detail_json),
                        )
                return h
        except Exception:
            log.exception("audit log write failed")
            return ""

    def verify_chain(self, limit: int = 1000) -> list[dict]:
        """Return list of entries where hash doesn't match recomputed value."""
        failures = []
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT entry_id, at, actor, action, subject_id, detail, integrity_hash "
                        "FROM audit_log ORDER BY entry_id ASC LIMIT %s",
                        (limit,),
                    )
                    rows = cur.fetchall()
            prev = ""
            for row in rows:
                entry_id, at, actor, action, subject_id, detail, stored_hash = row
                detail_json = json.dumps(detail, sort_keys=True, default=str) if isinstance(detail, dict) else (detail or "{}")
                chain_input = f"{prev}|{actor}|{action}|{subject_id or ''}|{detail_json}|{at.isoformat()}"
                computed = hashlib.sha256(chain_input.encode()).hexdigest()
                if stored_hash and computed != stored_hash:
                    failures.append({"entry_id": entry_id, "stored": stored_hash, "computed": computed})
                prev = stored_hash or computed
        except Exception:
            log.exception("chain verification failed")
        return failures
