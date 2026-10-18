# Phase 1 implementation report

Date: 18 October 2026. Scope: authentication, server sessions, application registry, and service catalog only. Phase 2 has not started.

## Implemented behavior

- PostgreSQL-backed administrator/operator/viewer accounts replace the in-memory account store. Passwords use scrypt with random per-password salts. Registration cannot overwrite accounts. First-administrator setup is serialized; later account creation requires an administrator.
- Random session tokens are stored as SHA-256 hashes. HttpOnly, SameSite cookies carry the opaque token; the API validates its database record, expiry, revocation, and current user status. Default absolute expiry is 12 hours. Login no longer returns the master API key or a JavaScript-readable session token.
- Operational HTTP APIs require a valid session or an explicitly configured machine API key. Role checks protect writes, account administration, discovery, and terminal access. Cookie-authenticated writes require an allowed browser origin. WebSockets validate the session and origin at connection and recheck session validity within 30 seconds.
- Refresh validates the session with the server before displaying the desktop. Lock/Reboot revoke it. Browser-only prototype login flags cannot grant access. The profile shows the authenticated username and actual role.
- The dashboard proxies API/WebSocket traffic through its own origin. Its build/runtime are pinned to Bun 1.3.11 and use a frozen lockfile. Build contexts exclude local dependencies, build output, and environment files.
- Applications persist name, environment, runtime type, labels, discovery scope, telemetry configuration, and observation timestamps/errors. Scoped Docker discovery requires a Compose project, label selector, or explicit container names. Combined selectors narrow the result.
- Services use UUIDs derived from application UUID plus logical service name. Runtime/container IDs are separate instance records. Repeated discovery, replicas, missing containers, and recreated containers preserve the logical service ID. Explicit manual runtime aliases retain their registered service identity. A container cannot be silently reassigned to another application.
- The existing onboarding entry point now opens a shadcn Application Registry and Service Catalog. Application creation, service registration, discovery, and catalog reads use persisted APIs. The simulated agent-pipeline completion and invented connection claims have been removed from onboarding.

## Database and migration

New tables: `users`, `user_sessions`, `applications`, `services`, `service_runtime_instances`, and `schema_migrations`.

The versioned `phase1-v1` migration runs transactionally under an advisory lock. It adds application/service references to events, incidents, cases, feature windows, model registry entries, findings, forecasts, and evaluations. It creates the default Astronomy Shop application and registers historical service names. Composite foreign keys prevent a service reference from belonging to a different application.

Existing IDs, original columns, case/approval relationships, feature-window keys, producer contracts, and detector/model algorithms remain in place. Database triggers associate new persisted records from the legacy pipeline without changing its Kafka payloads. Unresolved service identity remains nullable rather than inventing a binding. Legacy records remain associated with Astronomy Shop.

Backups were retained in `C:\Users\Krisss\Documents\eios2\.phase1\before-phase1.dump` and `before-phase1-live.dump`. The migration was rehearsed on restored copies before use. For the live run, EIOS writers were paused, PostgreSQL restarted using its existing volume, another backup taken, and every historical identity compared before/after migration. The live migration and identity checks took 51.73 seconds.

| Existing data at live migration | Rows retained | Identity check |
| --- | ---: | --- |
| Events | 86,636 | All event IDs unchanged |
| Incidents | 1,323 | All incident IDs unchanged |
| Cases | 66 | All case IDs unchanged |
| Approvals | 0 | Schema preserved; nonempty preservation tested in isolation |
| Fault windows | 22 | All window IDs unchanged |
| Intelligence findings | 1,099 | All finding IDs unchanged |
| Forecasts | 20,066 | All forecast IDs unchanged |
| Feature windows | 10,101 | All composite keys unchanged |
| Models/evaluations | 0 / 0 | Existing empty baseline preserved |

All eight history tables had zero unassigned application references after backfill. Exact identity digests are in [PHASE1_EVIDENCE.json](PHASE1_EVIDENCE.json).

The existing volumes remain `opentelemetry-demo_eios-pgdata` and `opentelemetry-demo_eios-models`. No volume was removed or recreated. Five disposable test databases were removed after testing. Ingestion, detectors, intelligence algorithms, and OpenTelemetry Demo business logic were not rewritten.

