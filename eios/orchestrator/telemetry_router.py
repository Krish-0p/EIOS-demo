"""Application-scoped source observations and normalized evidence APIs."""
from datetime import datetime, timedelta, timezone
import logging
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import auth
import catalog
import db
from telemetry import DEFAULT_APPLICATION_ID, source_id
from telemetry.health import view, observe
from telemetry.sources import endpoint, validate_scope, probe
from telemetry.evidence import traces, logs, save

router = APIRouter(prefix='/api/applications/{application_id}/telemetry',tags=['telemetry'])
log = logging.getLogger('eios.telemetry')


class SourceSettings(BaseModel):
    kind: Literal['prometheus','jaeger','opensearch']
    endpoint: str = Field(max_length=512)
    scope: dict = Field(default_factory=dict)
    enabled: bool = True
    freshness_seconds: int = Field(default=240,ge=30,le=86400)


@router.get('/sources')
def sources(application_id: UUID):
    catalog.application(application_id)
    return [view(row) for row in db._rows('SELECT * FROM telemetry_sources WHERE application_id=%(app)s ORDER BY kind',
        {'app':application_id})]


@router.post('/sources',status_code=201)
def configure(application_id: UUID, body: SourceSettings, request: Request):
    user = auth.require_role(request,'administrator')
    catalog.application(application_id)
    try:
        url = endpoint(body.endpoint)
        key,terms = validate_scope(body.kind,body.scope)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    sid = source_id(application_id,body.kind)
    with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT pg_advisory_xact_lock(71023005)')
        # A shared backend needs a provably disjoint exact label/tag/term. A
        # service name alone cannot separate two applications with equal names.
        others = cur.execute('SELECT * FROM telemetry_sources WHERE kind=%s AND endpoint=%s AND application_id<>%s',
            (body.kind,url,application_id)).fetchall()
        for other in others:
            old = other['scope'].get(key,{})
            if not any(name in old and old[name]!=value for name,value in terms.items()):
                raise HTTPException(409,'Shared backend requires disjoint application/environment selectors on every binding')
        existing = cur.execute('SELECT * FROM telemetry_sources WHERE source_id=%s',(sid,)).fetchone()
        if existing and (existing['endpoint']!=url or existing['scope']!=body.scope):
            if cur.execute('SELECT 1 FROM events WHERE source_id=%s UNION ALL SELECT 1 FROM telemetry_evidence WHERE source_id=%s LIMIT 1',
                (sid,sid)).fetchone():
                raise HTTPException(409,'Source endpoint/scope is immutable after data exists; register a separate application')
        cur.execute('''INSERT INTO telemetry_sources(source_id,application_id,kind,endpoint,scope,enabled,freshness_seconds)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(application_id,kind) DO UPDATE SET
            endpoint=EXCLUDED.endpoint,scope=EXCLUDED.scope,enabled=EXCLUDED.enabled,
            freshness_seconds=EXCLUDED.freshness_seconds,updated_at=NOW()''',
            (sid,application_id,body.kind,url,Jsonb(body.scope),body.enabled,body.freshness_seconds))
        auth.audit(conn,user['username'],'telemetry.source_configured','application',application_id)
    return next(row for row in sources(application_id) if row['source_id']==sid)


def envelope(row, now=None):
    now = now or datetime.now(timezone.utc)
    at = row.get('source_observed_at') or row['observed_at']
    age = max(0,(now-at).total_seconds())
    return {**row,'timestamp':row['observed_at'],'source_type':row.get('kind') or row.get('source'),
        'freshness':'fresh' if age<=row.get('freshness_seconds',240) else 'stale','age_seconds':age,
        'identity_state':'resolved' if row.get('service_id') else 'unresolved'}


def service_for(application_id, service_id):
    app = catalog.application(application_id)
    found = db._rows('SELECT * FROM services WHERE application_id=%(app)s AND service_id=%(svc)s',
        {'app':application_id,'svc':service_id})
    if not found:
        raise HTTPException(404,'Service not registered in this application')
    return app,found[0]


