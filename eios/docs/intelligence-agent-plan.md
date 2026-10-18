# EIOS Intelligence Agent: backend implementation plan

Status: proposal only. Application code has not been changed by this planning task.

Reviewed baseline: main at 183bcc1, Merge pull request #1 from IshhS/feat/eios-contribution. The repository was fast-forwarded from 76ecb8d after fetching origin. The only pre-existing local addition was this planning document, which was preserved.

User constraint: implement and validate the intelligence backend first. Do not modify dashboard source, styling, components, or frontend dependencies. Decide UI work later. The upstream dashboard changes were included in the requested main-branch pull; no additional UI edits are proposed.

## 1. What changed after the pull

The merged PR adds an OS-style dashboard, API-key middleware, authentication endpoints, security utilities, security Compose overlays, Docker management routes, host/system metrics, filesystem/terminal routes, workload connection routes, and an agents router.

The core telemetry/model foundation is unchanged: detect/, ingest/prom_tap.py, orchestrator/topology.py, schemas/, and db/init.sql have no changes between 76ecb8d and 183bcc1. The ML, forecasting, feature-history, and evaluation requirements from the earlier assessment still apply.

Source code, rather than the new PROJECT.md claims, defines implemented behavior. For example, the documented payment/cart spike detectors and full evaluation harness are not present in the inspected detector code; the actual detectors remain memory thresholds, CPU deviations, and order-rate drops.

## 2. Existing agent features and their limits

| Existing feature | Current behavior | Required intelligence work |
| --- | --- | --- |
| POST /api/ai/chat | Reads recent incidents, stats, and topology, then selects a reply by query keywords. Several health/score/governor statements are fixed text. | Return evidence-backed summaries of persisted findings and explicit limitations. Preserve reply, timestamp, and context_snapshot fields. |
| GET /api/cases | Groups the latest 25 incidents by service/entity on every request. Uses service-derived string IDs and fixed cause/restart templates; returns a synthetic nominal case when empty. | Produce durable case episodes with time/dependency-aware correlation, actual evidence, and stable identities. Preserve the existing response envelope. |
| GET /api/cases/{case_id} | Regenerates the same transient cases and searches them. | Retrieve stored case detail, linked incidents, evidence, and timeline. |
| GET /api/approvals | Returns an in-memory list seeded with a sample approval. | Use PostgreSQL-backed recommendations/approval records when this workflow is implemented. |
| POST /api/approvals/{approval_id}/action | Updates the in-memory approval status and inserts a plain audit row. It does not execute the proposed operation. | Keep decision recording separate from execution outcomes. Real action execution remains later orchestration work. |
| /api/docker/... | Implements real Docker inspection/stats/start/stop/restart calls through the SDK. | Reuse as an eventual orchestrator action capability; the intelligence worker should not call it autonomously. |
| /api/services and graph | Supplies live Prometheus RED metrics and Jaeger dependency information. | Share verified queries and persist timestamped telemetry for features/training. |
| Security libraries | Redaction, rate-limit, and audit utilities exist alongside middleware/configuration. | Wire needed utilities into deployed intelligence paths and validate behavior rather than infer enforcement from configuration flags. |

The agents router creates a useful API integration point. It does not yet implement learned anomaly detection, predictive models, a model registry, or a persistent feedback cycle.

## 3. Proposed architecture

Add one Python analytics worker, eios-intelligence, under eios/intelligence/. Use the existing Kafka broker and PostgreSQL. Keep analytical processing outside FastAPI request handlers.

~~~mermaid
flowchart LR
  P[Orders and Prometheus] --> I[EIOS ingest]
  I --> E[eios.events]
  I --> DB[(PostgreSQL)]
  E --> R[Existing rule detector]
  E --> A[Intelligence worker]
  R --> N[eios.incidents]
  A -->|ML incidents| N
  N -->|Evidence analysis| A
  DB --> A
  A -->|Durable features, insights and forecasts| DB
  A --> U[eios.intelligence updates]
  U --> O[Existing orchestrator]
  N --> O
  DB --> O
  O --> API[Existing agent APIs and additive intelligence APIs]
~~~

The worker gets its own Kafka consumer group. It observes events, evaluates closed feature windows, emits ML incidents using the existing Incident contract, and enriches both rule and ML incidents. Enrichment writes insight records rather than generating another incident, avoiding a self-triggered processing loop.

The orchestrator serves stored results and owns approval/policy decisions. The intelligence worker has no Docker socket or terminal capability. Kubernetes scheduling, scaling, service restarts, and general action execution remain a later orchestration feature.

