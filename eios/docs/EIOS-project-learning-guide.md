# EIOS project learning guide

Repository implementation reviewed for this guide: 12 October 2026.

This document explains the project, its technology, data flow, analytical methods, frontend, evaluation, and production considerations. It describes the implementation available in this workspace. Features shown in the proposed architecture are distinguished from features implemented in the application. Live model readiness and service health must be checked in the running system.

## 1. Project purpose

EIOS stands for Enterprise Intelligent Operating System in the application interface. It is an application for observing and investigating a distributed software system. It collects operational measurements and business events, identifies unusual behavior, stores findings, and presents evidence and recommended investigations to an operator.

EIOS is implemented as containerized backend services and a web dashboard. Its desktop, terminal, boot screen, windows, and taskbar are interface metaphors. It does not implement an operating-system kernel, hardware scheduling, or a replacement for Windows or Linux.

The problem addressed is that a failure in a microservice application can appear in several places at once. A payment problem can affect checkout completion; a memory leak can first appear as increasing resource use and later as errors or restarts. Separate metric charts and log records do not automatically explain the relationship. EIOS assembles a common event history, applies rules and analytics, and keeps the evidence with each finding.

The intended users are developers, operations engineers, site reliability engineers, and administrators responsible for services. The university demonstration uses a controlled application and injected faults to make behavior observable and repeatable.

## 2. The application being monitored

The monitored application is the OpenTelemetry Astronomy Shop demo. It contains cooperating services such as the storefront, product catalog, cart, checkout, payment, shipping, email, and supporting services.

A typical customer operation involves several calls. The frontend requests product information, a cart retains selected items, and checkout coordinates operations needed to complete an order. A checkout outcome also produces an order message that other services can consume.

The demo supplies instrumented services, a load generator, infrastructure, and feature flags for controlled failures. These are upstream OpenTelemetry project components. EIOS supplies the additional normalization, incident detection, intelligence worker, database records, APIs, operator interface, and related integration.

The two main workspace directories are `opentelemetry-demo/` and `eios/`. The EIOS Compose file is applied after the demo Compose files. This lets the project attach its services without requiring source changes to the upstream application.

The dashboard itself is a separate frontend from the Astronomy Shop storefront. Customers would use the storefront; an operator would use EIOS.

## 3. Main concepts to understand

A microservice is a separately running component responsible for part of an application. Services communicate through network calls or messages. Independent deployment and scaling are useful, but a request can fail because of a dependency rather than the first service showing an error.

Telemetry is information emitted by software about its behavior. Observability is the ability to use those outputs to understand the internal condition of a system. Monitoring usually checks known measurements and conditions; investigation uses measurements and context to understand an unexpected condition.

A metric is a numerical measurement over time, such as CPU use, request count, or duration. A log is an event record, usually with a timestamp and contextual fields. A trace represents a request or operation across components. A span represents one timed operation inside a trace. Trace identifiers allow related activity to be linked across service boundaries.

An application event, such as an order being completed, has business meaning. It is different from a sampled CPU measurement, although EIOS normalizes both into a common envelope.

A detector applies a rule or model to observations. An incident records a detected condition. An insight adds interpretation, baseline comparisons, and recommendations. A case groups related investigation records. An approval records an operator's decision about a proposed action.

An anomaly is an observation that differs from a learned or expected pattern. It does not necessarily mean a failure. A promotion, load test, batch job, or new release can create unusual but legitimate behavior.

Correlation means observations vary together or occur near each other. Causation means one produces another. EIOS dependency and time-window evidence supports candidate causes; it does not prove a root cause.

