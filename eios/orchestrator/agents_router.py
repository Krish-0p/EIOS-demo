"""Stored intelligence, durable investigation cases, and approval decisions.

This deterministic assistant summarizes measurements and stored findings.
Approval decisions are recorded separately from resource action execution.
"""
from __future__ import annotations
from datetime import datetime, timezone
import re
from typing import Any, Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import db
from intelligence_router import rows, status_snapshot
from chat_summary import intelligence_note, request_summary

router = APIRouter(prefix="/api", tags=["agents"])

class AIChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    context: dict[str, Any] | None = None

@router.post("/ai/chat")
def ai_assistant_chat(req: AIChatRequest):
    state = status_snapshot()
    service = (req.context or {}).get("service")
    if not isinstance(service,str):
        service = None
    windows = rows("""SELECT DISTINCT ON(service) * FROM feature_windows
        WHERE feature_version='2.0' AND (%s::text IS NULL OR service=%s)
        ORDER BY service,window_end DESC""",(service,service))
    if service is None:
        mentioned = [w for w in windows if re.search(
            r"(?<![\w-])" + re.escape(w["service"]) + r"(?![\w-])", req.query, re.IGNORECASE)]
        if mentioned:
            windows = mentioned
    now = datetime.now(timezone.utc)
    fresh = [w for w in windows if (now-w["window_end"]).total_seconds() <= 240]
    degraded = [w for w in fresh if w["features"].get("memory_fraction",0)>=.85
        or w["features"].get("error_fraction",0)>=.02 or w["features"].get("latency_p95_ms",0)>=500]
    incident_count = rows("""SELECT count(*) AS count FROM incidents WHERE detected_at > NOW()-INTERVAL '24 hours'
        AND (%s::text IS NULL OR entity_service=%s)""",(service,service))[0]["count"]
    findings = rows("""SELECT * FROM intelligence_insights WHERE (%s::text IS NULL OR service=%s)
        AND window_end > NOW()-INTERVAL '24 hours' ORDER BY window_end DESC LIMIT 5""",(service,service))
    query = req.query.lower()
    if any(k in query for k in ("memory","ram","leak","predict","forecast")):
        predictions = rows("""SELECT DISTINCT ON(service,horizon_minutes) * FROM intelligence_forecasts
            WHERE (%s::text IS NULL OR service=%s) ORDER BY service,horizon_minutes,observed_at DESC""",(service,service))
        relevant = [p for p in predictions if (now-p["observed_at"]).total_seconds() <= 240]
        values = [f"{w['service']}: {w['features']['memory_fraction']:.1%} memory"
            for w in fresh if "memory_fraction" in w["features"]]
        lines = values[:10] or ["No fresh memory measurements available."]
        for prediction in relevant[:5]:
            if prediction["state"] == "ready":
                values = prediction["values"]
                lines.append(f"{prediction['service']}: {prediction['horizon_minutes']}-minute projection "
                    f"{values['projected_memory_fraction']:.1%}; measured validation error "
                    f"{values['validation_mae_fraction']:.3f} fraction.")
            else:
                lines.append(f"{prediction['service']}: forecast abstained ({prediction['reason']}).")
    elif any(k in query for k in ("latency","slow","p95","error","payment","order","checkout")):
        lines = request_summary(fresh)
    else:
        lines = [f"[{i['severity']}] {i['title']} ({i['detector']}); observed {i['window_end'].isoformat()}."
            for i in findings] or ["No stored findings in the last 24 hours. This does not establish system health."]
    reply = "\n\n".join(lines + [intelligence_note(state), "No resource action was executed."])
    return {"reply":reply,"timestamp":now.isoformat(),"engine":"stored_analytics",
        "context_snapshot":{"services_count":len(windows),"degraded_count":len(degraded),
            "total_incidents":incident_count,"findings_in_context":len(findings),
            "active_models":len(state["active_models"]),"agent_state":state["state"]},
        "sources":[str(i["insight_id"]) for i in findings]}

def case_view(row):
    row["recommendation"] = row["enrichment"].get("recommendation",{
        "action":"inspect_evidence","title":"Review incident evidence","requires_approval":True,"execution":"manual"})
    return row

@router.get("/cases")
def list_cases():
    return [case_view(c) for c in rows("SELECT * FROM cases ORDER BY opened_at DESC LIMIT 100")]

@router.get("/cases/{case_id}")
def get_case(case_id: UUID):
    result = rows("SELECT * FROM cases WHERE case_id=%s",(case_id,))
    if not result:
        raise HTTPException(404,"Case not found")
    return case_view(result[0])

def approval_view(row):
    row["status"] = {"approve":"approved","reject":"rejected"}.get(row["decision"],"pending")
    row["target"] = (row["modification"] or {}).get("target")
    row["execution"] = "manual"
    return row

@router.get("/approvals")
def list_approvals():
    return [approval_view(a) for a in rows("SELECT * FROM approvals ORDER BY requested_at DESC LIMIT 100")]

@router.post("/cases/{case_id}/approvals",status_code=201)
def request_approval(case_id: UUID):
    case = get_case(case_id)
    recommendation = case["recommendation"]
    approval_id = uuid4()
    with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""INSERT INTO approvals(approval_id,case_id,action,rationale,destructive,requested_at,modification)
            VALUES(%s,%s,%s,%s,FALSE,NOW(),%s) RETURNING *""",(
            approval_id,case_id,recommendation["action"],recommendation.get("rationale","Review stored evidence"),
            Jsonb({"target":recommendation.get("target"),"execution":"manual"})))
        result = cur.fetchone()
        cur.execute("""INSERT INTO audit_log(actor,action,subject_kind,subject_id,detail)
            VALUES('operator','approval.request','approval',%s,%s)""",(str(approval_id),Jsonb({"case_id":str(case_id)})))
    return approval_view(result)

class ActionApprovalRequest(BaseModel):
    decision: Literal["approve","reject"]
    operator: str = Field(default="operator",min_length=1,max_length=100)
    notes: str | None = Field(default=None,max_length=2000)

@router.post("/approvals/{approval_id}/action")
def execute_approval(approval_id: UUID, req: ActionApprovalRequest, request: Request):
    import auth
    user=auth.require_role(request,'administrator')
    linked=rows('SELECT application_id,proposal_id FROM remediation_proposals WHERE approval_id=%s',(approval_id,))
    if linked:
        from workflow_runtime import decide
        return decide(linked[0]['application_id'],linked[0]['proposal_id'],user['username'],user['role'],req.decision,req.notes or '')
    req.operator=user['username']
    with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""UPDATE approvals SET decision=%s,decided_at=NOW(),decided_by=%s
            WHERE approval_id=%s AND decided_at IS NULL RETURNING *""",(req.decision,req.operator,approval_id))
        item = cur.fetchone()
        if not item:
            cur.execute("SELECT 1 FROM approvals WHERE approval_id=%s",(approval_id,))
            raise HTTPException(409 if cur.fetchone() else 404,"Approval already decided or not found")
        cur.execute("""INSERT INTO audit_log(actor,action,subject_kind,subject_id,detail)
            VALUES(%s,%s,'approval',%s,%s)""",(req.operator,f"governance.{req.decision}",str(approval_id),Jsonb(req.model_dump())))
    return {"status":"success","approval":approval_view(item),
        "message":f"Decision '{req.decision}' recorded. No resource action executed."}