## 4. Foundation work before ML

### Telemetry correctness and history

- Verify live CPU/memory units and denominator. Ingestion forwards raw values, detector comments assume one interpretation, and topology divides values by 100. Consolidate conversion once and use the same result throughout backend consumers.
- Add durable service request rate, error ratio, and p95 latency to normalized telemetry. These metrics currently exist in live topology responses, not the training event stream.
- Preserve source timestamps and distinguish stale/missing data from numeric zero. CPU utilization can exceed one core; document the verified denominator rather than arbitrarily clamp it.
- Use new canonical metric names and a feature-schema version so older PostgreSQL values retain their original meaning. Adapt legacy rule inputs explicitly; preserve existing API units expected by the dashboard.
- Combine completed-order throughput with checkout/frontend request traffic and ingestion health. Missing orders alone do not prove payment failure.
- Restore detector history after restart and suppress stale observations. Keep the rule algorithms as the baseline, with corrected units and data quality handling.

### Packaging and database setup

The current ingest Dockerfile copies schemas and ingest modules, but not security/. sink.py falls back to an identity function if security.redactor cannot import. Therefore a source-level redaction hook does not guarantee container-level redaction. Copy/wire the needed package and validate the deployed path before persisting or analyzing sensitive context.

Add additive, versioned migrations for existing PostgreSQL volumes; init.sql is first-start initialization only. Account for the existing migrate_security.sql when wiring audited intelligence operations. Do not recreate data volumes to apply schema changes.

The normal start script does not include the security overlay. Verify the chosen startup profile and API-key configuration during implementation. New routes follow the existing configured API guard; this task does not require an unrelated authentication/UI redesign.

## 5. Intelligence capabilities

### Feature windows and KPI analytics

Build shared, closed 60-second buckets on the existing 30-second evaluation cadence, with a configurable late-arrival allowance. Process each entity/bucket/model combination once. Train and infer through the same feature builder.

Service features include verified CPU/memory utilization, request rate, error ratio, p95 latency, rolling median/variability, change from a healthy baseline, memory growth slope, and freshness/coverage. Business features include completed orders per minute, checkout/payment error signals, traffic context, and throughput change. Keep order monetary values grouped by currency.

Persist feature values, schema version, bucket boundaries, entity, quality, and evidence references. Abstain when critical input is absent or stale. An empty error series is only a zero-error observation if the query/source is healthy and sufficient requests exist.

### Learned anomaly detection

Use the previously researched scikit-learn Isolation Forest as the first model. Train per-service models when enough healthy observations exist, plus a separate checkout throughput model. Sparse services remain in a visible learning state while rules continue operating.

Capture healthy runs at several load levels. A missing fault label is not sufficient proof of health. Exclude known fault/recovery intervals from healthy training; calibrate thresholds on separate validation runs. Store raw and documented normalized anomaly scores, never present them as failure probabilities.

Emit existing Incident records with versioned detector names, feature values, and evidence IDs. Explain unusual features through deviations from the reference baseline, labelled as supporting evidence rather than exact model attribution. Retain independent rule/model provenance for evaluation.

### Prediction

Start with memory growth over recent fresh observations. Forecast utilization 5 and 10 minutes ahead and time to a configured warning boundary. Compare against a persistence baseline on held-out runs. Abstain for sparse/stale/unstable history or a container restart.

Report the observation window, horizon, estimated value, method/model version, data quality, and measured forecast error. A boundary-risk estimate is not a guaranteed crash prediction. Other forecasts can follow only if the experiments demonstrate useful performance.

### Evidence and recommendations

For an incident, combine its feature window, nearby service signals, event evidence, and timestamped dependency topology. Rank candidate causes using temporal ordering, signal changes, and downstream effects. A topology edge alone cannot establish causality. State unavailable trace/log evidence explicitly.

Initial scenarios:

- adHighCpu: distinguish ordinary traffic growth from unusual resource use; recommend CPU investigation or capacity review.
- emailMemoryLeak: identify sustained growth, provide a forecast, and recommend memory-retention investigation with an operator-reviewed temporary mitigation where appropriate.
- paymentFailure: correlate elevated payment errors with checkout/order throughput changes and identify affected dependencies.
- Order decline with no traffic or unavailable ingestion: report inadequate demand/evidence rather than assert payment failure.

Use a versioned recommendation catalogue containing target, rationale, evidence, preconditions, and required approval. Remove unconditional restart recommendations from the intelligence path. Fault flags and experiment labels are never inference features.

