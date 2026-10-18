"""Persistent password authentication and opaque, revocable sessions."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, WebSocket
from psycopg.rows import dict_row

import db

COOKIE_NAME = "eios_session"
SESSION_SECONDS = int(os.getenv("EIOS_SESSION_SECONDS", "43200"))


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt$16384$8$1${salt}${digest}"


def password_matches(password, encoded):
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(token):
    if not token or len(token) > 256:
        return None
    rows = db._rows("""SELECT u.user_id,u.username,u.role,s.expires_at FROM user_sessions s
        JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=%(hash)s
        AND s.revoked_at IS NULL AND s.expires_at>NOW() AND NOT u.disabled""", {"hash": token_hash(token)})
    return rows[0] if rows else None


def new_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)
    conn.execute("INSERT INTO user_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)",
                 (token_hash(token), user_id, expires))
    return token, expires


def allowed_origins():
    return set(os.getenv("EIOS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))


def require_role(request: Request, *roles):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Sign in required")
    if user["role"] not in roles:
        raise HTTPException(403, "Insufficient permissions")
    return user


def audit(conn, actor, action, subject_kind="user", subject_id=None):
    conn.execute("INSERT INTO audit_log(actor,action,subject_kind,subject_id) VALUES(%s,%s,%s,%s)",
                 (actor, action, subject_kind, str(subject_id) if subject_id else None))
    from workflow_store import audit as governance_audit
    governance_audit(conn,actor,action,{'subject_kind':subject_kind,'subject_id':str(subject_id) if subject_id else None})


async def authorize_websocket(ws: WebSocket):
    import asyncio
    if ws.headers.get("origin") not in allowed_origins():
        await ws.close(code=1008)
        return False
    user = await asyncio.to_thread(current_user, ws.cookies.get(COOKIE_NAME))
    if not user:
        await ws.close(code=1008)
        return False
    ws.state.user = user
    return True
