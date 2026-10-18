"""Process liveness; missing telemetry is a data state, not a process crash."""
import sys
import psycopg
from .config import POSTGRES_DSN

with psycopg.connect(POSTGRES_DSN,connect_timeout=3) as conn:
    row = conn.execute("SELECT updated_at > NOW()-INTERVAL '3 minutes' FROM intelligence_state WHERE key='worker'").fetchone()
    sys.exit(0 if row and row[0] else 1)