### Model registry and feedback

Store registry metadata in PostgreSQL and worker-generated model artifacts in a persistent volume. Record model version, feature schema, entity/domain, training intervals, dependency versions, validation metrics, checksum, and candidate/active/retired state.

Initial training is an explicit worker command; training must not block API requests. Feedback records confirmed/dismissed findings and recommendation usefulness. A dismissed alert is not automatically a healthy training label.

Retraining creates a candidate, evaluated before explicit promotion. Keep a previous model for rollback. This provides a demonstrable feedback cycle with reproducible model behavior. The first version is local and does not need a paid LLM API; optional LLM explanation can follow later.

## 6. API compatibility and persistence

Reuse NormalizedEvent and Incident. Add IntelligenceInsight, Forecast, ModelVersion, and IntelligenceFeedback schemas.

Add feature_windows, model_registry, intelligence_insights, intelligence_forecasts, intelligence_feedback, and evaluation_runs tables. Reuse cases, incidents.case_id, and approvals when implementing durable case/decision workflows instead of introducing a second case store. Use UUIDs internally; existing API clients already treat IDs as strings. Preserve list responses and fields such as timeline, enrichment, recommendation, reply, timestamp, and context_snapshot.

Existing routes should read genuine analytics when available:

- POST /api/ai/chat: deterministic summaries of evidence and available intelligence, with a truthful no-data response.
- GET /api/cases and /api/cases/{case_id}: stored case episodes and evidence.
- GET /api/approvals and POST /api/approvals/{approval_id}/action: durable decisions if included in this slice; no claim that a recorded decision performed an operation.

Add backend-only routes for status, models, forecasts, insights, feedback, and evaluations under /api/intelligence. Validate them through HTTP/OpenAPI and integration tests. Preserve the current /ws incident message shape. Intelligence notifications can be added without altering existing dashboard subscribers.

Persist results and outbox notifications transactionally; publish pending notifications with retry and result-ID deduplication. Commit Kafka offsets only after durable handling. Use unique entity/window/model keys, bounded retries, and invalid-message handling. Recover recent feature state and active models on restart.

The existing frontend contains canned fallback replies when API calls fail. Because UI edits are deferred, those frontend fallbacks are a known presentation limitation; backend acceptance uses direct API responses, not those fallbacks.

## 7. Backend implementation phases

| Phase | Deliverable | Acceptance gate |
| --- | --- | --- |
| 1. Data foundation | Shared units/queries, RED ingestion, feature buckets, freshness, redactor packaging, additive migrations. | Correct and reproducible stored features; legacy service response units retained; deployed redaction verified. |
| 2. ML vertical slice | Worker, healthy capture/training, minimal registry, versioned model, ML Incident output, restart recovery. | adHighCpu produces an evidence-backed finding; normal load variation evaluated; rules remain available; replay does not duplicate results. |
| 3. Prediction and insights | Memory forecast, KPI analysis, evidence enrichment, candidate causes, recommendation catalogue. | Held-out memory runs yield measured warnings or explicit abstention; payment conclusions use telemetry, not experiment labels. |
| 4. Existing API integration | Evidence-backed chat summaries, durable cases, additive intelligence endpoints and compatible notifications. | Existing response shapes pass compatibility tests; direct API analysis works without dashboard edits. |
| 5. Evaluation and feedback | Repeated experiments, detector comparison, forecast report, feedback storage, candidate promotion/rollback. | Reproducible metrics and a demonstrated model-version transition. |

Start with Phase 1 followed by the ad CPU vertical slice. Durable approvals and real action execution can be scheduled separately if the intelligence scope needs to remain focused.

## 8. University evaluation

Use independent chronological healthy training, validation, and held-out test runs, with a gap covering the rolling feature window. Fit preprocessing only on training data. Keep fault labels, active flag values, and expected_entity out of inference.

Test normal operation, changed load, adHighCpu, moderate emailMemoryLeak variants, paymentFailure percentages, missing sources, worker restart, and replay. Record load-generator settings and fault/recovery intervals; confirm the injected fault actually took effect rather than infer it solely from a file write.

Measure precision, recall, F1, false alerts per healthy hour, and detection delay per fault episode. Match windows and affected services with documented propagation/recovery allowances. The current expectation mapping attributes payment faults to checkout, so evaluate observed payment/checkout effects rather than use that mapping blindly. Count duplicate alerts separately rather than inflate true positives.

