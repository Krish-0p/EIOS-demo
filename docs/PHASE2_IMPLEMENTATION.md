# Phase 2 implementation report

Date: 18 October 2026. Scope: unified telemetry identity, bounded evidence retrieval, and truthful source observations. Phase 3 has not started.

## Current telemetry flow and preserved behavior

The original pipeline remains in use:

- Checkout produces Protobuf `OrderResult` messages on Kafka `orders`. The existing independent `eios-ingest` consumer decodes them, persists normalized events and an outbox entry transactionally, then publishes `eios.events`.
- The existing Prometheus tap polls container CPU/memory and server-span RED metrics. Source samples retain their real timestamps; missing/stale samples are not synthesized. Legacy percentage fields and canonical cores/fraction/millisecond fields retain their existing units.
- Existing rule detectors consume `eios.events`. Intelligence consumes events/incidents, builds closed feature windows, persists findings/forecasts/cases, and publishes through the existing outbox.
- The existing orchestrator service APIs and Jaeger dependency graph remain available. The shared query layer now handles Prometheus transport/vector parsing and Jaeger dependency transport for their existing callers.
- The existing OpenTelemetry Collector already exports logs into OpenSearch `otel-logs-*`. Phase 2 queries that deployment; it does not install another log pipeline or duplicate its entire warehouse.

No monitored application business source, detector scoring formula, feature units, model algorithm, case identity, approval relationship, or PostgreSQL/model volume was rewritten.

## Identity and normalized contracts

`NormalizedEvent` retains its original fields and adds optional wire fields: `application_id`, `service_id`, `service_name`, `environment`, `source_id`, `signal_type`, and `source_observed_at`. The existing schema version remains backward compatible because these fields are additive. Newly emitted Kafka/Prometheus records resolve these fields before database insertion and Kafka publication. Published Kafka keys include application/service identity. Pending pre-upgrade outbox messages receive the identities of their already-persisted events before publication, retaining their event/message IDs.

Source kinds are `kafka`, `prometheus`, `jaeger`, and `opensearch`; signal types distinguish `business_event`, `metric`, `source_health`, `trace`, and `log`. Read envelopes add `timestamp`, `source_type`, dynamic freshness/age, and an explicit resolved/unresolved identity state. Freshness is computed from the source clock rather than refreshed by an HTTP read.

Logical service IDs remain application-scoped UUIDs. A container sample from the existing shared Docker collector is routed through the persistent runtime-instance owner. Consequently new `eios-orchestrator`/`eios-dashboard` metrics belong to the EIOS Platform application. Small derived Prometheus bindings describe this routing and inherit the real collector's connection observations. They do not launch duplicate pollers. Historical records retain their previous assignment.

Other applications can bind Prometheus, Jaeger, and OpenSearch sources through the administrator API. A shared endpoint requires a common exact selector key with different values on every participating application binding; an unscoped legacy endpoint cannot be silently shared by name. Reserved span-kind/status labels cannot masquerade as application selectors. Source endpoint/scope becomes immutable once data exists. Trace queries additionally check service and matching tags in returned spans; log queries use exact service and configured term filters.

The existing name-keyed rule/feature/model pipeline remains scoped to Astronomy Shop. Explicit guards prevent another application's records from entering that state. This phase provides isolated telemetry/evidence for other applications; it does not claim application-scoped model execution.

Kafka IDs now incorporate source and order identity as well as source coordinates. Topic recreation can reuse offsets, so offset-only UUIDs could collide with historical orders. Exact legacy order replay retains its existing UUID; a different order at a reused offset gets a distinct ID. Existing historical IDs are unchanged.

## Database and migration

New tables:

- `telemetry_sources`: application-scoped binding, kind, endpoint, exact scope, activation, observation timestamps/error, and freshness allowance.
- `telemetry_evidence`: bounded trace/log snapshots with application/service/environment/source identity, timestamps, source reference, trace ID, and evidence payload.

The `events` table gains additive source/environment/name/signal/source-clock metadata and an application/signal/time index. Composite foreign keys prevent source/service references from belonging to a different application. A metadata trigger supports legacy producers while preserving original fields.

The `phase2-v1` migration runs transactionally under an advisory lock. It creates the four default Astronomy Shop bindings and backfills event metadata. The existing intelligence bootstrap DDL is now versioned as `intelligence-v1` under its existing lock, avoiding repeated startup DDL against active writers. The initial version stamp was applied with EIOS writers paused.

A consistent backup was first restored to a disposable database. The rehearsal preserved 94,634 event IDs and every original event value, plus all other historical keys. The live migration then ran with EIOS ingestion/detection/intelligence/API paused and a fresh backup retained. It took **72.59 seconds** including preservation checks.

