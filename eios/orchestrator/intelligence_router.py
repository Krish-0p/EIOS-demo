"""Read stored intelligence; operators provide feedback without executing actions."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import db
from schemas.intelligence import IntelligenceInsight, Forecast, ModelVersion, IntelligenceFeedback

router = APIRouter(prefix="/api", tags=["intelligence"])


def rows(sql, params=()):
    with db.pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def status_snapshot():
    now = datetime.now(timezone.utc)
    worker = rows("SELECT * FROM intelligence_state WHERE key='worker'")
    healthy = bool(worker and (now-worker[0]["updated_at"]).total_seconds() < 120
        and worker[0]["value"].get("process_state") != "error")
    models = rows("""SELECT m.service,m.model_id,m.last_inference_at,s.value AS latest_inference
        FROM model_registry m LEFT JOIN intelligence_state s ON s.key='inference:'||m.service
        WHERE m.state='active'""")
    latest = rows("""SELECT DISTINCT ON(service) service,window_end,quality FROM feature_windows
        WHERE feature_version='2.0' ORDER BY service,window_end DESC""")
    fresh_services = [w["service"] for w in latest if (now-w["window_end"]).total_seconds() <= 240]
    state = "unavailable" if not healthy or not fresh_services else "ready" if models else "learning"
    if state=="ready" and any((m["latest_inference"] or {}).get("state")!="ready" for m in models):
        state = "degraded" if any(m["latest_inference"] for m in models) else "learning"
    return {"state":state,"worker_alive":healthy,"worker":worker[0]["value"] if worker else {},
        "active_models":models,"fresh_services":fresh_services,
        "stale_services":[w["service"] for w in latest if w["service"] not in fresh_services],
        "training_required":not bool(models),"feature_version":"2.0",
        "services_without_active_model":[s for s in fresh_services if s not in {m["service"] for m in models}],
        "score_meaning":"Unusualness, not failure probability",
        "pending_notifications":rows("SELECT count(*) AS count FROM intelligence_outbox WHERE published_at IS NULL")[0]["count"]}


@router.get("/intelligence/status")
def status():
    return status_snapshot()


@router.get("/intelligence/insights",response_model=list[IntelligenceInsight])
def insights(service: str | None = None, since: datetime | None = None, limit: int = Query(50,ge=1,le=500)):
    return rows("""SELECT * FROM intelligence_insights WHERE (%s::text IS NULL OR service=%s)
        AND window_end >= %s ORDER BY window_end DESC LIMIT %s""",
        (service,service,since or datetime.now(timezone.utc)-timedelta(hours=24),limit))


@router.get("/incidents/{incident_id}/intelligence",response_model=list[IntelligenceInsight])
def incident_intelligence(incident_id: UUID):
    if not rows("SELECT 1 FROM incidents WHERE incident_id=%s",(incident_id,)):
        raise HTTPException(404,"Incident not found")
    return rows("SELECT * FROM intelligence_insights WHERE incident_id=%s ORDER BY created_at DESC",(incident_id,))


@router.get("/intelligence/forecasts",response_model=list[Forecast])
def forecasts(service: str | None = None, limit: int = Query(100,ge=1,le=500)):
    result = rows("""SELECT DISTINCT ON(service,horizon_minutes) * FROM intelligence_forecasts
        WHERE (%s::text IS NULL OR service=%s) ORDER BY service,horizon_minutes,observed_at DESC LIMIT %s""",(service,service,limit))
    for row in result:
        row["data_fresh"] = (datetime.now(timezone.utc)-row["observed_at"]).total_seconds() <= 240
    return result


@router.get("/intelligence/kpis")
def kpis(service: str | None = None, limit: int = Query(100,ge=1,le=500)):
    result = rows("""SELECT DISTINCT ON(service) * FROM feature_windows
        WHERE feature_version='2.0' AND (%s::text IS NULL OR service=%s)
        ORDER BY service,window_end DESC LIMIT %s""",(service,service,limit))
    for row in result:
        row["data_fresh"] = (datetime.now(timezone.utc)-row["window_end"]).total_seconds() <= 240
    return result


@router.get("/intelligence/history")
def history(service: str, minutes: int = Query(60,ge=1,le=1440)):
    return rows("""SELECT * FROM feature_windows WHERE service=%s AND feature_version='2.0'
        AND window_end >= NOW()-(%s*INTERVAL '1 minute') ORDER BY window_end""",(service,minutes))


@router.get("/intelligence/models",response_model=list[ModelVersion])
def models(service: str | None = None):
    return rows("SELECT * FROM model_registry WHERE (%s::text IS NULL OR service=%s) ORDER BY created_at DESC LIMIT 200",(service,service))


@router.get("/intelligence/inferences")
def inferences(service: str | None = None):
    return rows("""SELECT substring(key from 11) AS service,value,updated_at FROM intelligence_state
        WHERE key LIKE 'inference:%%' AND (%s::text IS NULL OR key='inference:' || %s) ORDER BY updated_at DESC""",(service,service))


@router.post("/intelligence/feedback",status_code=201)
def feedback(body: IntelligenceFeedback):
    feedback_id = uuid4()
    with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intelligence_insights WHERE insight_id=%s FOR UPDATE",(body.insight_id,))
        insight = cur.fetchone()
        if not insight:
            raise HTTPException(404,"Insight not found")
        cur.execute("""INSERT INTO intelligence_feedback(feedback_id,insight_id,verdict,operator,notes)
            VALUES(%s,%s,%s,%s,%s)""",(feedback_id,body.insight_id,body.verdict,body.operator,body.notes))
        if body.verdict in ("confirm","dismiss"):
            cur.execute("UPDATE intelligence_insights SET status=%s WHERE insight_id=%s",
                ("confirmed" if body.verdict=="confirm" else "dismissed",body.insight_id))
            cur.execute("UPDATE incidents SET status=%s WHERE incident_id=%s",
                ("investigating" if body.verdict=="confirm" else "dismissed",insight["incident_id"]))
        cur.execute("""INSERT INTO audit_log(actor,action,subject_kind,subject_id,detail)
            VALUES(%s,'intelligence.feedback','insight',%s,%s)""",(body.operator,str(body.insight_id),Jsonb(body.model_dump(mode="json"))))
    return {"feedback_id":feedback_id,"verdict":body.verdict,"model_updated":False,
        "message":"Feedback stored. Retraining and promotion remain explicit operator steps."}


@router.get("/intelligence/evaluations")
def evaluations(service: str | None = None):
    return rows("""SELECT * FROM evaluation_runs WHERE (%s::text IS NULL OR service=%s)
        ORDER BY started_at DESC LIMIT 100""",(service,service))
