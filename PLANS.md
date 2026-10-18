# EIOS Implementation Roadmap

## Purpose

This roadmap evolves the existing EIOS prototype into a university-major-project-grade intelligent microservice reliability platform without discarding working components.

The current implementation already provides a strong base: telemetry ingestion, normalized events, rule-based incident detection, an orchestrator, a React dashboard, Docker/container control, fault injection support, PostgreSQL storage, security middleware, and real-time APIs/WebSockets.

The target is a complete closed-loop system:

Observe → Detect → Correlate → Investigate → Explain → Recommend → Approve → Remediate → Verify → Evaluate

---

## Phase 0 — Repository Audit and Baseline

### Goal
Establish exactly what works today before changing architecture.

### Tasks
- Read `PROJECT.md`, `README.md`, and the target documents under `docs/`.
- Inspect all EIOS services and compose files.
- Map current APIs, schemas, data stores, event flows, WebSockets, and UI pages.
- Identify hard-coded Astronomy Shop assumptions.
- Record current startup procedure and known failure points.
- Produce a gap analysis against the target architecture.

### Deliverables
- Current-state architecture map.
- Gap analysis.
- Prioritized technical debt list.
- Verified baseline demo.

### Acceptance Criteria
- Existing stack starts successfully.
- Existing dashboard, ingestion, detection, and incident flow are demonstrated before refactoring.
- No production code is changed merely for this phase unless required to restore the baseline.

---

## Phase 1 — Authentication, Application Registry, and Service Catalog

### Goal
Make EIOS application-oriented instead of implicitly tied to one demo stack.

### Tasks
- Implement administrator authentication and session handling if not already production-ready.
- Add `applications` and `services` persistence models.
- Create an Add Application workflow.
- Store runtime type, telemetry endpoints, environment, and labels.
- Add a Service Catalog page.
- Associate telemetry and incidents with application/service IDs.

### Minimum Application Record
- application ID
- name
- environment
- runtime type (`docker`, future `kubernetes`)
- telemetry endpoints/configuration
- status
- created/updated timestamps

### Minimum Service Record
- service ID
- application ID
- service name
- runtime identifier/container name
- language/runtime metadata when available
- health state
- discovered dependencies
- tags/labels

### Acceptance Criteria
- Admin can create an application.
- Admin can add/discover services.
- Registered services remain visible after restart.
- Existing Astronomy Shop can be onboarded through the new model.

---

## Phase 2 — Unified Telemetry Pipeline

### Goal
Create a single vendor-neutral event model for metrics, traces, logs, and business events.

### Tasks
- Define canonical telemetry contracts.
- Refactor existing Kafka and Prometheus ingestion around application/service identity.
- Add trace ingestion/query integration.
- Add log ingestion/query integration.
- Preserve raw-source references for investigation.
- Add telemetry freshness/connection health checks.

### Acceptance Criteria
- EIOS can associate metrics, traces, logs, and business events with the correct application and service.
- Data is normalized without losing source evidence.
- Failure of one telemetry source does not crash the entire pipeline.

---

## Phase 3 — Service Discovery and Live Topology

### Goal
Represent the monitored system as a dependency graph that can drive both UI and analysis.

### Tasks
- Discover service-to-service edges from trace data.
- Store/update topology edges.
- Calculate node health and edge health.
- Add a live topology API.
- Render interactive topology in the dashboard.
- Allow service drill-down from a topology node.

### Acceptance Criteria
- Astronomy Shop dependencies are visible without manually hard-coding every edge.
- Service health changes are reflected in the graph in near real time.
- Topology data is reusable by RCA and correlation engines.

---

## Phase 4 — Real-Time Operations Dashboard

### Goal
Create a clear operations experience instead of only a collection of technical windows.

### Required Views
- Operations Overview
- Application Overview
- Service Explorer
- Live Topology
- Incident Center
- Experiment Lab
- Security/Audit View

### Acceptance Criteria
- Operators can identify unhealthy services quickly.
- Metrics and incident state update in real time or near real time.
- UI clearly separates application health, service health, incidents, and experiments.

---

## Phase 5 — Hybrid Anomaly Detection and Health Scoring

### Goal
Move beyond fixed thresholds while preserving explainability.

### Detection Layers
1. Static rules.
2. Dynamic statistical baselines.
3. Optional unsupervised ML anomaly model.

### Suggested Statistical Methods
- rolling mean
- rolling standard deviation
- Z-score
- EWMA
- rate-of-change checks

### Suggested ML Baseline
- Isolation Forest on normalized service-level features.

### Health Score Inputs
- error rate
- request rate
- latency
- CPU
- memory
- restart/health status
- anomaly score

### Acceptance Criteria
- Each detected anomaly records its detector, score, threshold/baseline, and evidence.
- Static and dynamic detectors can be evaluated separately.
- Health score is reproducible from stored evidence.

---

## Phase 6 — Alert Correlation and Incident Engine

### Goal
Reduce many symptoms into fewer meaningful incidents.

### Correlation Inputs
- time proximity
- service topology
- shared traces
- same error signature
- same fault window
- same upstream/downstream failure chain

### Tasks
- Introduce alert/anomaly records distinct from incident records if needed.
- Group related alerts into incidents.
- Add incident severity calculation.
- Add incident lifecycle/state machine.
- Record correlated evidence.

### Acceptance Criteria
- One injected payment failure does not appear as unrelated standalone alerts only.
- Related symptoms can be grouped into one incident.
- Alert-reduction ratio can be measured.

---

## Phase 7 — Deterministic Root Cause Analysis

### Goal
Rank probable root causes using evidence rather than LLM guessing.

### RCA Signals
- temporal precedence
- anomaly severity
- topology position
- trace failure concentration
- propagation direction
- service health/resource state
- matching historical failure signatures