| Existing live data | Rows preserved |
| --- | ---: |
| Events | 96,826 |
| Incidents | 1,612 |
| Cases | 68 |
| Approvals | 0 |
| Fault windows | 23 |
| Intelligence findings | 1,388 |
| Forecasts | 24,452 |
| Feature windows | 12,328 |
| Model registry / evaluations | 0 / 0 |

Every primary/composite history key matched before/after. A separate digest of each event's original source, timestamps, entity, metrics, attributes, trace ID, and raw reference also matched. Exact hashes are in the evidence JSON. Nonempty approval preservation remains covered by the Phase 1 integration tests.

Backups are retained under the ignored workspace `.phase2/` directory (`before-phase2.dump`, `before-phase2-live.dump`). Existing target files were backed up before synchronization. The live database continues to use `opentelemetry-demo_eios-pgdata`; the existing model volume remains in place. No volume was removed or recreated.

## Evidence retrieval and source health

The trace API returns bounded Jaeger span evidence with trace/span IDs, operation, original microsecond duration, selected status tags, parent references, timestamp, and exact source reference. The log API returns bounded OpenSearch excerpts with timestamp, severity, service, document coordinates, and trace reference where present. Password/token/card patterns and email addresses are redacted; message excerpts are capped at 2,048 characters. Full upstream traces/logs remain in their original stores.

Evidence queries permit at most a 60-minute window, 50 returned records (trace fetches capped at 20), an end time within the last day, an 8-second request timeout, and a 3 MB response limit. Failed/incomplete queries retain cached evidence with an explicit unavailable reason and cached marker. Reads do not turn old samples fresh.

Source observations distinguish:

- **connected**: recent successful observation and recent source data/eligible broker observation.
- **disconnected**: a recent source query/check failed; the last data timestamp is still exposed independently.
- **stale**: observations aged beyond 90 seconds or source data exceeded the configured allowance (default 240 seconds).
- **unknown**: disabled, never checked, or reachable without observed source data.

Kafka watermark requests establish real broker/consumer progress. Idle consumers use their committed offset when no current fetch position exists. A caught-up broker observation can establish source freshness with zero orders; original business-event timestamps remain independently visible. The API reports `freshness_basis` explicitly. A transient watermark failure during recovery was reported and cleared by the next successful check; orders continued to persist.

Prometheus source observations come from its actual collector queries, including partial failures. Jaeger/OpenSearch are probed independently, using bounded real data queries. Jaeger requires a service parameter; its probe samples up to three registered service names rather than treating a service-list response as fresh trace evidence. Failures in one source do not terminate the other collectors.

The Application Registry's shadcn source panel shows these observations, timestamps, failures, loading/unavailable states, and cached age. Configuration fields alone do not claim activation. Older prototype views outside this panel retain their separately documented UI limitations.

## Live acceptance evidence

Before verification, the running demo had `paymentUnreachable=on` without a new Phase 2 fault window. Persisted Kafka business events were last dated 12 October. Checkout also exhibited its documented producer startup failure. The existing `docker restart checkout` recovery was used; no business code was edited. The existing payment fault was suspended only during verification and restored to **on** afterward. The existing load generator's 20-user run was preserved.

Acceptance ran from **13:23:17.303344 to 13:24:55.275426 UTC**. Requests traversed the live dashboard proxy using temporary, database-validated administrator sessions; those sessions were revoked afterward.

| Check | Evidence |
| --- | --- |
| Kafka business events | Real checkout orders at offsets 718 through 724, including event `b83efe42-f1cd-5263-b451-4340d8490016`; persisted and published identities matched |
| Prometheus | Real server/container metrics; recovered checkout sample `5488d302-16ed-4d73-96e6-bd8770596b4f` at 13:24:51.771055 UTC |
| Jaeger | Three real `ad` span records per query, persisted with source references |
| OpenSearch | Three real `recommendation` log records per query, persisted with source references |
| Application mapping | EIOS Platform returned its own orchestrator/dashboard metrics; Astronomy Shop queries remained scoped |
| Legacy API behavior | Service health, dependency graph, and intelligence status returned successfully |
| Intelligence | Worker alive; real feature windows/findings continued; status correctly remained `learning` with no active model |

Exactly one telemetry source outage was injected:

| UTC | Observation |
| --- | --- |
| 13:23:45.315680 | Prometheus stop requested |
| 13:23:46.501954 | Container stopped |
| 13:24:21.758665 | Collector persisted the failed source observation; API returned `disconnected` |
| 13:24:30.684199 | Outage check passed; Kafka, Jaeger, and OpenSearch were connected |
| 13:24:31.166545 | Prometheus restarted |
| 13:24:53.766908 | Successful metric observation persisted; source returned `connected` |
| 13:24:55.275426 | Verification finished and original payment fault restored |