## State semantics

| State | Meaning |
| --- | --- |
| Not discovered | Registration exists; no successful discovery has been recorded |
| Connected | A successful scoped Docker observation is less than 90 seconds old |
| Unavailable | Discovery failed; registered services and previous observations are retained |
| Stale | Successful runtime observation is older than 90 seconds; current runtime state becomes unknown |
| Offline | A successful scoped observation confirms no running instance for the registered service |
| Unknown health | Docker health checks are absent, or a current health observation is unavailable |
| Fresh telemetry | Persisted source observation is no more than 240 seconds old |
| Stale/not observed telemetry | Observation is older than that deadline, or none exists |
| Configured endpoint | Configuration is saved; no connector activation or verified connection is implied |

The open catalog polls every 10 seconds. Background runtime reconciliation runs every 30 seconds. Cached UI observations also age by timestamp when API polling fails. Slow CPU/memory statistics do not block the catalog. API failures preserve the displayed records and show an error.

## Live acceptance evidence

The existing demo administrator was persisted using its existing password. Anonymous operational access and an incorrect password returned HTTP 401. Login issued an HttpOnly cookie without returning a token/master key in the body. A logged-out cookie was replayed and rejected with HTTP 401. An already-open authenticated WebSocket closed with code 1008 after revocation.

The same authenticated session and catalog IDs survived another PostgreSQL/API/worker restart without another login. The registry contains two applications and 53 services at verification: 51 historical/discovered Astronomy Shop records and two services in the new **EIOS Platform** application. Historical-only records with no verified runtime binding remain unknown rather than being deleted or declared online.

EIOS Platform application ID: `15a91729-4ab0-4a45-9ba6-629270c93328`. Its explicit Docker scope selected exactly `eios-orchestrator` and `eios-dashboard`. Manual registration followed by discovery retained the service ID; repeat discovery and restart did not create duplicate services.

One controlled stop/start used the existing email container. Its logical service ID remained `156ceb2a-1d7e-5186-a255-7e0c0c4b7e2f`. Ground-truth window: `714c9781-4925-471a-b912-620d5c97b0a7`.

| Observation | Time, UTC |
| --- | --- |
| Stop experiment began | 12:13:20.834 |
| Same registered service observed offline | 12:13:25.180 |
| Service restarted; fault window closed | 12:13:25.669 |
| Same service ID observed online | 12:13:29.186 |
| Later persisted email telemetry sample verified | 12:17:09.644 |

Stored telemetry remained fresh during the short stop, while runtime state correctly became offline. The later telemetry sample was fresh and newer than the restart. Email was healthy after recovery. Existing demo fault flags were unchanged.

This experiment verifies runtime persistence and recovery state; it does not claim a newly implemented service-down detector or verified remediation engine.

During the live verification, persisted events increased from **87,219 to 88,304** and incidents from **1,344 to 1,374**. Example new incident: `d41f6376-59cc-5aa3-b9fc-159d83705e8a`, detector `kpi:memory_fraction:v1`. Baseline memory detectors also continued producing Kafka/OpenSearch incidents. The real-time feed delivered an `intelligence` frame at **12:17:47.855 UTC**. The retained Prometheus-backed service API returned 37 services, and Jaeger returned an available graph with 23 dependency edges. These are observations, not mock/fallback values.

The initial 60-second WebSocket sample ended before the next detector batch. A longer observation verified actual delivery without injecting a second fault. The reusable live check allows for detector warm-up.

## Tests and verification

| Check | Result |
| --- | --- |
| Dashboard regression tests, including final Docker runtime | 22 passed |
| New authentication/catalog PostgreSQL integration tests | 13 passed |
| Existing analytics, ingestion, collector, model, storage, and summary tests | 53 passed |
| Existing intelligence/case/approval API tests | 6 passed |
| Total distinct passing tests | **94** |
| TypeScript and production builds | Passed |
| Fresh and restored-backup migrations; repeat application | Passed |
| Complete packaged orchestrator import | Passed |
| Compose configuration validation | Passed |
| Live login, replay rejection, revocation, registry, restart, discovery, stop/start, telemetry, WebSocket | Passed |

