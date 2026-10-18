"""Audit chain integrity verifier."""
import hashlib, json, os, sys
import psycopg
from psycopg.rows import tuple_row

def main():
    dsn = os.environ.get("EIOS_POSTGRES_DSN", "postgresql://eios:eios@eios-postgres:5432/eios")
    failures = 0
    with psycopg.connect(dsn, row_factory=tuple_row) as conn:
        rows = conn.execute(
            "SELECT entry_id, at, actor, action, subject_id, detail, integrity_hash "
            "FROM audit_log ORDER BY entry_id ASC"
        ).fetchall()
    prev = ""
    for entry_id, at, actor, action, subject_id, detail, stored_hash in rows:
        if not stored_hash:
            print(f"[SKIP] #{entry_id} — no hash (pre-migration row)")
            continue
        detail_json = json.dumps(detail, sort_keys=True, default=str) if isinstance(detail, dict) else (detail or "{}")
        chain = f"{prev}|{actor}|{action}|{subject_id or ''}|{detail_json}|{at.isoformat()}"
        computed = hashlib.sha256(chain.encode()).hexdigest()
        if computed == stored_hash:
            print(f"[OK]   #{entry_id} hash verified")
        else:
            print(f"[FAIL] #{entry_id} hash mismatch — possible tampering!")
            failures += 1
        prev = stored_hash
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