During the outage check, persisted events increased from 98,551 to 98,557 while Prometheus was stopped. Business events/source observations continued. Across baseline and recovery, events increased to 98,641, incidents from 1,653 to 1,663, findings from 1,429 to 1,439, and feature windows from 12,699 to 12,731. The existing rule detector produced `rule:memory_above_92`; intelligence produced `kpi:latency_p95_ms:v1`. These are observed outputs, not claims that the short telemetry outage caused those anomalies.

The final completeness capture observed 913 metrics, nine business events, and 12 source-health events since the experiment start, with **zero missing application/service/environment/source/name/source-clock fields**. Six log and six trace evidence snapshots had persisted, and every configured source was connected. Later live counts can increase as traffic continues.

## Tests and verification

**116 distinct tests passed:**

- 17 Phase 2 integration tests: migration replay/preservation, identity mismatch rejection, equal names across applications, runtime-owner mapping, event UUID isolation, legacy Kafka replay/recreated offsets, source states, ambiguous/disjoint binding rules, reserved selectors, bounded/redacted evidence, cached outage behavior, Jaeger probe correctness, and legacy worker isolation.
- 55 collector/intelligence/model/persistence tests, including the new idle-offset and pending legacy outbox checks.
- Six existing API compatibility tests, run separately against an empty disposable database.
- 13 existing Phase 1 authentication/session/catalog tests.
- 25 dashboard tests, including loading, failures, source disconnection, stale cached observations, and existing session/discovery behavior.

Production Python images imported successfully. The Bun/TypeScript/Vite production build passed and the updated dashboard is running. The existing bundle-size warning remains. Local Windows Vite execution hit a sandbox directory-read restriction; the production Docker build completed successfully. Some early regression attempts exposed incomplete test-image dependencies/layout and one reused test-backend fixture; these were corrected before the successful final runs.

Interactive browser automation was unavailable in this environment. UI verification used component tests, the production build, HTTP availability, and authenticated API calls through the real dashboard proxy; no manual browser validation is claimed.

## Changed files and interfaces

- `eios/telemetry/`: shared identity, queries, source configuration/probes, health, evidence, migration, and reproducible tests/acceptance helpers.
- `eios/db/migrate_phase2.sql`, `eios/schemas/events.py`: additive schema/contract.
- `eios/ingest/{sink,kafka_tap,prom_tap}.py`: normalization before publication, source references/health, scoped polling/routing, compatible Kafka identity/replay, pending legacy delivery enrichment.
- `eios/orchestrator/{main,telemetry_router,topology}.py`: migration, background observations, new scoped APIs, shared query transport.
- `eios/intelligence/{migrate,evidence,features,main,store}.py`, `eios/detect/rules.py`: versioned bootstrap, shared dependencies, explicit application isolation, and preservation of enriched input.
- Python Dockerfiles and `eios/compose.eios.yaml`: package the shared module and wait for migration-ready API startup using the existing volumes.
- Dashboard API client, `ApplicationOnboardingModal`, `TelemetrySourceStatus`, tests, README, PROJECT, and this report/evidence.

New API routes:

| Route | Purpose |
| --- | --- |
| `GET /api/applications/{id}/telemetry/sources` | Current source observations and dynamic freshness |
| `POST /api/applications/{id}/telemetry/sources` | Administrator source activation/settings |
| `GET /api/applications/{id}/telemetry/records` | Persisted normalized records with service/signal/time filters |
| `GET /api/applications/{id}/telemetry/services/{service_id}/evidence/{trace|log}` | Bounded evidence fetch and cached availability |

## Remaining limits

- Additional Kafka topic/schema consumers are not implemented. The working `orders` consumer remains the supported business connector.
- The existing unscoped shared legacy backend cannot safely distinguish equal service names from another application without instrumentation-level selectors. Ambiguous activation is rejected rather than guessing. Separate endpoints or provably disjoint selectors are required.
- Non-demo telemetry is stored and queried independently; full application-scoped detector/model keys, topology, correlation, and RCA are later work. Existing default application detection remains active.
- Source probes are bounded samples, not exhaustive per-service completeness checks. Historical binding ambiguity remains explicitly unresolved where appropriate. A failed probe can coexist with recently received data; both observations are exposed.
- Trace/log snapshots are fetched on demand. Per-query bounds are enforced; automatic age-based snapshot retention/archival is not implemented. Full-fidelity raw warehouses remain upstream.
- Source binding management is currently an administrator API; the affected UI displays source status. Saving Phase 1 application endpoint text alone does not activate a connector.
- The user's original `paymentUnreachable=on` configuration is restored. Successful business throughput will again be impaired until that existing fault is disabled deliberately.
- No Phase 3 topology redesign, new RCA, LLM investigation, or autonomous remediation was implemented.