@router.get('/records')
def records(application_id: UUID, service_id: UUID | None=None,
            signal_type: Literal['metric','business_event','source_health','trace','log'] | None=None,
            minutes: int=Query(15,ge=1,le=1440),limit: int=Query(50,ge=1,le=100)):
    catalog.application(application_id)
    if service_id:
        service_for(application_id,service_id)
    params = {'app':application_id,'svc':service_id,'signal':signal_type,'minutes':minutes,'limit':limit}
    rows = db._rows('''SELECT e.event_id,e.application_id,e.service_id,e.service_name,e.environment,e.source_id,
        e.signal_type,e.source,e.observed_at,e.source_observed_at,e.ingested_at,e.metrics,e.attributes,e.trace_id,e.raw_ref,
        t.kind,t.freshness_seconds FROM events e LEFT JOIN telemetry_sources t USING(application_id,source_id)
        WHERE e.application_id=%(app)s AND (%(svc)s::uuid IS NULL OR e.service_id=%(svc)s)
        AND (%(signal)s::text IS NULL OR e.signal_type=%(signal)s)
        AND e.observed_at>=NOW()-(%(minutes)s*INTERVAL '1 minute') ORDER BY e.observed_at DESC LIMIT %(limit)s''',params)
    evidence = db._rows('''SELECT e.*,t.kind,t.freshness_seconds FROM telemetry_evidence e
        JOIN telemetry_sources t USING(application_id,source_id)
        WHERE e.application_id=%(app)s AND (%(svc)s::uuid IS NULL OR e.service_id=%(svc)s)
        AND (%(signal)s::text IS NULL OR e.signal_type=%(signal)s)
        AND e.observed_at>=NOW()-(%(minutes)s*INTERVAL '1 minute') ORDER BY e.observed_at DESC LIMIT %(limit)s''',params)
    return [envelope(row) for row in sorted(rows+evidence,key=lambda row:row['observed_at'],reverse=True)[:limit]]


@router.get('/services/{service_id}/evidence/{signal}')
def evidence(application_id: UUID,service_id: UUID,signal: Literal['trace','log'],
             minutes: int=Query(15,ge=1,le=60),limit: int=Query(10,ge=1,le=50),
             end: datetime | None=None):
    app,service = service_for(application_id,service_id)
    now = datetime.now(timezone.utc)
    end = end or now
    if end.tzinfo is None or end>now+timedelta(seconds=60) or end<now-timedelta(days=1):
        raise HTTPException(400,'Use an aware evidence end time within the last day')
    start = end-timedelta(minutes=minutes)
    kind = 'jaeger' if signal=='trace' else 'opensearch'
    found = db._rows('SELECT * FROM telemetry_sources WHERE application_id=%(app)s AND kind=%(kind)s AND enabled',
        {'app':application_id,'kind':kind})
    if not found:
        return {'state':'unknown','reason':'Source not configured/enabled','records':[],'cached':False}
    source = found[0]
    error = None
    try:
        with httpx.Client(base_url=source['endpoint'],follow_redirects=False) as client:
            fetched = (traces if signal=='trace' else logs)(client,source,service['name'],start,end,min(limit,20) if signal=='trace' else limit)
        with db.pool.connection() as conn:
            save(conn,source,app,service,signal,fetched)
            # Historical evidence queries must not refresh the latest source clock.
            observe(conn,source['source_id'],data_at=max((row['observed_at'] for row in fetched),default=None))
    except (httpx.HTTPError,ValueError,KeyError,TypeError,OverflowError):
        error = 'Evidence source unavailable or returned invalid/incomplete data'
        with db.pool.connection() as conn:
            observe(conn,source['source_id'],error=error)
    cached = db._rows('''SELECT e.*,t.kind,t.freshness_seconds FROM telemetry_evidence e
        JOIN telemetry_sources t USING(application_id,source_id) WHERE e.application_id=%(app)s
        AND e.service_id=%(svc)s AND e.signal_type=%(signal)s AND e.observed_at BETWEEN %(start)s AND %(end)s
        ORDER BY e.observed_at DESC LIMIT %(limit)s''',{'app':application_id,'svc':service_id,'signal':signal,
            'start':start,'end':end,'limit':limit})
    source_view = next(row for row in sources(application_id) if row['kind']==kind)
    return {'state':source_view['state'],'reason':error,'records':[envelope(row) for row in cached],
        'cached':error is not None,'window_start':start,'window_end':end,'source':source_view}


def source_loop(stop):
    while not stop.is_set():
        try:
            for source in db._rows('SELECT * FROM telemetry_sources WHERE enabled AND kind IN (\'jaeger\',\'opensearch\')'):
                if stop.is_set():
                    break
                with db.pool.connection() as conn:
                    probe(conn,source)
        except Exception:
            log.exception('Telemetry source observations unavailable')
        stop.wait(30)
