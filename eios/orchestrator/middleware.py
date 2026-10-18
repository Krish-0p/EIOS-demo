"""Session and optional machine-key protection for every operational HTTP API."""
import hmac
import ipaddress
import logging
import os
import time
import uuid
import threading
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import auth

log = logging.getLogger("eios.security")
_PUBLIC = {"/health", "/api/auth/status", "/api/auth/login", "/api/auth/register", "/api/auth/signup", "/api/auth/forgot-password", "/api/auth/reset-password", "/api/auth/logout"}
_MAX_BYTES = int(os.getenv("EIOS_MAX_REQUEST_BYTES", 1_048_576))
_rates = {}
_rate_lock = threading.Lock()


def rate_allowed(key, limit, seconds):
    tick=time.monotonic()
    with _rate_lock:
        if len(_rates)>10000:
            for old in [k for k,v in _rates.items() if not v or v[-1]<tick-3600]:
                _rates.pop(old,None)
        if key not in _rates and len(_rates)>=10000:
            return False
        bucket=_rates.setdefault(key,deque())
        while bucket and bucket[0]<=tick-seconds:
            bucket.popleft()
        if len(bucket)>=limit:
            return False
        bucket.append(tick)
        return True


def get_client_ip(request):
    value = request.client.host if request.client else ""
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return "unknown"


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        import asyncio
        request.state.request_id = str(uuid.uuid4())
        request.state.client_ip = get_client_ip(request)
        request.state.user = None
        guarded = request.url.path.startswith("/api/")
        unsafe = request.method not in ("GET", "HEAD", "OPTIONS")
        origin = request.headers.get("origin")
        if guarded and unsafe and origin and origin not in auth.allowed_origins():
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        if guarded and request.method != "OPTIONS":
            key = os.getenv("EIOS_API_KEY", "")
            supplied = request.headers.get("x-api-key", "")
            machine = bool(key and supplied and hmac.compare_digest(key, supplied))
            if machine:
                role=os.getenv('EIOS_MACHINE_ROLE','viewer')
                request.state.user = {"username": "machine", "user_id": None, "role": role if role in ('administrator','operator','viewer') else 'viewer'}
            else:
                token = request.cookies.get(auth.COOKIE_NAME)
                if token:
                    request.state.user = await asyncio.to_thread(auth.current_user, token)
                if token and unsafe and origin not in auth.allowed_origins():
                    return JSONResponse({"detail": "Origin required for cookie-authenticated changes"}, status_code=403)
            if request.url.path not in _PUBLIC:
                if not request.state.user:
                    return JSONResponse({"detail": "Sign in required"}, status_code=401)
                if unsafe and request.state.user["role"] == "viewer":
                    return JSONResponse({"detail": "Read-only account"}, status_code=403)
                # Executing commands or changing runtime resources requires an operator.
                if request.url.path.startswith("/api/terminal") and request.state.user["role"] == "viewer":
                    return JSONResponse({"detail": "Operator role required"}, status_code=403)
            identity=(request.state.user or {}).get('username',request.state.client_ip)
            seconds=int(os.getenv('EIOS_RATE_LIMIT_WINDOW','60'))
            limit=int(os.getenv('EIOS_RATE_LIMIT_REQUESTS','200'))
            if not rate_allowed(('api',identity),limit,seconds):
                return JSONResponse({'detail':'Rate limit exceeded'},status_code=429,headers={'Retry-After':str(seconds)})
            if request.url.path in ('/api/auth/forgot-password','/api/auth/reset-password','/api/auth/signup') and not rate_allowed(('public-auth',request.state.client_ip),10,300):
                return JSONResponse({'detail':'Too many account requests; try again later'},status_code=429,headers={'Retry-After':'300'})
            path=request.url.path
            if path.startswith(('/api/terminal','/api/fs')):
                if (request.state.user or {}).get('role')!='administrator':
                    return JSONResponse({'detail':'Administrator role required for workspace access'},status_code=403)
                setting = 'EIOS_ENABLE_ADMIN_TERMINAL' if path.startswith('/api/terminal') else 'EIOS_ENABLE_ADMIN_WORKSPACE'
                enabled=os.getenv(setting,os.getenv('EIOS_ENABLE_ADMIN_WORKSPACE','false')).lower()=='true'
                if not enabled:
                    return JSONResponse({'detail':'Administrator terminal access is disabled' if path.startswith('/api/terminal') else 'Administrator workspace access is disabled'},status_code=403)
            if unsafe and path.startswith('/api/docker/containers/') and path.rsplit('/',1)[-1] in ('start','stop','restart'):
                return JSONResponse({'detail':'Create and approve an application-scoped remediation proposal before executing runtime actions'},status_code=403)
            if unsafe and path.startswith('/api/faults/') and (request.state.user or {}).get('role')!='administrator':
                return JSONResponse({'detail':'Administrator role required for legacy fault controls; operators use Experiment Lab'},status_code=403)
        start = time.monotonic()
        response = await call_next(request)
        if guarded and unsafe and response.status_code<400 and request.state.user and not request.url.path.startswith('/api/auth/'):
            # Legacy mutating endpoints also leave a governance reference.
            def record_change():
                import db
                from workflow_store import audit
                with db.pool.connection() as conn:
                    audit(conn,request.state.user['username'],'api.change_recorded',{'method':request.method,
                        'path':request.url.path,'request_id':request.state.request_id,'status':response.status_code})
            try:
                await asyncio.to_thread(record_change)
            except Exception:
                log.exception('Could not append compatibility API audit reference')
        response.headers["x-request-id"] = request.state.request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        if guarded:
            response.headers["cache-control"] = "no-store"
        if unsafe:
            log.info("%s %s %dms rid=%s", request.method, request.url.path,
                     int((time.monotonic()-start)*1000), request.state.request_id)
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        length = request.headers.get("content-length")
        if length and int(length) > _MAX_BYTES:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        return await call_next(request)
