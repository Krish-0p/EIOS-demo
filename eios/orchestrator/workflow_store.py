"""Bounded scoped reads, lifecycle transitions and durable governance history."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import db


def now():
    return datetime.now(timezone.utc)


def clean(value):
    return jsonable_encoder(value)


def blob(value):
    return Jsonb(clean(value))


def rows(sql, params=(), conn=None):
    if conn is None:
        with db.pool.connection() as connection:
            return rows(sql, params, connection)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def one(sql, params=(), conn=None):
    found = rows(sql, params, conn)
    if not found:
        raise HTTPException(404, 'Record not found in this application')
    return found[0]


def incident(app, incident_id, conn=None):
    return one('SELECT * FROM operational_incidents WHERE application_id=%s AND incident_id=%s', (app, incident_id), conn)


def service(app, service_id, conn=None):
    return one('SELECT * FROM services WHERE application_id=%s AND service_id=%s', (app, service_id), conn)


def timeline(conn, incident_id, kind, detail=None, actor='workflow'):
    conn.execute('INSERT INTO incident_timeline(incident_id,kind,actor,detail) VALUES(%s,%s,%s,%s)',
                 (incident_id, kind, actor, blob(detail or {})))


TRANSITIONS = {
    'DETECTED': {'CORRELATING'}, 'CORRELATING': {'INVESTIGATING'},
    'INVESTIGATING': {'ROOT_CAUSE_IDENTIFIED','ESCALATED'},
    'ROOT_CAUSE_IDENTIFIED': {'ACTION_RECOMMENDED','INVESTIGATING'},
    'ACTION_RECOMMENDED': {'AWAITING_APPROVAL','INVESTIGATING'},
    'AWAITING_APPROVAL': {'REMEDIATING','INVESTIGATING','ESCALATED'},
    'REMEDIATING': {'VERIFYING','ESCALATED'},
    'VERIFYING': {'RESOLVED','ESCALATED'},
    'ESCALATED': {'INVESTIGATING'}, 'RESOLVED': set(),
}


def transition(conn, incident_id, target, detail=None, actor='workflow'):
    row = one('SELECT * FROM operational_incidents WHERE incident_id=%s FOR UPDATE', (incident_id,), conn)
    if row['state'] == target:
        return
    if target not in TRANSITIONS[row['state']]:
        raise HTTPException(409, f"Cannot transition {row['state']} to {target}")
    conn.execute('UPDATE operational_incidents SET state=%s,updated_at=NOW(),resolved_at=CASE WHEN %s=\'RESOLVED\' THEN NOW() ELSE NULL END WHERE incident_id=%s',
                 (target, target, incident_id))
    conn.execute('UPDATE cases SET status=%s,closed_at=CASE WHEN %s=\'RESOLVED\' THEN NOW() ELSE NULL END WHERE case_id=%s',
                 (target.lower(), target, row['case_id']))
    timeline(conn, incident_id, target, {'from': row['state'], **(detail or {})}, actor)


def audit(conn, actor, action, detail):
    from security.redactor import redact
    # Serialize all writers so sequence order and chain order agree.
    conn.execute('SELECT pg_advisory_xact_lock(71023016)')
    previous = conn.execute('SELECT integrity_hash FROM governance_audit ORDER BY sequence DESC LIMIT 1').fetchone()
    previous = previous[0] if previous else ''
    at = now()
    def redact_values(value):
        if isinstance(value,str):
            return redact(value)
        if isinstance(value,dict):
            return {k:redact_values(v) for k,v in value.items()}
        if isinstance(value,list):
            return [redact_values(v) for v in value]
        return value
    payload = redact_values(clean(detail))
    canonical = json.dumps({'at': at.isoformat(), 'actor': actor, 'action': action, 'detail': payload,
                            'previous_hash': previous}, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    conn.execute('INSERT INTO governance_audit(at,actor,action,detail,previous_hash,integrity_hash) VALUES(%s,%s,%s,%s,%s,%s)',
                 (at, actor, action, blob(payload), previous, digest))


def detail(app, incident_id):
    result = incident(app, incident_id)
    result['anomalies'] = rows('''SELECT a.*,s.name AS service,c.correlation FROM operational_anomalies a
        JOIN incident_anomalies c USING(anomaly_id) JOIN services s USING(service_id)
        WHERE c.incident_id=%s ORDER BY a.observed_at''', (incident_id,))
    for key, query in {
        'timeline': 'SELECT * FROM incident_timeline WHERE incident_id=%s ORDER BY event_id',
        'rca': 'SELECT * FROM rca_rankings WHERE incident_id=%s ORDER BY created_at DESC LIMIT 10',
        'investigations': 'SELECT * FROM investigation_runs WHERE incident_id=%s ORDER BY created_at DESC LIMIT 10',
        'proposals': '''SELECT p.*,a.decision,a.decided_by,a.decided_at FROM remediation_proposals p
            JOIN approvals a USING(approval_id) WHERE p.incident_id=%s ORDER BY p.created_at DESC''',
        'executions': '''SELECT e.* FROM remediation_executions e JOIN remediation_proposals p USING(proposal_id)
            WHERE p.incident_id=%s ORDER BY e.started_at''',
        'verifications': 'SELECT * FROM recovery_verifications WHERE incident_id=%s ORDER BY created_at DESC',
    }.items():
        result[key] = rows(query, (incident_id,))
    return result
