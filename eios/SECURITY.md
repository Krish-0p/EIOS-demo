# EIOS Security Architecture & Defense-in-Depth Specification

> **Note**: The OpenTelemetry Demo substrate was NOT developed by the EIOS team. EIOS is an intelligence and security layer operating on top of it.

---

## 1. System Topology & Security Ingress

```
[External Traffic / Operators]
            │
            ▼
┌───────────────────────────────┐
│     Envoy Proxy (:8080)       │  ◄── Rate Limiting, WAF rules, Security Headers, Port Isolation
└───────┬──────────────┬────────┘
        │              │
        ▼              ▼
┌──────────────┐ ┌────────────────────────────────────────────────────────┐
│  OTel Demo   │ │                   EIOS Intelligence                    │
│ Microservice │ │                                                        │
│  Substrate   │ │   ┌───────────────────────┐   ┌──────────────────────┐ │
│ (Storefront) │ │   │ EIOS Dashboard (:5173)│   │  Orchestrator (:8000)│ │
└──────────────┘ │   │ • KeyPrompt (Session) │   │  • X-API-Key Auth    │ │
                 │   │ • SecurityPanel Posture│  │  • Sliding RateLimit │ │
                 │   └───────────┬───────────┘   │  • 1MB Body Ceiling  │ │
                 │               │               │  • Trace X-Request-ID│ │
                 │               └──────────────►│  • Audit Interceptor │ │
                 │                               └───────────┬──────────┘ │
                 │                                           │            │
                 │      ┌──────────────────────┬─────────────┘            │
                 │      ▼                      ▼                          │
                 │ ┌──────────────┐  ┌────────────────────┐               │
                 │ │eios-postgres │  │    Kafka Cluster   │               │
                 │ │ • Hash-Chain │  │  (eios.events/     │               │
                 │ │   Audit Logs │  │   eios.incidents)  │               │
                 │ └──────────────┘  └─────────┬──────────┘               │
                 │                             │                          │
                 │               ┌─────────────┴─────────────┐            │
                 │               ▼                           ▼            │
                 │        [eios-ingest]               [eios-detect]       │
                 │        Regex PII Redaction         Rule Engine Guard   │
                 └────────────────────────────────────────────────────────┘
```

---

## 2. Security Addons & Techniques Implemented

### A. Confidentiality (Data Safety & Privacy)

| Control / Feature | File Location | Technique & Algorithm | Security Impact & Data Safety |
| :--- | :--- | :--- | :--- |
| **PII & Secret Redaction** | `eios/security/redactor.py`<br>`eios/ingest/sink.py` | **Compiled Regex Lexical Parsing**<br>Scans incoming event dictionaries recursively before storage or broker broadcast. | Prevents passwords, JWTs, Bearer tokens, Credit Cards, AWS keys (`AKIA...`), and DSN strings from ever being persisted to disk or distributed to telemetry consumers. |
| **API Key Authentication** | `eios/orchestrator/middleware.py` | **Constant-time Key Header Validation**<br>Checks `X-API-Key` on `/api/*` endpoints. Public endpoints (`/health`, `/api/security/status`, `/ws`) are explicitly whitelisted. | Closes unauthorized external access; orchestrator APIs and fault injection tools cannot be accessed by external attackers. |
| **Volatile Client Key Storage** | `eios/dashboard/src/hooks/useApiKey.ts`<br>`eios/dashboard/src/components/ApiKeyPrompt.tsx` | **Session Storage Scoping** (`sessionStorage`) | Isolates the sensitive API key from disk storage and persistent storage (`localStorage`). Protects against key persistence across browser sessions and cross-tab access. |
| **Cryptographic Secrets Generator** | `eios/scripts/generate-secrets.ps1` | **CSPRNG (Cryptographically Secure Pseudo-Random Number Generator)** via `.NET RandomNumberGenerator`. | Replaces vulnerable default credentials (`eios:eios`) with 32-byte high-entropy random keys for databases and APIs. |
| **Network & Port Isolation** | `eios/compose.eios.security.yaml`<br>`opentelemetry-demo/compose.security.yaml` | **Network Segmentation & Port Stripping** | Removes public port bindings for internal databases (`eios-postgres`, `astronomy-db`, `valkey-cart`). Database ports are strictly exposed inside the Docker bridge network. |

### B. Integrity (Tamper-Proofing & Anti-Tampering)