Forecast reports include mean absolute error versus persistence, early-warning lead time where the boundary is crossed, and false forecast warnings. The current scoreboard counts labelled detections and cannot establish full precision/recall. Improvement over rules must be demonstrated by results, not promised.

## 9. Proposed changed files

- eios/intelligence/: worker, features, detectors, forecasts, insights, registry, train/evaluate commands, persistence, Dockerfile, and pinned requirements.
- eios/schemas/intelligence.py and eios/telemetry/: shared contracts, queries, and unit conversion.
- eios/db/migrations/: additive schema and migration runner integration.
- eios/ingest/prom_tap.py and Dockerfile: durable service metrics, timestamps, and redactor packaging.
- eios/detect/: explicit unit adapter, freshness, and history recovery.
- eios/orchestrator/agents_router.py, db.py, main.py, and additive intelligence modules: stored analytics, compatible APIs, and worker update consumer.
- eios/compose.eios.yaml and the security overlay as needed: worker configuration, persistent artifact volume, and matching database connection settings.
- eios/tests/ and eios/evaluation/: behavior, contract, replay, and experiment checks.

No dashboard files or frontend packages are in this implementation scope.

## 10. Verification performed during this reassessment

Git fetch and fast-forward pull succeeded. Post-pull main matches origin/main at 183bcc1; the untracked plan document was preserved. Source comparison confirms the detector contracts, raw Prometheus tap, and topology implementation are unchanged by the PR.

Python/py were unavailable to the validation environment and Docker Engine was unreachable. No backend tests or runtime ML claims are made in this review. The review did not launch Docker, install dependencies, modify runtime services, or implement the feature.

Technical references retained from the initial planning review:

- [Isolation Forest](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html).
- [Avoiding data leakage](https://scikit-learn.org/stable/common_pitfalls.html).
- [Time-ordered validation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).
- [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/).

## 11. Feasibility and frontend design proposal

This is a design proposal, not permission to modify frontend code. UI implementation remains deferred. The source baseline is still main at 183bcc1 with the separately completed startup-script fixes.

### Live feasibility evidence

The running API returned healthy service telemetry for 35 services with no degraded sources. A sample of 100 recent infrastructure events contained only cpu_ratio and memory_ratio. There are more than 34,000 persisted events across infrastructure and ecommerce, but their normality, per-service duration, freshness, and unit consistency have not been established. Historical volume alone does not prove that a model has enough trustworthy training data.

| Diagram capability | First implementation | Feasibility and dependency |
| --- | --- | --- |
| AI and data analytics engine | Autonomous worker that assembles features, evaluates KPIs/models, and writes evidence-backed insights. | High: Kafka, PostgreSQL, incidents, and live metrics already exist. |
| Predictive models | Short-horizon memory-growth forecast and estimated warning-boundary crossing. | Moderate: requires fresh chronological history and validation against a persistence baseline. |
| Anomaly detection | Per-service Isolation Forest, with existing rules as baseline/fallback. | High to implement; detection quality depends on healthy data spanning different loads and validated thresholds. |
| KPI analysis | Availability/error ratio, p95 latency, request throughput, completed-order throughput, CPU/memory. | High after RED history is persisted; low-traffic windows need explicit unavailable states. |
| Model registry | PostgreSQL metadata and versioned artifacts in a Docker volume. | High; does not require a separate MLflow deployment for the first release. |
| Inference | Evaluate fresh, closed feature windows with the active compatible model. | High; requires bounded processing, duplicate suppression, model/version checks, and restart recovery. |

The first release can run local CPU-based analytics without a GPU or paid AI API. Set a measured worker resource budget alongside the existing multi-container stack; benchmark representative training and inference rather than promise a fixed memory footprint. Start with selected ad/email/checkout/payment services before enabling every service model.

The academic claim is that the system learns a reference distribution and analyzes operational behavior. Whether that improves precision, recall, or warning lead time over existing rules must be established experimentally. No accuracy percentage is promised before evaluation.

### Minimum complete university demonstration

1. Capture explicitly healthy telemetry at multiple traffic levels and build reproducible feature windows.
2. Train a versioned anomaly model and show its active registry entry.
3. Inject adHighCpu and surface an evidence-backed ML incident alongside the rule result.
4. Inject emailMemoryLeak and measure a forecasted warning boundary against subsequent observations.
5. Inject paymentFailure and show how service errors and reduced completed orders support a candidate diagnosis.
6. Record operator feedback and demonstrate a validated candidate model promotion or rollback.
7. Present held-out metrics comparing rules and ML, including false alerts during healthy traffic.

There is no need to demonstrate autonomous restarts or Kubernetes scaling to complete this Intelligence Agent block. Those are responsibilities of the separate orchestration block in the full system diagram.

### Proposed frontend placement

Add an Intelligence launcher and an Intelligence Center window inside the current EIOSDesktop window system when UI work is authorized. Reuse existing close, minimize, maximize, taskbar, and visual conventions. The existing AI Assistant can explain the same persisted findings through compatible backend responses.

The proposed window has a service filter, time-range filter, agent state, active model version, and last successful analysis timestamp. It uses five views:

| View | What a user sees | Primary interaction |
| --- | --- | --- |
| Overview | Current operational anomalies, forecast warnings, key KPI breaches, agent/data readiness. | Open the highest-priority finding or affected service. |
| Anomalies | Service, detection time, observed change, detector, anomaly score, operational severity, and lifecycle state. | Open evidence detail; confirm or dismiss a finding. |
| Predictions | Observed memory history, forecast projection, horizon, warning boundary, and data-quality limitations. | Choose a service and inspect projected versus observed values. |
| KPIs | Request/error rate, p95 latency, order throughput, CPU/memory, reference baseline, and trend. | Inspect metric history and the applicable configured objective. |
| Models | Model version, target service, feature schema, healthy data window, validation results, last inference, and candidate/active state. | Inspect training jobs and propose model promotion under backend policy. |

Anomaly detail includes the actual triggering feature values, healthy reference range, analysis interval, evidence IDs/trace links where available, potentially affected services, and proposed next steps. Explain anomaly score as unusualness, and determine severity separately from operational impact. Model-score values must not be labelled as failure probabilities.

Prediction charts distinguish historical observations from projections and display units and timestamps. Show an uncertainty band only if that band has been estimated and validated; otherwise describe measured forecast error and data limitations. Display learning, no data, stale data, or source unavailable states rather than invent normal health values.

Buttons in the first intelligence UI are View evidence, Confirm/Dismiss, and recommendation feedback. Actions that change containers/resources belong to the later approval/execution workflow. Existing synthetic AI fallback messages should be removed when that frontend integration phase is authorized; until then, direct API responses are the acceptance surface.

Conceptual layout:

~~~text
Intelligence Center                 Agent: Ready | Last analysis: timestamp
Service: All services               Time range: 1 hour
Overview | Anomalies | Predictions | KPIs | Models

Active anomalies      Forecast warnings      KPI breaches      Model state

Findings list                           Selected finding
Service / signal / severity             Observed value and reference range
Observed trend                          Evidence and affected services
Prediction warnings                     Candidate cause and proposed action
                                        Confirm / Dismiss / Feedback
~~~

This layout contains no fabricated live values; all cards and details are backed by the intelligence API.

### Execution and review points

Build and review the backend first. Phase 1 validates telemetry/windows. Phase 2 completes the ad CPU model-to-API slice. Phase 3 adds memory forecasts and payment/KPI evidence. Phase 4 makes existing agent routes truthful and exposes typed intelligence APIs. Phase 5 evaluates and records feedback. The frontend integration is a subsequent, separately agreed phase using the design above.

Schedule the work after the submission deadline and available team capacity are known. Data capture/evaluation must receive explicit time in the schedule, not be treated as an automatic consequence of writing a detector.

## Backend implementation status

The backend worker, canonical telemetry collection, durable outbox, additive migrations, model registry and lifecycle CLI, KPI findings, memory forecasts, dependency evidence, feedback, persistent cases/approvals, and compatible agent APIs are implemented. The model includes an explicit CPU range guard because Isolation Forest cannot estimate distance beyond its outermost splits. Results expose the guard separately from the forest score.

The disposable-database test suite verifies analytical behavior and pipeline correctness. Representative healthy training, active model promotion, and real fault/forecast evaluation remain operational steps requiring collected data; no production model or accuracy claim is fabricated. See [the runbook](./intelligence-agent-runbook.md) for startup, training, evaluation, and API commands.

## Frontend implementation update

Following the user's frontend approval, intelligence views now live inside the existing **Reports** launcher rather than a separate Intelligence Center. The window follows the existing EIOS theme, supports minimize/maximize/close, and includes Overview, Anomalies & Findings, Predictions, KPIs, and Models tabs. Service and finding-period filters, observed trend plots, evidence details, and Confirm/Dismiss feedback use backend results. Models are read-only in this release. Learning, stale, missing, unavailable, and abstained states remain visible. Existing sidebar artwork and the other application windows are preserved.