The six API tests skipped in the worker-only suite were run successfully in the orchestrator environment. Legacy tests used a separate empty migrated database, with model artifacts outside the live model volume. Training, promotion, inference, and rollback were exercised there. The live instance had no active trained model before migration; none was fabricated to claim live inference.

At the final service check, all 34 running services were up; configured health checks were healthy. Browser automation reported no available browser session, so interactive visual QA was unavailable. UI state was checked with renderer tests and the served production bundle; live operations were checked through the real same-origin API/WebSocket proxy.

## Files and interfaces

- `eios/db/migrate_phase1.sql`; `eios/orchestrator/phase1_migrate.py`: schema, version guard, default application, identity backfill/triggers.
- `eios/orchestrator/auth.py`, `auth_router.py`, `middleware.py`, `main.py`, `security_router.py`: persistent authentication, roles, origin checks, sessions, and authenticated real-time access.
- `eios/orchestrator/catalog.py`, `registry_router.py`: scoped discovery, runtime instances, persistent catalog, and observation states.
- `eios/orchestrator/db.py`, `services_router.py`, `docker_router.py`: identity-aware read responses/filtering, persisted legacy workload compatibility view, and bounded Docker client calls.
- Dashboard `App.tsx`, `lib/api.ts`, `lib/session.ts`, login/onboarding/desktop/sidebar/security components, and shadcn primitives: server validation and real registry UI.
- Dashboard `serve.ts`, `vite.config.ts`, `Dockerfile`, package/lock files; `eios/compose.eios.yaml`, `eios/.dockerignore`: same-origin transport and reproducible build configuration.
- Backend/dashboard tests, `verify_phase1_live.py`, README, PROJECT, and this report/evidence file.

Important API routes:

| Route | Purpose |
| --- | --- |
| `GET /api/auth/status` | First-administrator setup status |
| `POST /api/auth/register`, `/login`, `/logout`; `GET /api/auth/me` | Accounts and validated sessions |
| `GET /api/auth/users`; `POST /api/auth/users/{id}/disable` | Administrator account management |
| `GET/POST /api/applications`; `GET/PATCH /api/applications/{id}` | Persistent registry/configuration |
| `GET/POST /api/applications/{id}/services` | Persistent service catalog/registration |
| `POST /api/applications/{id}/discovery` | Scoped, non-destructive runtime reconciliation |
| `GET /api/applications/{id}/services/{service_id}/history` | Persisted service event/incident history |
| `GET /api/events`, `/api/incidents` with `application_id` | Application-filtered legacy history |

## Compatibility and remaining limits

- Prototype browser flags no longer authenticate users. Existing open tabs need one hard refresh and a normal login. This instance retains the existing demo administrator credentials. Old accounts that existed only in a previous process's memory cannot be recovered; newly created accounts persist.
- Anonymous operational API access is intentionally removed. Cookie clients must provide the allowed origin for writes; existing explicitly configured machine-key clients remain supported.
- Additional applications currently provide persistent runtime catalogs and configuration. Their telemetry connectors and application-scoped intelligence are not activated by registration. The legacy pipeline and name-based operational views remain assigned to Astronomy Shop. Full multi-source provenance/canonical-message changes belong to Phase 2.
- Unresolved historical service bindings stay unknown. Dependency enrichment in the new catalog is not collected; the existing Jaeger topology remains available separately. Kubernetes discovery/onboarding is outside this phase.
- Existing intelligence startup DDL produced one transient deadlock during the initial restart and recovered through the existing worker restart behavior. No data loss was observed. Serializing/versioning that pre-existing bootstrap DDL remains an operational follow-up; Phase 1's new migration itself is versioned and ran with writers paused.
- Existing prototype windows outside the new registry retain Phase 0 UI limitations. They were not broadly rewritten. Password recovery/SSO, new RCA, LLM investigation, and autonomous remediation were not added.

Phase 1 is implemented and verified within those boundaries. Phase 2 has not started.