These signal definitions follow the [OpenTelemetry signals documentation](https://opentelemetry.io/docs/concepts/signals/).

## 4. Technology stack and responsibilities

Python runs the EIOS ingestion, rule detection, Intelligence Agent, and API services. It is used for data processing, service integration, and numerical analysis.

FastAPI exposes HTTP endpoints. Pydantic validates structured request and event data. Uvicorn runs the API application. HTTPX is used for calls to services such as Prometheus and Jaeger.

Apache Kafka carries asynchronous messages. The demo's `orders` topic provides business events. EIOS uses `eios.events` for normalized events, `eios.incidents` for incidents, and `eios.intelligence` for intelligence notifications. The Python client is `confluent-kafka`.

PostgreSQL stores durable records. Psycopg provides the Python database interface. JSONB columns hold flexible measurements and structured context, while ordinary columns support identities, timestamps, service filters, and indexes.

OpenTelemetry instruments the monitored application and collects telemetry. The Collector receives and processes telemetry and routes it to observability backends. OpenTelemetry is not the machine-learning algorithm and is not itself the EIOS incident database.

Prometheus holds numerical time series and evaluates PromQL queries. EIOS uses its HTTP API to retrieve resource measurements and request-related statistics.

Jaeger provides distributed tracing and dependency information. EIOS uses dependency information to relate services and provides access to traces for investigation. Grafana is an additional observability interface supplied by the demo stack. The custom EIOS Reports charts are drawn by EIOS rather than embedded Grafana dashboards.

The demo also contains infrastructure such as OpenSearch. The Intelligence Agent's main analytical inputs are normalized events, Prometheus measurements, and dependency evidence. The presence of a log backend in the stack does not mean the agent currently performs complete log-content analysis.

Scikit-learn provides Isolation Forest. NumPy supports numerical arrays and calculations. Joblib stores and loads locally generated model artifacts. Related scientific-library versions are tracked because model loading must use a compatible environment.

React and TypeScript implement the EIOS frontend. Vite builds it. Tailwind CSS supplies utility styling, with existing shadcn-style components and Radix primitives for components such as tabs. Lucide supplies interface icons. Bun is used in the frontend workflow and container serving setup.

Docker packages each service. Docker Compose defines the local stack, service networking, environment configuration, volumes, and startup dependencies. PowerShell provides the local startup and backend-test scripts.

The backend also includes Docker SDK, Kubernetes client, and psutil dependencies for operational interfaces. A dependency being installed does not establish that a complete Kubernetes automation system is deployed.

## 5. How the architecture maps to implementation

The application environment is the Astronomy Shop demo. The collection layer consists of its telemetry infrastructure plus the EIOS Prometheus and Kafka taps.

`eios-ingest` turns source data into normalized events, stores it, and publishes it for downstream consumption.

`eios-detect` performs baseline rule detection. `eios-intelligence` performs feature-window analysis, KPI checks, forecasting, and inference with active models. Keeping the rule detector provides a useful reference when evaluating the additional value of machine learning.

`eios-postgres` stores the project history, findings, models, cases, feedback, and delivery state.

`eios-orchestrator` is the FastAPI service. It exposes data and operational endpoints, connects the UI to backend capabilities, and handles notification delivery to connected clients. The name does not mean all autonomous policy execution in the architecture has been completed.

`eios-dashboard` serves the web application. The Reports window exposes the Intelligence Agent's stored results.

The architecture's Output Agent corresponds mainly to dashboard and API presentation responsibilities in this implementation. It is not a separately deployed reasoning model. Likewise, the proposed investigation, correlation, feedback, and orchestration boxes are logical responsibilities; not every box is an independent running service.

The feedback loop currently stores operator feedback and supports explicit retraining and model promotion. Automatic continuous retraining, automatic resource allocation, full incident resolution workflows, and guaranteed self-healing are future extensions.

## 6. End-to-end telemetry pipeline

The telemetry path begins when the monitored application performs work. Instrumentation emits request traces and other measurements. Infrastructure collection provides resource measurements. The observability stack makes the relevant numerical data queryable through Prometheus and trace data available through Jaeger.

The Prometheus tap in `eios/ingest/prom_tap.py` polls on a configured interval, normally 30 seconds. It retrieves CPU, memory, and request-related measurements. It standardizes units and preserves the source observation time.

The Kafka tap in `eios/ingest/kafka_tap.py` consumes `orders` using an EIOS consumer group. It decodes the demo's Protobuf order messages and converts the relevant information into normalized events.

The sink validates and redacts applicable data, then writes the event and its intended Kafka publication in a database transaction. A publisher delivers the queued message to `eios.events` and records successful delivery. Failed delivery can be retried.

The rule detector consumes normalized events and evaluates its conditions. The intelligence worker also consumes the stream with its own group, maintains durable input history, and periodically builds closed feature windows from that history.

The intelligence worker evaluates KPIs, produces memory forecasts where data permits, and runs the active service model where one exists. A finding can produce a persisted incident, insight, case update, and notification intent.

The API reads stored results for the dashboard. Notification messages can inform connected clients that new information exists. Reports retrieves its results through HTTP polling, every 30 seconds while open.

This is near-real-time processing. Collection, window closure, allowed lateness, analysis scheduling, and frontend refresh all add latency. A changing graph and a persisted intelligence finding can therefore update at different times.

## 7. Kafka concepts used by the project

A topic is a named message stream. A partition is an ordered portion of a topic. An offset identifies a message's position within a partition. A consumer group tracks consumption independently of other groups.

EIOS consumes orders using its own group, so its reading does not take orders away from the demo's accounting or fraud-detection consumers. Within one group, partition assignment determines which consumer processes which messages.

Messages decouple producers and consumers. Checkout can publish an event without directly calling each analytical component. Consumers can process at their own pace, within the capacity and retention limits of the message system.

Consumer lag is the distance between the producer's latest offsets and a consumer's progress. A process can be running while its data is delayed. This is why process health and data freshness are separate concepts.

EIOS uses stable identities and conflict handling to avoid creating duplicate records when messages are replayed. Order event identity is derived from Kafka coordinates. The durable outbox can publish a message more than once after a retry or crash; downstream handling must remain idempotent.

The implementation should be described as at-least-once delivery with deduplication, rather than universally exactly-once processing. The older baseline detector and the newer intelligence path should also be evaluated separately for their failure behavior.

## 8. Normalized events and data contracts

`NormalizedEvent` is defined in `eios/schemas/events.py`. Its main concepts are an event ID, schema version, domain, source, observation time, ingestion time, entity, numerical metrics, contextual attributes, and optional trace or raw-data references.

`observed_at` records when the source observation occurred. `ingested_at` records when EIOS received it. An old Kafka message arriving now must not be counted as current traffic solely because its ingestion time is recent.

The entity identifies what the measurement belongs to. Its service name allows measurements from different sources to be grouped around the same operational component.

The `metrics` object holds numerical features. The `attributes` object holds descriptive context. Keeping context separate from features helps prevent accidental use of identifiers, injected-fault labels, or other inappropriate fields as training input.

The domain contract supports infrastructure, e-commerce, and attack-oriented data. The main demonstrated ingestion paths are infrastructure measurements and order events. A complete attack-data collection and detection pipeline should not be inferred simply from the presence of an attack domain in the schema.

`Incident`, defined in `eios/schemas/incidents.py`, includes the entity, detector, time window, score, severity, features, evidence identifiers, labels, status, and optional case association. The same incident contract lets rule and model findings be compared and consumed by common APIs.

Intelligence-specific schemas add insights, forecasts, model versions, recommendations, and feedback. Schema and feature versions matter because a model trained with one feature definition must not silently consume a different definition later.

## 9. Database organization

The `events` table holds normalized raw events. `fault_windows` records controlled failures used for evaluation. `incidents` stores detected conditions. `cases` stores investigation groups, timelines, and enrichment. `approvals` stores proposed actions and operator decisions. `audit_log` stores operational actions.

The intelligence migration adds `feature_windows`, `model_registry`, `intelligence_insights`, `intelligence_forecasts`, `intelligence_feedback`, `evaluation_runs`, `intelligence_outbox`, `intelligence_state`, and `intelligence_rejections`.

Feature windows are reusable analytical observations. Model registry rows describe versions and validation metadata. Model artifacts themselves live in the model volume. Intelligence state holds checkpoints and worker status. Rejections record invalid-message coordinates and reasons without retaining unnecessary sensitive raw content.

PostgreSQL transactions keep related changes together. For example, saving a finding and its delivery intent together avoids a state where the database has committed a result but notification delivery has no retry record.

Unique IDs and database constraints support deduplication. Indexes on service, domain, and time make common dashboard and training queries practical. JSONB supports flexible evidence, but it does not remove the need for schema validation or query design.

The local `eios-pgdata` volume retains database data across container recreation. The `eios-models` volume retains model artifacts. Persistent volumes are not backups: deletion, corruption, or host failure can still lose their contents.

The intelligence migration is additive and repeatable, with a database lock to coordinate startup migration attempts. The original initialization SQL runs when PostgreSQL initializes a new data directory; changing that file alone does not migrate an existing database volume.

## 10. Feature windows, units, and missing data

The canonical feature version is `2.0`. Features include `cpu_cores`, `memory_fraction`, `request_rate_per_sec`, `error_rate_per_sec`, `error_fraction`, `latency_p95_ms`, and `orders_per_min`.

`cpu_cores = 1.0` means the equivalent use of one CPU core. This is different from a percentage of the entire machine's capacity. For example, 0.5 cores means half a core's worth of usage.

`memory_fraction = 0.8` means 80% of the relevant container memory limit. A fraction must be multiplied by 100 for percentage display. Error fraction has the same percentage conversion, with a different denominator: requests rather than memory capacity.

The current collection integration applies a 0.01 scale to Docker CPU and memory source values because their observed source units are percentages. Unit behavior must be verified when replacing the collector or metric source. Metric names alone are insufficient evidence of units.

The worker constructs one-minute windows in UTC and closes them after a 90-second lateness allowance. Late-arriving events remain in raw history but do not rewrite sealed model windows. This stabilizes training and inference inputs at the cost of excluding very late data from those windows.

Repeated polling of the same source sample does not count as extra independent coverage. Window quality records contributing observations, metric timestamps, and missing features. Metrics older than the freshness allowance are not treated as reliable current inference input; the intelligence path normally uses a 240-second allowance.

Missing values are not automatically zero. Missing requests can indicate unavailable telemetry. Missing orders can mean consumer lag. Zero order throughput is accepted only with sufficient fresh source-health evidence that the consumer is caught up and covers the observation interval.

## 11. KPI calculations

KPI means key performance indicator. EIOS combines service health indicators with selected business and resource indicators.

Request rate is the rate of change of a request counter over time. The stored RED measurements use five-minute server-span statistics. Conceptually, request rate is the number of requests during an interval divided by the interval duration. Prometheus `rate()` also accounts for counter-reset behavior.

Error rate is the rate of requests or server spans identified as errors. Error fraction is error rate divided by request rate when request traffic exists. A zero denominator must not become a claimed zero-error ratio.

Latency measures duration. A p95 latency is a threshold below which approximately 95% of measured durations fall. Prometheus can estimate it from histogram buckets. It is not a maximum, and it is not the average duration. Histogram-based estimates depend on bucket boundaries. The [Prometheus histogram documentation](https://prometheus.io/docs/practices/histograms/) explains this distinction.

EIOS's stored `latency_p95_ms` window value is the mean of five-minute p95 snapshots contributing to that window. It is not a newly computed p95 of all requests in the minute. Averaging percentiles does not produce the percentile of the combined underlying observations.

Orders per minute counts distinct observed orders in a minute when source coverage is sufficient. Completed-order events alone do not measure all attempted checkouts. Payment and request metrics provide additional context when order completion falls.

The intelligence configuration includes warning objectives such as memory fraction 0.85, error fraction 0.02, and p95 latency 500 milliseconds. Memory at 0.95 and errors at 0.20 can produce higher operational severity. These are project defaults, not universal thresholds for all organizations.

Order-drop analysis requires a prior healthy order baseline, current request activity, and trustworthy order-source coverage. It compares recent throughput with that baseline. Low traffic or missing source evidence should lead to abstention rather than a false claim of business failure.

Span-derived request measurements reflect the span coverage available to the pipeline. Sampling, instrumentation gaps, retries, and service naming affect their interpretation. Production request-count objectives should use an appropriate complete metric source or explicitly account for sampling.

## 12. Rule detection and machine-learning detection

Rules encode known conditions, such as sustained high resource use. They are explainable, inexpensive, and useful before enough training history exists. Their limitations include manual threshold selection and limited adaptation to different service behaviors.

Machine learning learns patterns from historical feature windows. A service's normal operating region may be different from another service's normal region. EIOS therefore supports per-service model versions.

Isolation Forest isolates observations through random splits. Unusual observations tend to require fewer splits to isolate than common observations. The model can identify unusual patterns without requiring examples of every failure type. The implementation uses scikit-learn; the [Isolation Forest API documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html) describes the estimator and scoring interface. Installed versions are pinned separately in the project.

The project trains on explicitly reviewed healthy data, creates a score threshold from training behavior, and checks a later healthy validation interval. An operator's healthy-data declaration is part of the procedure; an event count alone does not establish healthy training data.

Isolation Forest scores are unusualness scores. They are not calibrated failure probabilities. A normalized score of 0.9 must not be described as a 90% chance that the service will fail.

The current model also uses an explicit CPU guard at `max(0.5 cores, 3 × training p95 CPU)`. This addresses the limitation that tree-based isolation does not measure ever-increasing distance beyond the outermost splits. The forest component and guard component are exposed separately. Evaluation must describe this as a hybrid detector, rather than attributing every CPU detection to machine learning alone.

Operational severity is assigned using observed impact and configured criteria. It is a different concept from statistical unusualness.

## 13. Model training, registry, inference, and rollback

Training requires at least 60 usable healthy minute windows, including enough windows for both training and validation. The implementation requires at least 40 training windows and 10 validation windows after a five-minute separation gap. In practice, collection needs more elapsed time to allow warmup, the gap, missing samples, and representative loads.

Recorded fault intervals, fault-boundary and recovery margins, and confirmed anomalous windows are excluded from healthy training. Future information and fault labels must not enter the model's input features.

Chronological splitting places earlier windows in training and later windows in validation. Randomly mixing nearby time windows can exaggerate performance because adjacent observations are highly related.

Training produces a candidate model. Registration records service, algorithm, feature names, feature version, training period, validation results, dependency versions, checksum, and artifact identity.

Promotion is explicit. The project checks artifact integrity, dependency compatibility, sufficient validation data, and an acceptable alert fraction on healthy holdout data. A development gate of at most 10% healthy validation alerts is not a claim of acceptable production performance or measured fault-detection accuracy.

Inference applies the active model to fresh compatible windows. Missing required features or an invalid artifact causes abstention. The worker records scoring progress so restarts do not create new copies of the same result merely because the process started again.

Rollback activates a previously registered version through the same checks. A candidate is not automatically active, and registering a model does not prove it has run inference.

Artifacts are loaded from an owned local volume and checked before use. Serialized Python models must be treated as trusted executable artifacts; arbitrary user uploads should not be loaded into the worker.

## 14. Memory prediction

The current predictive feature estimates short-term memory growth using a local linear trend. It is designed to give an early indication that memory may approach a warning boundary.

The estimate uses recent valid memory observations. Conceptually, projected memory fraction equals current memory fraction plus estimated growth per minute multiplied by the forecast horizon. The supported horizons are five and ten minutes.

When growth is positive and current memory is below the warning boundary, an estimated time to the boundary can be calculated by dividing remaining capacity-to-warning by the growth rate.

The implementation validates the requested horizon using earlier points with known later outcomes. It compares the trend model with persistence, which predicts that memory stays at its latest observed value. A more complicated model is not useful merely because it produces a changing line.

Forecasts can abstain because of insufficient history, gaps, stale data, abrupt memory release or a possible restart, unstable trends, insufficient validation pairs, or failure to perform well enough against persistence.

A projection is not a guaranteed failure time. Garbage collection, traffic changes, deployments, restarts, and memory-limit changes can invalidate the trend. There is no calibrated uncertainty band in this implementation.

The horizon begins at the observation timestamp. Since processing waits for the feature window to close, some horizon time can have elapsed before the operator sees the prediction. Evaluation uses actual creation time when measuring warning lead time.

## 15. Evidence, recommendations, cases, and feedback

A stored finding identifies the affected service and observation interval. It includes measurements, a baseline or threshold when applicable, detector identity, optional model version, severity, analytical details, and evidence event IDs.

Recommendations come from a versioned operational catalog. Examples include investigating CPU consumption, memory retention, request errors, or latency. They provide a target, rationale, and preconditions. They are not generated by an unrestricted language model.

Jaeger dependency snapshots and nearby service measurements can support a candidate explanation. For example, payment errors and reduced checkout throughput may be related. Dependency proximity alone does not prove that payment caused the checkout behavior.

Related findings can be grouped into a case with a persisted identity and timeline. Current case grouping uses same-service episodes. This provides durable investigation context but does not imply complete cross-service incident clustering or automatic resolution.

Confirm and Dismiss in Reports record operator feedback. Feedback is stored and can inform later reviewed training decisions. It does not immediately retrain a model or execute a recommendation.

Case approval endpoints record a requested action and a decision. The intelligence approval flow currently does not execute a service restart, change replica counts, or perform automatic remediation. Separate Docker operational endpoints exist and must be understood as a different capability.

## 16. How the frontend gets its data

The frontend API client is `eios/dashboard/src/lib/api.ts`. It sends HTTP requests to the configured backend address. `VITE_API_BASE` is compiled into the dashboard build. The local setup uses `http://127.0.0.1:8000`.

React components keep returned data in state and render it. Timers trigger refreshes. A component can therefore show a recent snapshot rather than the backend's exact instantaneous state.

The desktop performs periodic general telemetry requests. Reports separately retrieves intelligence status, KPI windows, insights, forecasts, models, and selected-service history. Reports refreshes every 30 seconds while open. Its finding-period filter applies to findings and the requested history range; KPI and forecast panels show their latest snapshots.

The project also provides a WebSocket incident feed with reconnect behavior. WebSocket availability does not mean every window uses WebSockets. The Reports implementation uses polling. After disconnection, stored REST history remains the reliable way to retrieve existing findings.

The Reports views are Overview, Anomalies & Findings, Predictions, KPIs, and Models. The findings view combines several detector kinds; it must not be interpreted as a list containing only ML anomalies. Models are read-only in this UI.

Learning means a model is not yet available or ready for the relevant work. Stale means an observation is too old to support a current-state claim. Unavailable indicates missing access or data. Abstained means an analytical method chose not to issue a result because its requirements were not met.

## 17. How graphs are made

The custom EIOS graphs use SVG inside React components. SVG provides shapes such as paths, lines, circles, rectangles, and text. The browser draws these shapes using coordinates calculated from the data. A graph is a visualization of observations; it does not itself collect telemetry or detect failures.

For a time-series plot, timestamps map to horizontal positions. The basic mapping is `x = left + (timestamp - earliestTimestamp) / timeRange × plotWidth`. Values map to vertical positions. Because SVG's y coordinate increases downwards, higher values require smaller y coordinates.

The Reports `Trend` component uses stored feature windows from `/api/intelligence/history`. It filters finite values, calculates a range, and draws observed points. Its SVG view box is 600 by 145. The horizontal data region spans 580 units. A minimum vertical range prevents division by zero for a flat series.

Adjacent valid points are joined only if their observation times are no more than 90 seconds apart. Missing values are not plotted, and long gaps are not joined. A point's SVG title contains its time and value. The caption gives the time span and observed range.

These are observed-history plots. The current Predictions view presents calculated forecast values and warning information in cards alongside observed memory history. It does not currently draw a complete future forecast curve or uncertainty band.

`SystemMonitorWindow.tsx` also builds SVG chart paths and contains a topology illustration. Those visuals are separate from the Reports history plots. Some older desktop elements contain fixed or demonstration values. A continuously moving or attractively rendered chart is not sufficient evidence that its values are live measurements.

`ServiceGraph.tsx` and the service graph API provide a separate dependency-view path. In a dependency graph, nodes represent services and edges represent observed calls. Edge data should come from trace-derived dependency information. A topology line has a different meaning from a time-series line: it indicates a relationship, not change over time.

Before using any graph as experimental evidence, identify its endpoint, source data, units, aggregation interval, freshness behavior, and fallback behavior. For the intelligence demonstration, Reports and the associated stored API results provide the clearest evidence path.

## 18. Frontend appearance and theme

The EIOS frontend uses a desktop layout with sidebar launchers, windows, a header, and a taskbar. Reports was added to the existing Reports launcher rather than introducing another application layout.

The small top-right theme button switches the root `dark` class. Shared CSS variables change surfaces, text, borders, and accents across the interface. The choice is saved under `eios_theme` in local storage and restored before the first paint.

Theme selection is a browser preference. It changes presentation and does not affect the Intelligence Agent, model results, collection intervals, or application workload.

The interface preserves the project's teal identity and existing SVG launcher artwork. Report data and interpretation should remain the same in both modes.

## 19. Implemented features and demonstration elements

The implemented intelligence path includes durable normalized input, feature windows, KPI analysis, model training and registration, explicit activation and rollback, active-model inference, short-term memory forecasting, stored findings, evidence references, feedback, and Reports integration.

The backend AI chat endpoint uses stored analytics to assemble a deterministic response. This is not a general-purpose LLM assistant. The older frontend assistant still contains local fallback responses, so a frontend message displayed during an API failure must not be treated as verified analysis.

The Security Center also contains fallback or demonstration content. Several existing desktop labels, terminal status strings, topology annotations, and resource-governor claims are presentation elements rather than independent proof of an enforced backend control.

The architecture includes broader goals such as automatic scaling, self-learning, complete log and trace correlation, alert noise reduction, escalation, and incident resolution. Some supporting pieces exist, but the full system depicted by those labels is not implemented end to end.

No live model accuracy, production SLA, maximum supported workload, or automatic-remediation success rate should be claimed without a reproducible measurement. Successful unit tests demonstrate behavior under test conditions; they do not establish these operational outcomes.

## 20. Security in the current project

The project includes API-key checking when configured, redaction utilities, security-related routes, audit storage, request-size checks, and a security Compose overlay. Their presence should be separated from proof that every route and running deployment uses them correctly.

The default local Compose configuration is designed for development. It exposes service ports, includes development credentials, and mounts the Docker socket into the orchestrator. The startup script uses the normal overlay; it does not automatically apply every security-overlay setting.

The current administrator account implementation uses an in-memory store and SHA-256 password hashes. Registration can assign or replace records. The returned session token is not a complete verified-session authorization system. Username and role fields alone do not establish authenticated identity or role enforcement.

The middleware exempts certain routes, including login, registration, and the WebSocket endpoint, from its API-key check. A production design needs explicit decisions about authentication and authorization for each capability.

The hash-chain audit helper provides machinery for linked hashes. Other code writes audit rows directly. The application therefore should not be described as universally tamper-proof or universally covered by a verified audit chain. A production audit design must handle concurrency, missing entries, retention, access controls, and verification failure.

A Docker socket grants powerful host-management access. Real deployment should isolate management actions and give each component the smallest required permissions. The UI's security status labels do not replace this enforcement.

Production preparation includes durable identity, strong password hashing or an organizational identity provider, server-verified sessions, route-level authorization, authenticated WebSockets, secret management, restricted networking, TLS, and a tested audit path. The exact requirements depend on the deployment environment.

## 21. Real-life operating scenarios

In an online shop, a payment service may begin producing errors after a release. Request error measurements increase, checkout behavior changes, and completed order volume may fall while customer traffic continues. EIOS can store the measurements, identify a KPI breach, show related service evidence, and recommend investigation. An operator then checks traces, logs, deployment history, and payment-provider availability before choosing an action.

For a memory-retention problem, a service's memory fraction rises across valid windows. The KPI detector can identify high usage, and the forecast can estimate whether the current trend crosses a warning boundary. The operator investigates allocations, retention, traffic, and container limits. A restart can temporarily reduce memory but does not establish that the underlying cause was fixed.

During a CPU-intensive fault, the service's CPU measurements depart from its healthy training range. The active model and explicit CPU guard can produce an anomaly finding with its detector components and baseline. Comparing this with a fixed-threshold rule shows whether the model adds useful early or service-specific detection.

During a telemetry outage, the worker may remain alive while its observations become old. EIOS should show stale or unavailable data and abstain from unsupported analysis. Treating missing values as zero would incorrectly suggest low load or recovery.

During a legitimate sales campaign, higher traffic and resource use may be healthy. A model trained only on quiet traffic can generate false positives. Representative healthy training, business context, and reviewed feedback are necessary to distinguish capacity pressure from abnormal failures.

These scenarios explain intended usage. Their exact detection quality and timing must be measured on the deployed workload.

## 22. How deployment would change in production

The university deployment runs the demo and EIOS together with Docker Compose. A real deployment would attach EIOS to the organization's applications and telemetry sources. Service identities, metric names, units, order or business-event schemas, objectives, and recommendation ownership would need configuration.

The browser cannot use `127.0.0.1:8000` to reach a server running on another person's machine. A production frontend needs an API address reachable by its users, commonly through the same HTTPS origin and reverse proxy. The frontend must be rebuilt when a build-time API address changes.

The ingestion and analysis services need private network access to their sources and stores. PostgreSQL requires backups, restoration testing, storage planning, and appropriate availability. Kafka requires planned retention, broker availability, access controls, and monitoring. Model artifacts require durable storage, controlled writes, and version retention.

Deploying containers to Kubernetes is possible, but it requires EIOS-specific deployment configuration, health probes, resource settings, permissions, storage, and operational testing. The architecture diagram and installed Kubernetes client are not evidence that this deployment has already been completed.

Kubernetes Horizontal Pod Autoscaling can change replica counts from observed resource or custom metrics. Integrating recommendations with an autoscaler would require explicit ownership and policy design. It must not compete with another controller that manages the same resource. See the [Kubernetes autoscaling documentation](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/).

The present intelligence worker periodically queries database windows and keeps shared analysis state. Simply starting several replicas does not guarantee safe parallel processing. Production scaling needs service ownership or work partitioning, coordinated checkpoints, duplicate suppression, and tested failover behavior.

Increasing Kafka consumers helps only where partitions and processing design allow it. Database query cost, model inference, outbox throughput, and source polling can become separate bottlenecks. Capacity should be measured with representative service counts, event rates, and retention periods.

Long-term telemetry and event storage require a retention policy, partitioning or archival where appropriate, and bounded API queries. Model cache and artifact retention also need limits. Container memory limits alone do not solve data-growth problems.

Automated remediation should begin with narrowly allowed actions, checked preconditions, cooldowns, bounded scope, recorded decisions, and post-action verification. Human approval is appropriate where an action could worsen an outage. Automatic action execution is a production extension to the current intelligence recommendation flow.

## 23. Reliability and monitoring EIOS itself

EIOS can fail independently of the monitored application. Its operating metrics should include Kafka lag, source-observation age, rejected input count, feature-window coverage, inference duration, abstention rate, database failures, notification backlog, and API availability.

A process health check answers whether a component is functioning at a basic level. Data readiness answers whether enough timely observations exist. Model readiness answers whether a compatible active model can score those observations. These states must not be collapsed into one green indicator.

An SLI is a measured service-level indicator, such as the proportion of successful requests. An SLO is a target for that indicator over a defined period. An SLA is an agreement specifying service commitments and consequences. A warning threshold on an individual metric is not automatically an SLO or SLA. MTTD describes average time to detect incidents; MTTR describes average time to restore service under a clearly stated definition. EIOS does not establish these organizational outcomes merely by creating incident records.

If Kafka publication fails after a database commit, the outbox retains delivery work. If a worker restarts, stored state and deterministic result identities support recovery. If the database is unavailable before durable input handling, offsets should not advance past unpersisted work.

Retries have limits. Broker retention can expire data, storage can fill, and persistent volumes can fail. The production system needs alerting on backlog and storage conditions before recovery becomes impossible.

Prometheus collection, event normalization, baseline detection, intelligence processing, and frontend retrieval have distinct failure modes. Troubleshooting should locate the last stage containing correct, timely data rather than assuming every missing chart is a frontend problem.

## 24. Evaluation and measurable outcomes

A useful experiment compares healthy operation, controlled faults, and recovery under recorded conditions. Start and end times, affected service, fault type, traffic level, and deployed model version should be recorded.

Training, validation, and evaluation periods have different roles. Training fits the model. Validation selects or checks its operating behavior. Evaluation measures it against later reviewed data. Reusing evaluation data to tune the model makes the reported result less independent.

A true positive is a detected abnormal condition matched to reviewed abnormal ground truth. A false positive is an alert on reviewed healthy behavior. A false negative is an abnormal condition the detector misses. The exact definition must specify whether the unit is a time window or an incident episode.

Precision is `TP / (TP + FP)`. Recall is `TP / (TP + FN)`. F1 is the harmonic mean of precision and recall when defined. Undefined denominators should remain undefined rather than being reported as perfect scores.

False alert windows per healthy hour measures noise at the window level. Episode recall measures how many complete fault episodes were detected. Detection delay measures time from fault onset to detection under the evaluator's timing definition.

EIOS's model evaluation compares its hybrid model with a CPU/memory rule baseline on the same eligible windows. It uses chronological separation and excludes incomplete, ambiguous boundary, and recovery windows. It needs correctly scoped fault records. Existing payment-fault mapping requires particular care before treating it as payment-service ground truth.

Signal delay calculated from stored windows does not include every live-system delay. User-visible delay also includes collection, lateness allowance, evaluation scheduling, publishing, and frontend refresh.

Forecast error is measured by comparing a prediction with an observed later value. Mean absolute error is the average absolute prediction error. A persistence baseline provides a simple reference. Warning evaluation also considers false warnings and how much useful lead time existed when the prediction was actually created.

Backend tests cover data validity, freshness, forecast behavior, artifact checks, model lifecycle, database transactions, deduplication, replay-related behavior, and API contracts. Frontend checks cover relevant interactions and error states. These are different from live fault experiments and production load tests.

## 25. Local startup and inspection

From the workspace root in PowerShell:

```powershell
.\eios\start.ps1
```

After source changes that require rebuilding images:

```powershell
.\eios\start.ps1 -Build
```

For the configured demonstration load:

```powershell
.\eios\start.ps1 -Demo
```

The script starts Docker Desktop when necessary, brings up the Compose stack, waits for Kafka readiness, and handles startup sequencing issues. Startup time depends on image availability and local resources.

The EIOS dashboard is at `http://127.0.0.1:5173`. The API and Swagger are at `http://127.0.0.1:8000` and `http://127.0.0.1:8000/docs`. The storefront is at `http://127.0.0.1:8080`. The demo exposes Jaeger and Grafana through its frontend proxy.

Useful read-only checks are:

```powershell
docker ps
docker logs eios-ingest --tail 30
docker logs eios-intelligence --tail 30
Invoke-RestMethod http://127.0.0.1:8000/api/intelligence/status
Invoke-RestMethod 'http://127.0.0.1:8000/api/intelligence/kpis?service=ad'
Invoke-RestMethod 'http://127.0.0.1:8000/api/intelligence/forecasts?service=email'
Invoke-RestMethod http://127.0.0.1:8000/api/intelligence/models
```

Use the existing intelligence runbook for reviewed data collection, training, promotion, rollback, and evaluation commands. A model UUID and a real reviewed collection interval must be supplied; those operations should not be presented as already completed merely because the code is available.

The backend test entry point is:

```powershell
.\eios\scripts\test-intelligence.ps1
```

That script uses a disposable test database. It is separate from testing against the application's real collected history.

## 26. Common explanations for unexpected results

If Reports says Learning, check whether a model has been registered, promoted, and has sufficient compatible data. KPI analysis can still work without an active anomaly model.

If a forecast abstains, read its reason. More history does not resolve every reason: an unstable trend or a trend worse than persistence may correctly remain unsuitable for prediction.

If request metrics are unavailable for a service that has CPU and memory, that service may lack the corresponding server-span series or source coverage. Infrastructure-only services do not necessarily have business request metrics.

If a value appears one hundred times too large or too small, verify fraction-versus-percentage conversion and collector units. Do not adjust the displayed number without fixing the underlying interpretation.

If an order decline appears during source lag, verify source health before interpreting it as lost customer business. If a service is stale after being removed, historical records may still exist even though the current container is gone.

If the dashboard cannot reach the API, check backend availability, the compiled API address, API-key configuration, and allowed browser origins. If a new frontend feature does not appear after rebuilding, reload the browser so it retrieves the new assets.

If a controlled fault produces no evaluated detection, inspect the recorded fault scope, timing, model state, eligible windows, cooldown behavior, and baseline. A missed detection is a result to investigate, not a reason to manufacture a favorable chart.

## 27. Repository reading map

`eios/compose.eios.yaml` explains the running EIOS services, local endpoints, dependencies, limits, and volumes. `eios/start.ps1` explains startup behavior.

`eios/schemas/events.py`, `eios/schemas/incidents.py`, and `eios/schemas/intelligence.py` define the shared data contracts.

`eios/ingest/prom_tap.py`, `kafka_tap.py`, `sink.py`, and `main.py` explain source collection, normalization, persistence, and delivery.

`eios/detect/rules.py` and `config.py` explain the baseline rules and configuration.

`eios/intelligence/features.py` explains window formation and quality. `analytics.py` explains KPI and memory calculations. `models.py` explains training, scoring, artifact handling, and promotion. `store.py` explains persistence. `main.py` explains the continuous worker. `evidence.py` explains dependency context. `evaluation.py` and `cli.py` explain experiments and operator commands.

`eios/db/init.sql` and `migrate_intelligence.sql` explain database structures. `eios/intelligence/tests/` contains backend analytical and integration checks.

`eios/orchestrator/main.py`, `intelligence_router.py`, and `agents_router.py` explain API integration and stored agent results. The authentication, middleware, security, Docker, terminal, filesystem, and system routers show the separate operational capabilities and their limitations.

`eios/dashboard/src/lib/api.ts` explains browser-to-backend requests. `components/os/ReportsWindow.tsx` explains Reports data loading, tabs, feedback, and history graphs. `lib/intelligence.ts` contains frontend intelligence contracts and formatting.

`components/os/SystemMonitorWindow.tsx`, `components/ServiceGraph.tsx`, and `components/ServicePanel.tsx` are relevant to other charts and service views. `components/os/EIOSDesktop.tsx` connects desktop windows. `components/ThemeToggle.tsx`, `src/index.css`, and `index.html` implement theme selection and restoration.

The [Intelligence Agent runbook](./intelligence-agent-runbook.md) contains operational instructions. The [implementation plan](./intelligence-agent-plan.md) records the original design and subsequent implementation updates. Older README text and architecture labels should be checked against current source before being used as implementation claims.

## 28. Learning order

First understand the business request flow through the demo services and the difference between the storefront and the EIOS dashboard.

Next understand metrics, logs, traces, spans, resource identities, timestamps, and the difference between an observation, an incident, and a case.

Then follow one metric and one order event through collection, normalization, PostgreSQL storage, Kafka delivery, feature-window construction, detection, and API retrieval.

Study KPI units and formulas before interpreting charts. Study missing-data and stale-data behavior before interpreting low values as healthy operation.

Study rule detection before Isolation Forest, and understand the explicit CPU guard alongside the learned detector. Then study training, chronological validation, activation, inference, and rollback as separate operations.

Study forecasting with the persistence baseline, abstention rules, and actual warning lead time. Study evidence and feedback without assuming they prove causation or automatically change models.

Finally, study evaluation, security gaps, persistence and retry behavior, deployment changes, scaling constraints, and the distinction between a working local prototype and a validated production service.