| Control / Feature | File Location | Technique & Algorithm | Security Impact & Data Safety |
| :--- | :--- | :--- | :--- |
| **Tamper-Evident Audit Logging** | `eios/security/audit.py`<br>`eios/db/migrate_security.sql` | **Cryptographic SHA-256 Hash Chaining**<br>`SHA-256(previous_hash + actor + action + subject + payload + timestamp)` | Creates an immutable, blockchain-style audit ledger. Any retroactive deletion, row update, or direct database tampering immediately breaks the chain. |
| **Audit Verification Engine** | `eios/scripts/audit-verify.py` | **Sequential Cryptographic Verification** | Recomputes every cryptographic link sequentially across the entire table, pinpointing the exact entry if tampering occurred. |
| **Distributed Request Tracing** | `eios/orchestrator/middleware.py` | **UUIDv4 Request Tagging (`X-Request-ID`)** | Stamps all requests and responses with a unique tracking identifier, correlating logs and detecting replay attacks. |
| **Immutable Container Runtime** | `eios/compose.eios.security.yaml`<br>`opentelemetry-demo/compose.security.yaml` | **Least Privilege & Read-Only Roots**<br>`security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, `read_only: true`, `tmpfs: [/tmp]` | Blocks attackers from gaining root access via privilege escalation vulnerabilities, and prevents persisting malicious payloads or rootkits to container filesystems. |
| **Security Headers Enforcement** | `eios/orchestrator/middleware.py` | **Defensive HTTP Response Headers**<br>`X-Content-Type-Options: nosniff`<br>`X-Frame-Options: DENY`<br>`Referrer-Policy: strict-origin-when-cross-origin` | Mitigates Clickjacking, MIME-sniffing exploits, and cross-origin information leakage. |

### C. Availability (DoS & Resource Exhaustion Defense)

| Control / Feature | File Location | Technique & Algorithm | Security Impact & Data Safety |
| :--- | :--- | :--- | :--- |
| **Sliding Window Rate Limiter** | `eios/security/ratelimit.py`<br>`eios/orchestrator/middleware.py` | **Sliding Window Counter** using thread-safe `collections.deque` and locks. | Rejects traffic surges beyond thresholds (default 200 req/60s per client IP) with `HTTP 429 Too Many Requests`, protecting services against brute-force and scraping. |
| **Payload Size Ceilings** | `eios/orchestrator/middleware.py` | **HTTP Content-Length Inspection** | Drops oversized request bodies exceeding 1 MB with `HTTP 413 Payload Too Large`, mitigating memory buffer exhaustion attacks. |
| **Kernel Resource Boundaries** | `eios/compose.eios.security.yaml`<br>`opentelemetry-demo/compose.security.yaml` | **cgroups Resource Quotas** (CPU & Memory limits) | Enforces hard memory and CPU limits per container, preventing "noisy neighbor" resource starvation from rogue or compromised microservices. |
| **Collector Memory Limiter** | `opentelemetry-demo/src/otel-collector/otelcol-security.yml` | **Telemetry Memory Limiter Processor** | Drops or sheds metric and trace traffic when collector memory limits are approached to prevent out-of-memory crashes. |

---

## 3. CIA Triad Mapping Summary

```
                      ┌──────────────────────────────────────────────┐
                      │                 CIA TRIAD                    │
                      └──────┬──────────────────┬──────────────────┬─┘
                             │                  │                  │
                CONFIDENTIALITY              INTEGRITY        AVAILABILITY
                ───────────────              ─────────        ────────────
                • PII Redaction              • SHA-256 Chain  • Sliding RateLimit
                • API Key Gatekeeper         • Audit Verifier • 1MB Body Ceiling
                • Session Storage Keys       • Read-Only Root • CPU / RAM Quotas
                • CSPRNG Random Secrets      • Dropped Caps   • OTel Memory Guard
                • Docker Port Unbinding      • Sec Headers    • Host Isolation
```

---

## 4. Operational Playbook

### 1. Generating or Rotating Credentials
```powershell
# Generate fresh random secrets (stored in .env)
cd d:\Eios\eios
.\scripts\generate-secrets.ps1

# Or rotate API key specifically
.\scripts\rotate-api-key.ps1
docker restart eios-orchestrator
```

### 2. Checking Security Posture via API
```bash
# Public status check
curl http://127.0.0.1:8000/api/security/status

# Authenticated audit logs check
curl -H "X-API-Key: <YOUR_EIOS_API_KEY>" http://127.0.0.1:8000/api/security/audit
```

### 3. Verifying Audit Log Chain Integrity
```bash
python scripts/audit-verify.py
# Output:
# [OK] Entry #1 hash verified
# [OK] Entry #2 hash verified
# [OK] Chain verified successfully. 0 tampered rows.
```

### 4. Running Security Test Suite
```bash
python -m pytest eios/security/tests/ -v
```

---

## 5. Production Gaps & Next Steps

| Gap | Production Requirement |
| :--- | :--- |
| **mTLS Mesh** | Service-to-service communication currently relies on Docker bridge networks; production requires Istio or Linkerd mutual TLS. |
| **Identity Provider (OIDC/SAML)** | API keys provide machine and operator auth; enterprise deployment should connect to Keycloak, Okta, or Azure AD. |
| **Kafka TLS / SASL** | Internal Kafka messaging uses PLAINTEXT internally; enterprise Kafka requires TLS and SASL/SCRAM auth. |
| **Secret Management** | Local `.env` files should be migrated to HashiCorp Vault or Kubernetes Secrets with KMS envelope encryption. |
