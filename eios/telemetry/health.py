"""Connection checks and source data freshness are independent observations."""
from datetime import datetime, timezone


def observe(conn, source_id, *, error=None, data_at=None):
    conn.execute('''UPDATE telemetry_sources SET checked_at=NOW(),last_error=%s,
        last_success_at=CASE WHEN %s::text IS NULL THEN NOW() ELSE last_success_at END,
        last_data_at=CASE WHEN %s::timestamptz IS NULL THEN last_data_at
            ELSE GREATEST(last_data_at,%s::timestamptz) END WHERE source_id=%s''',
        (error,error,data_at,data_at,source_id))


def view(source, now=None):
    now = now or datetime.now(timezone.utc)
    checked, data = source['checked_at'],source['last_data_at']
    age = max(0,(now-data).total_seconds()) if data else None
    heartbeat_age = max(0,(now-checked).total_seconds()) if checked else None
    if not source['enabled'] or checked is None:
        state = 'unknown'
    elif heartbeat_age > 90:
        state = 'stale'
    elif source['last_error']:
        state = 'disconnected'
    elif age is None:
        state = 'unknown'
    elif age > source['freshness_seconds']:
        state = 'stale'
    else:
        state = 'connected'
    return {**source,'state':state,'data_age_seconds':age,'check_age_seconds':heartbeat_age,
        'freshness_basis':'broker_watermark_or_business_event' if source['kind']=='kafka' else 'source_sample',
        'connection_state':'unknown' if not source['enabled'] or checked is None or heartbeat_age>90 else (
            'disconnected' if source['last_error'] else 'connected'),
        'freshness':'unknown' if age is None else ('fresh' if age<=source['freshness_seconds'] else 'stale')}
