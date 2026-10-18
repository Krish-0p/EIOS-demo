"""Database-backed accounts, first-administrator setup, and cookie sessions."""
import os
import re
import secrets
from uuid import UUID, uuid4
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

import auth
import db

router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY_HASH = auth.password_hash(secrets.token_urlsafe(32))


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["administrator", "operator", "viewer"] = "viewer"

class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)

class ForgotPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)

class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=8, max_length=256)

class RoleRequest(BaseModel):
    role: Literal['administrator','operator','viewer']


@router.patch('/users/{user_id}/role')
def change_role(user_id: UUID,body: RoleRequest,request: Request):
    actor=auth.require_role(request,'administrator')
    if str(actor.get('user_id'))==str(user_id):
        raise HTTPException(400,'Use another administrator to change your own role')
    with db.pool.connection() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(71023003)')
        target=conn.execute('SELECT role FROM users WHERE user_id=%s AND NOT disabled FOR UPDATE',(user_id,)).fetchone()
        if not target:
            raise HTTPException(404,'Enabled account not found')
        admins=conn.execute("SELECT count(*) FROM users WHERE role='administrator' AND NOT disabled").fetchone()[0]
        if target[0]=='administrator' and admins<=1 and body.role!='administrator':
            raise HTTPException(409,'Cannot remove the last administrator')
        conn.execute('UPDATE users SET role=%s WHERE user_id=%s',(body.role,user_id))
        conn.execute('UPDATE user_sessions SET revoked_at=NOW() WHERE user_id=%s AND revoked_at IS NULL',(user_id,))
        auth.audit(conn,actor['username'],'auth.role_changed',subject_id=user_id)
    return {'status':'updated','role':body.role,'sessions_revoked':True}


def set_cookie(response, token):
    response.set_cookie(auth.COOKIE_NAME, token, max_age=auth.SESSION_SECONDS,
        httponly=True, secure=os.getenv("EIOS_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax", path="/")


@router.get("/status")
def status():
    return {"setup_required": not bool(db._rows("SELECT 1 FROM users LIMIT 1")), "self_signup_enabled": True, "password_reset_enabled": True}

def _username(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", value):
        raise HTTPException(400, "Use 3–64 letters, numbers, dots, underscores, or hyphens")
    return value

@router.post("/signup", status_code=201)
def signup(body: SignupRequest):
    username = _username(body.username)
    try:
        with db.pool.connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(71023003)')
            if not conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                raise HTTPException(409,'Set up the first administrator before self-signup')
            user_id = uuid4()
            conn.execute("INSERT INTO users(user_id,username,password_hash,role) VALUES(%s,%s,%s,'viewer')",
                         (user_id, username, auth.password_hash(body.password)))
            auth.audit(conn, username, "auth.user_signed_up", subject_id=user_id)
        return {"status": "created", "user": username, "role": "viewer"}
    except UniqueViolation:
        raise HTTPException(409, "Username already exists")

@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest):
    # No email channel exists. Returning a bearer reset token publicly would
    # allow anyone knowing a username to take over that account.
    return {'status':'accepted','message':'Ask your EIOS administrator for a recovery token, then choose “I have a recovery token”. Email delivery is not configured.'}


@router.post('/users/{user_id}/password-reset')
def issue_reset(user_id: UUID, request: Request):
    actor=auth.require_role(request,'administrator')
    token=secrets.token_urlsafe(32)
    with db.pool.connection() as conn:
        if not conn.execute('SELECT 1 FROM users WHERE user_id=%s AND NOT disabled',(user_id,)).fetchone():
            raise HTTPException(404,'Account not found')
        conn.execute('UPDATE password_reset_tokens SET used_at=NOW() WHERE user_id=%s AND used_at IS NULL',(user_id,))
        conn.execute("INSERT INTO password_reset_tokens(token_hash,user_id,expires_at) VALUES(%s,%s,NOW()+INTERVAL '30 minutes')",(auth.token_hash(token),user_id))
        auth.audit(conn,actor['username'],'auth.recovery_issued',subject_id=user_id)
    return {'reset_token':token,'expires_in_seconds':1800,'delivery':'Administrator must deliver this token privately to the verified account owner.'}

@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest):
    with db.pool.connection() as conn:
        row = conn.execute("SELECT t.user_id FROM password_reset_tokens t JOIN users u USING(user_id) WHERE t.token_hash=%s AND t.used_at IS NULL AND t.expires_at>NOW() AND NOT u.disabled FOR UPDATE OF t", (auth.token_hash(body.token),)).fetchone()
        if not row:
            raise HTTPException(400, "Reset token is invalid or expired")
        conn.execute("UPDATE users SET password_hash=%s WHERE user_id=%s", (auth.password_hash(body.password), row[0]))
        conn.execute("UPDATE password_reset_tokens SET used_at=NOW() WHERE user_id=%s AND used_at IS NULL", (row[0],))
        conn.execute("UPDATE user_sessions SET revoked_at=NOW() WHERE user_id=%s AND revoked_at IS NULL", (row[0],))
        auth.audit(conn, "password_reset", "auth.password_reset", subject_id=row[0])
    return {"status": "password_updated"}


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request):
    username = _username(body.username)
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username):
        raise HTTPException(400, "Use 3–64 letters, numbers, dots, underscores, or hyphens")
    hashed = auth.password_hash(body.password)
    try:
        with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(71023003)")
            cur.execute("SELECT 1 FROM users LIMIT 1")
            first_user = cur.fetchone() is None
            actor = "initial_setup"
            role = "administrator"
            if not first_user:
                actor = auth.require_role(request, "administrator")["username"]
                role = body.role
            user_id = uuid4()
            cur.execute("INSERT INTO users(user_id,username,password_hash,role) VALUES(%s,%s,%s,%s)",
                        (user_id, username, hashed, role))
            auth.audit(conn, actor, "auth.user_created", subject_id=user_id)
        return {"status": "created", "user": username, "role": role}
    except UniqueViolation:
        raise HTTPException(409, "Username already exists")


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    username = body.username.strip().lower()
    actor = request.client.host if request.client else "unknown"
    attempts = db._rows("""SELECT count(*) AS count FROM audit_log
        WHERE actor=%(actor)s AND action='auth.login_failed' AND at>NOW()-INTERVAL '5 minutes'""", {"actor": actor})[0]["count"]
    if attempts >= 10:
        raise HTTPException(429, "Too many failed sign-in attempts. Try again later.")
    users = db._rows("SELECT * FROM users WHERE username=%(username)s", {"username": username})
    user = users[0] if users else None
    valid = auth.password_matches(body.password, user["password_hash"] if user else _DUMMY_HASH)
    if not user or not valid or user["disabled"]:
        with db.pool.connection() as conn:
            auth.audit(conn, actor, "auth.login_failed")
        raise HTTPException(401, "Invalid username or password")
    with db.pool.connection() as conn:
        previous = request.cookies.get(auth.COOKIE_NAME)
        if previous:
            conn.execute("UPDATE user_sessions SET revoked_at=NOW() WHERE token_hash=%s", (auth.token_hash(previous),))
        token, expires = auth.new_session(conn, user["user_id"])
        auth.audit(conn, username, "auth.login_success", subject_id=user["user_id"])
    set_cookie(response, token)
    return {"status": "authenticated", "user": username, "role": user["role"], "expires_at": expires}


