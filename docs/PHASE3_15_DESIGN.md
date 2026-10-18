# Phases 3–15 implementation design

The user authorized implementation through Phase 15 and explicitly requested no tests, builds, live checks, or fault experiments. Source reading is necessary for integration. All delivered functionality remains unverified until manual acceptance.

## Compatibility and storage

Use an additive `workflow-v1` migration after existing migrations. Keep legacy events, incidents, cases, findings, approvals, detector IDs, and volumes. New operational anomalies reference legacy records; correlated incidents use their own IDs and link a legacy case for approval compatibility. No upstream demo business logic changes.

## Contracts and responsibilities

- Phase 3: persisted topology snapshots contain application/service UUIDs, runtime instances, metric values, metric timestamps, health state/reason/score, source availability, and dependency edges with provenance. Registered nodes remain visible when stopped. Fresh runtime-down observations imply OFFLINE; old observations imply STALE/UNKNOWN, never confirmed offline. Dependencies require scoped, retrieved Jaeger evidence or registered declared dependencies.
- Phase 4: Operations workspace selects an application; shows persisted topology, measured counts, anomalies, incidents, source freshness, and state changes. Authenticated WebSocket invalidations refresh snapshots; bounded polling is fallback. API failures show unavailable.
- Phase 5: preserve static rules and existing ML inference. Normalize their persisted outputs into one anomaly contract; add rolling mean/stddev, EWMA and Z-score baselines on fresh, sufficiently populated history. Suppress startup/history/telemetry-loss guesses. Health is 100 minus explicit bounded error, latency, CPU, and memory penalties; unknown data yields no score. Durable fingerprint/cooldown prevents repeated alerts across restarts.
- Phase 6: application-scoped correlation uses five-minute temporal proximity plus same service, trace/signature or dependency adjacency. Preserve all anomaly IDs and matching reasons; durable timeline records legal transitions. One writer per application prevents concurrent duplicate groups.
- Phase 7: score temporal precedence, local severity/errors/resources, trace failure concentration and downstream propagation. Store every component and cited evidence. Ranking scores are not calibrated probabilities. Abstain without direct evidence; experimental ground truth never enters RCA.
- Phase 8: bounded read-only evidence tools supply an optional configured model provider. Strict structured output must cite tool-returned evidence IDs. Timeouts/failures persist an unavailable result, never block incident handling. No shell/filesystem/runtime tools.
- Phases 9–10: fixed action catalog, deterministic proposals, recorded policy, administrator approval for service changes, operator execution. Docker adapter resolves registered UUIDs and rechecks scope/container ownership at execution. Durable execution claim prevents duplicate retries; uncertain interrupted commands require a human decision.
- Phase 11: capture pre-action topology, collect fresh post-action samples during a configurable observation window, require consecutive healthy distinct observations with traffic and error/latency thresholds, and persist comparison/outcome. Only RECOVERED transitions to RESOLVED. Missing data is INCONCLUSIVE.
- Phase 12: durable experiment intents with exclusive fault lock, bounded duration, explicit prior state, fault-window linkage, and restart-resumable cleanup. Fault changes and DB writes use a compensating saga because file/Docker operations cannot share a PostgreSQL transaction. Existing load generator is observed by default; requested profiles require an explicitly configured Locust endpoint.
- Phase 13: immutable evaluations record experiment IDs, observation period, definitions, exact input record IDs, and measured/calculated metric labels. Ground-truth service membership and annotation determine TP/FP/FN; no detection outside a fault is automatically labelled false. Unlabelled values stay unknown. Export JSON/CSV. Compare detector categories using actual normalized live outputs.
- Phase 14: backend role enforcement, real rate limiting, disabled-by-default terminal/filesystem, explicit machine permissions, secure session/WebSocket handling, redaction, and hash-chained append-only governance audit. Public password-reset requests must never return a working reset secret; use operator-delivered recovery tokens until email is configured.
- Phase 15: retain desktop, graph and explorer; add a coherent shadcn Operations workspace, incident detail, experiment/evaluation views, explicit loading/error/empty states, readiness report and manual demo checklist.

## Planned files

Create `eios/db/migrate_workflow.sql`, `eios/orchestrator/workflow_{migrate,store,topology,analysis,investigation,runtime,experiments,evaluation,router,worker}.py`, dashboard Operations workspace, and phase reports. Integrate orchestrator startup, middleware, auth, service APIs, existing desktop/graph/status components, README and PROJECT.

## Manual acceptance

On a preserved database volume: apply migrations; sign in with each role; select Astronomy Shop; discover real services; stop/restart Payment; observe offline persistence and topology recovery; inject one fault; inspect anomaly provenance, grouping, RCA, optional AI evidence citations, proposal, rejection/approval, controlled execution, sustained verification, experiment cleanup, evaluation denominators and audit history. Also exercise source loss, missing models/provider, process restart, expired approval, repeated execute, wrong-application targets and permission denials.