### Output
For each incident, store ranked candidates:
- service
- confidence/score
- evidence
- supporting traces/events

### Acceptance Criteria
- RCA is deterministic for the same evidence set.
- UI shows why a service received its score.
- RCA can be evaluated against known injected faults.

---

## Phase 8 — AI Investigation Agent

### Goal
Use an LLM as a bounded investigation assistant on top of deterministic evidence.

### Allowed Tools
- get service metrics
- get service logs
- get recent traces
- get dependencies
- get container status
- get incident evidence
- get recent incident history

### Responsibilities
- summarize evidence
- explain likely failure chain
- ask for additional evidence through approved tools
- produce structured investigation findings
- generate operator-friendly explanation

### Restrictions
- no arbitrary shell access
- no direct Docker control
- no autonomous destructive actions
- no unsupported factual claims without evidence

### Acceptance Criteria
- Agent output references actual incident evidence.
- Same incident can be understood without reading raw telemetry manually.
- Agent failure does not block deterministic incident handling.

---

## Phase 9 — Remediation Planner and Policy Engine

### Goal
Turn investigation results into safe, structured recovery proposals.

### Initial Allowed Actions
- restart service/container
- stop/start service in Experiment Lab
- run health check
- capture logs/diagnostic bundle
- toggle approved demo fault flags
- future: scale service

### Action Proposal Format
- action type
- target service
- reason
- confidence
- risk level
- prerequisites
- expected effect

### Modes
- Observe — no remediation.
- Assisted — recommend; human approves.
- Autonomous — only explicitly allow-listed low-risk actions.

### Acceptance Criteria
- LLM text is converted into or accompanied by a validated structured action.
- Policy engine rejects unsupported actions.
- Operator approval is recorded.

---

## Phase 10 — Runtime Adapter and Controlled Remediation

### Goal
Abstract infrastructure control away from incident logic.

### Interface
`RuntimeAdapter`

Initial implementation:
- `DockerRuntimeAdapter`

Future implementation:
- `KubernetesRuntimeAdapter`

### Acceptance Criteria
- Incident/remediation logic does not call the Docker socket directly from arbitrary code paths.
- Runtime actions use allow-listed adapter methods.
- Action outcomes are captured and audited.

---

## Phase 11 — Recovery Verification

### Goal
Prove whether remediation actually restored the system.

### Verification Signals
- target service health
- error rate recovery
- latency recovery
- request/order throughput recovery
- downstream symptom recovery
- disappearance of related anomalies

### Outcomes
- recovered
- partially recovered
- failed recovery
- inconclusive

### Acceptance Criteria
- Incident is not marked resolved solely because a restart command returned success.
- Before/after evidence is stored.
- Failed remediation can trigger escalation or a second recommendation.

---

## Phase 12 — Experiment Lab

### Goal
Provide repeatable controlled failure demonstrations and ground truth.

### Initial Scenarios
- payment failure
- cart failure
- product catalog failure/latency
- email memory leak
- ad high CPU
- Kafka queue/backpressure problem
- explicit service stop/restart scenario

### Controls
- scenario
- target service
- load level
- duration
- start/stop

### Acceptance Criteria
- Experiment start/end times are persisted.
- Every run has ground-truth metadata.
- Detection/RCA/recovery outcomes are linked to the experiment.

---

## Phase 13 — Evaluation Framework

### Goal
Turn EIOS into a measurable academic system.

### Metrics
- precision
- recall
- F1 score
- MTTD
- incident creation latency
- RCA accuracy / top-k accuracy
- alert reduction ratio
- remediation success rate
- MTTR
- false-positive rate

### Acceptance Criteria
- Metrics are computed from stored experiment data rather than manually typed values.
- Results can be exported or displayed in an Evaluation Dashboard.

---

## Phase 14 — Security, RBAC, and Governance Hardening

### Goal
Make administrative and automated actions defensible.

### Roles
- Viewer
- Operator
- Administrator

### Tasks
- enforce permissions
- preserve PII redaction
- preserve/extend rate limiting
- preserve cryptographic audit logging
- audit remediation approvals and execution
- validate secrets/configuration handling

### Acceptance Criteria
- Unauthorized roles cannot execute remediation.
- Sensitive values are not exposed in UI/logs.
- Critical actions have auditable records.

---

## Phase 15 — Final UX and Demonstration Flow

### Goal
Optimize the system for a clear university demonstration.

### Final Demo
1. Log in.
2. Open onboarded Astronomy Shop application.
3. Show healthy topology and telemetry.
4. Start load generation.
5. Open Experiment Lab.
6. Inject/stop a target service.
7. Watch topology and telemetry degrade in real time.
8. Show correlated incident.
9. Show RCA ranking and evidence.
10. Show AI explanation.
11. Approve remediation.
12. Show recovery verification.
13. Show incident timeline and audit trail.
14. Show experiment metrics.

### Acceptance Criteria
- Demo is reproducible from a clean documented startup.
- Every screen used in the demo displays real backend data.
- No critical step depends on manually editing the database.

---

## Optional Phase 16 — Kubernetes and Multi-Application Expansion

Only begin after the Docker-based closed loop and evaluation pipeline are stable.

Possible work:
- Kubernetes discovery/runtime adapter
- deployment scaling
- pod-level remediation
- multi-cluster support
- SLO management
- failure forecasting
- autonomous low-risk policies
- notification integrations

---

# Scope Rule

Do not sacrifice the core closed-loop incident workflow to implement optional features.

The minimum major-project-quality EIOS is:

Application Onboarding
→ Telemetry
→ Topology
→ Detection
→ Correlation
→ Incident
→ RCA
→ Investigation
→ Human-approved Remediation
→ Verification
→ Experiment Evaluation
