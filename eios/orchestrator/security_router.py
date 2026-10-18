"""Security API endpoints."""
from __future__ import annotations
import os
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
import auth
import db

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/status")
def security_status() -> dict:
    return {
        "security_enabled": True,
        "session_authentication": True,
        "api_key_enabled": bool(os.getenv("EIOS_API_KEY")),
        "rate_limiting": {
            "requests_per_window": int(os.getenv("EIOS_RATE_LIMIT_REQUESTS", 200)),
            "window_seconds": int(os.getenv("EIOS_RATE_LIMIT_WINDOW", 60)),
        },
        "redaction_enabled": os.getenv("EIOS_REDACTION_ENABLED", "true").lower() == "true",
        "audit_integrity": True,
        "audit_scope": "governance_audit is hash-chained; legacy audit_log remains separate",
        "rate_limit_scope": "per-process authenticated identity; direct client IP for public endpoints",
        "admin_workspace_enabled": os.getenv('EIOS_ENABLE_ADMIN_WORKSPACE','false').lower()=='true',
        "cors_origins": os.getenv("EIOS_CORS_ORIGINS", "http://localhost:5173").split(","),
        "version": "1.0.0",
    }


@router.get("/audit")
def security_audit(request: Request) -> list[dict]:
    auth.require_role(request,'administrator')
    return db.audit_entries()


@router.get("/alerts")
def security_alerts(request: Request) -> list[dict]:
    auth.require_role(request,'administrator')
    return db.security_alerts()


class RedactionRequest(BaseModel):
    text: str = Field(max_length=10000)


@router.post('/redact')
def redact_preview(body: RedactionRequest,request: Request):
    auth.require_role(request,'administrator')
    from security.redactor import redact
    return {'redacted':redact(body.text),'scope':'Preview using the server redactor. Preview text is not persisted.'}