@router.get("/me")
def me(request: Request):
    user = auth.require_role(request, "administrator", "operator", "viewer")
    return {"username": user["username"], "user_id": user["user_id"], "role": user["role"],
            "expires_at": user.get("expires_at"), "status": "active"}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        with db.pool.connection() as conn:
            conn.execute("UPDATE user_sessions SET revoked_at=NOW() WHERE token_hash=%s AND revoked_at IS NULL",
                         (auth.token_hash(token),))
            auth.audit(conn, getattr(request.state, "user", None).get("username", "session") if getattr(request.state, "user", None) else "session",
                       "auth.logout")
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"status": "signed_out"}


@router.get("/users")
def users(request: Request):
    auth.require_role(request, "administrator")
    return db._rows("SELECT user_id,username,role,disabled,created_at FROM users ORDER BY created_at")


@router.post("/users/{user_id}/disable")
def disable(user_id: UUID, request: Request):
    actor = auth.require_role(request, "administrator")
    if str(actor["user_id"]) == str(user_id):
        raise HTTPException(400, "Cannot disable your own account")
    with db.pool.connection() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(71023003)')
        target=conn.execute('SELECT role FROM users WHERE user_id=%s FOR UPDATE',(user_id,)).fetchone()
        if target and target[0]=='administrator' and conn.execute("SELECT count(*) FROM users WHERE role='administrator' AND NOT disabled").fetchone()[0]<=1:
            raise HTTPException(409,'Cannot disable the last administrator')
        row = conn.execute("UPDATE users SET disabled=TRUE WHERE user_id=%s RETURNING user_id", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        conn.execute("UPDATE user_sessions SET revoked_at=NOW() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
        auth.audit(conn, actor["username"], "auth.user_disabled", subject_id=user_id)
    return {"status": "disabled"}
