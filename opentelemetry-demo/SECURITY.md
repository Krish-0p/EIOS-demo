# Security Hardening Guide — OpenTelemetry Demo

> Security controls applied to the OpenTelemetry Demo project per the **CIA Triad**:  
> **C**onfidentiality · **I**ntegrity · **A**vailability

---

## CIA Control Mapping

| Control | Pillar | File(s) | Status |
|---|---|---|---|
| Secrets removed from `.env` → `.env.security` placeholders | **C** | `.env.security` | ✅ Applied |
| `no-new-privileges:true` on all containers | **I** | `compose.security.yaml` | ✅ Applied |
| `cap_drop: ALL` on all containers | **I** | `compose.security.yaml` | ✅ Applied |
| `read_only: true` + `tmpfs: /tmp` on stateless services | **I** | `compose.security.yaml` | ✅ Applied |
| `otel-collector` user changed from `0:0` → `65534:65534` | **C/I** | `compose.security.yaml` | ✅ Applied |
| PostgreSQL host port binding removed (internal only) | **C** | `compose.security.yaml` | ✅ Applied |
| Valkey/Redis host port binding removed (internal only) | **C** | `compose.security.yaml` | ✅ Applied |
| Envoy admin (`10000`) bound to `127.0.0.1` | **C** | `envoy.tmpl.yaml` + `.env.security` | ✅ Applied |
| Security response headers (CSP, HSTS, XFO, XCO…) | **C/I** | `envoy.tmpl.yaml` | ✅ Applied |
| Envoy local rate limiter (1000 rps) | **A** | `envoy.tmpl.yaml` | ✅ Applied |
| OTel Collector `batch/security` processor | **A** | `otelcol-security.yml` | ✅ Applied |
| OTel Collector `transform/scrub_pii` — auth tokens, cookies, DB passwords | **C** | `otelcol-security.yml` | ✅ Applied |
| CPU limits on all services | **A** | `compose.security.yaml` | ✅ Applied |
| `POSTGRES_SSLMODE=require` | **C/I** | `.env.security` | ✅ Applied |
| Pre-flight security check script | **All** | `scripts/security-check.ps1` | ✅ Added |

---

## Files Created / Modified

| File | Action | Purpose |
|---|---|---|
| [`compose.security.yaml`](./compose.security.yaml) | **Created** | Docker Compose security overlay |
| [`.env.security`](./.env.security) | **Created** | Hardened environment variable overrides |
| [`src/otel-collector/otelcol-security.yml`](./src/otel-collector/otelcol-security.yml) | **Created** | OTel Collector batch + PII scrub extension |
| [`src/frontend-proxy/envoy.tmpl.yaml`](./src/frontend-proxy/envoy.tmpl.yaml) | **Modified** | Added security headers, rate limiter, loopback admin |
| [`scripts/security-check.ps1`](./scripts/security-check.ps1) | **Created** | Pre-flight security audit script |

---

## How to Apply the Security Overlay

### Step 1 — Rotate all secrets in `.env.security`

```bash
# Generate strong passwords
openssl rand -base64 32   # for POSTGRES_* passwords
openssl rand -hex 64      # for SECRET_KEY_BASE
```

Edit [`.env.security`](./.env.security) and replace every `REPLACE_WITH_…` placeholder.

### Step 2 — Run the pre-flight check

```powershell
.\scripts\security-check.ps1
# Must exit 0 before proceeding
```

### Step 3 — Start the stack with the security overlay

```bash
docker compose \
  --env-file .env \
  --env-file .env.security \
  -f compose.yaml \
  -f compose.full.yaml \
  -f compose.observability.yaml \
  -f compose.security.yaml \
  up
```

> [!IMPORTANT]
> `.env.security` **must come after** `.env` in the `--env-file` chain so it overrides the weak defaults.

---

## Secret Rotation Procedure

1. Generate new credentials:
   ```bash
   NEW_PG_PASS=$(openssl rand -base64 32)
   NEW_ASTRONOMY_PASS=$(openssl rand -base64 32)
   NEW_MONITORING_PASS=$(openssl rand -base64 32)
   NEW_SECRET_KEY=$(openssl rand -hex 64)
   ```

2. Update `.env.security` with the new values.

3. Rotate the PostgreSQL passwords **inside the database**:
   ```sql
   ALTER USER postgres           PASSWORD 'new_pg_pass';
   ALTER USER astronomy_user     PASSWORD 'new_astronomy_pass';
   ALTER USER monitoring_user    PASSWORD 'new_monitoring_pass';
   ```
   (These users are created by `src/postgresql/init.sql`.)

4. Re-deploy:
   ```bash
   docker compose ... up --force-recreate
   ```

5. Run the check script again and confirm exit code 0.

---

## Pre-Deployment Security Checklist

- [ ] All `REPLACE_WITH_…` placeholders replaced in `.env.security`
- [ ] `.env.security` excluded from version control (add to `.gitignore`)
- [ ] `scripts/security-check.ps1` passes with **0 HIGH findings**
- [ ] `POSTGRES_SSLMODE=require` confirmed in `.env.security`
- [ ] `ENVOY_ADMIN_ADDR=127.0.0.1` confirmed in `.env.security`
- [ ] Stack started with all four `-f` compose files **including** `compose.security.yaml`
- [ ] Verified no DB ports (5432, 6379) are bound to `0.0.0.0` after startup
- [ ] Verified Envoy admin port `10000` is **not** reachable externally
- [ ] OTel Collector container is running as UID `65534` (not root)
- [ ] Security headers present in browser DevTools → Network → Response Headers

> [!WARNING]
> Never commit `.env.security` (with real secrets) to source control.  
> Add `.env.security` to `.gitignore` immediately.

> [!CAUTION]
> `sslmode=require` will cause product-catalog to fail if PostgreSQL TLS is not configured.  
> For local dev without TLS configured on the Postgres container, use `sslmode=prefer` in `.env.security`.

---

## Architecture — Security Network Boundaries

```
 Internet
    │
    ▼  :8080 (public)
┌─────────────────┐
│  Envoy Proxy    │  ← Rate limiter, security headers, loopback admin
│ (frontend-proxy)│
└────────┬────────┘
         │ internal Docker network (opentelemetry-demo)
    ┌────┴──────────────────────────────────────┐
    │  frontend  checkout  payment  cart  ...   │
    │  (read_only, no-new-priv, cap_drop ALL)   │
    └────────────────────┬──────────────────────┘
                         │
              ┌──────────┴──────────┐
              │  astronomy-db       │  ← Port NOT exposed to host
              │  (PostgreSQL)       │
              │  valkey-cart        │  ← Port NOT exposed to host
              └─────────────────────┘
```
