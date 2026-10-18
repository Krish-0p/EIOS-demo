# EIOS Product Vision

## 1. Product Name

**EIOS — Enterprise Intelligence Operating System**

### Descriptor
**An Intelligent Microservice Observability, Incident Investigation, and Self-Healing Operations Platform**

---

## 2. Problem Statement

Modern web applications are commonly composed of many independently deployed microservices. A single user request can travel through several services, message brokers, databases, and infrastructure components before it completes.

When one component fails, operators can receive many separate symptoms:

- high latency
- service errors
- failed traces
- resource spikes
- dropped business transactions
- downstream service failures
- container health failures

Traditional observability platforms are excellent at exposing metrics, logs, and traces, but an operator must still correlate those signals, determine the likely root cause, decide what action to take, and verify whether the action restored the system.

EIOS is intended to combine these stages into one explainable operational workflow.

---

## 3. Vision

EIOS is a vendor-neutral intelligence and operations layer that sits alongside a distributed application.

It continuously observes the application's telemetry, builds a live model of its services and dependencies, detects abnormal behavior, correlates related symptoms into incidents, ranks probable root causes, assists operators during investigation, proposes safe remediation actions, executes approved actions, and verifies whether the application recovered.

The OpenTelemetry Astronomy Shop is used as the primary demonstration and experimental environment because it is a realistic microservice application with observability and controlled failure-injection capabilities.

EIOS itself should not be designed as an Astronomy-Shop-specific product.

---

## 4. Main User

The primary user is an **administrator/operator** responsible for the health of one or more distributed applications.

The operator should not need to open several separate tools simply to understand one incident.

---

## 5. Administrator Journey

### 5.1 Login

The administrator signs in to EIOS and reaches the operations dashboard.

### 5.2 Add Application

The administrator creates an application entry, for example:

```text
Application Name: Astronomy Shop
Environment: Development
Runtime: Docker
Prometheus: http://prometheus:9090
Trace Source: Jaeger / OpenTelemetry
Log Source: OpenSearch / OpenTelemetry
```

### 5.3 Add or Discover Services

EIOS discovers or registers the application's microservices.

Example:

```text
Astronomy Shop
├── frontend
├── checkout
├── cart
├── payment
├── product-catalog
├── shipping
├── email
├── accounting
└── ...
```

### 5.4 Observe the Application

The application becomes visible in EIOS with:

- current service health
- metrics
- traces
- logs
- business events
- dependencies
- active incidents
- service topology

### 5.5 Run a Controlled Failure

For the university demonstration, the administrator can open the Experiment Lab and intentionally stop a service or activate a supported demo failure.

Example:

```text
Experiment: Payment Failure
Load: 20 users
Duration: 60 seconds
```

### 5.6 Real-Time Impact

EIOS should immediately begin showing the effect:

```text
Payment       HEALTHY → CRITICAL
Checkout      HEALTHY → DEGRADED
Order Rate    NORMAL  → DOWN
Error Rate    NORMAL  → HIGH
```

The live topology should visually show the failure propagation.

### 5.7 Incident Creation

Instead of showing many unrelated alerts, EIOS correlates symptoms into a single incident.

Example:

```text
INC-1042
Critical Payment Failure

Affected Services:
- payment
- checkout
- frontend

Correlated Signals:
- payment error spike
- failed checkout traces
- order-rate reduction
- downstream error increase
```

### 5.8 Root Cause Analysis

EIOS ranks possible root causes.

```text
1. Payment Service     0.94
2. Checkout Service    0.41
3. Frontend            0.14
```

The score must be supported by evidence such as temporal precedence, trace concentration, topology, anomaly severity, and propagation behavior.

### 5.9 Investigation Assistance

An AI investigation agent receives bounded tools for retrieving evidence and produces an operator-friendly explanation.

Example:

```text
The payment service produced the earliest major anomaly.
Most failed checkout traces terminate inside the payment path.
Payment error rate rose significantly before checkout and frontend symptoms appeared.
No comparable CPU or memory anomaly was observed in checkout.
```

### 5.10 Remediation Recommendation

EIOS proposes a structured action.

```text
Recommended Action: Restart payment service
Risk: Low
Confidence: High

[Approve]
[Reject]
[View Evidence]
```

### 5.11 Controlled Execution

After approval, the orchestration layer executes the action using an allow-listed runtime adapter.

### 5.12 Recovery Verification

EIOS verifies whether the remediation actually restored the application.

```text
Before:
Error Rate: 49%
Latency: 1800 ms
Health Score: 31

After:
Error Rate: 1.5%
Latency: 430 ms
Health Score: 93

Recovery: VERIFIED
```

The incident is resolved only when recovery criteria are satisfied.

---

## 6. Core Closed-Loop Workflow

```text
MONITORED APPLICATION
        ↓
TELEMETRY COLLECTION
        ↓
NORMALIZATION
        ↓
SERVICE HEALTH + TOPOLOGY
        ↓
ANOMALY DETECTION
        ↓
ALERT CORRELATION
        ↓
INCIDENT CREATION
        ↓
ROOT CAUSE ANALYSIS
        ↓
AI-ASSISTED INVESTIGATION
        ↓
REMEDIATION RECOMMENDATION
        ↓
HUMAN / POLICY APPROVAL
        ↓
CONTROLLED REMEDIATION
        ↓
RECOVERY VERIFICATION
        ↓
INCIDENT RESOLUTION
        ↓
EXPERIMENT + AUDIT + LEARNING DATA
```

---

## 7. Core Product Modules

### Application Registry
Stores monitored applications and their telemetry/runtime configuration.

### Service Catalog
Maintains service identity, health, dependencies, metadata, and runtime mapping.

### Telemetry Pipeline
Handles metrics, traces, logs, and business events.

### Topology Engine
Builds a live dependency graph from observed service communication.

### Intelligence Engine
Provides static rules, statistical anomaly detection, optional ML anomaly detection, and health scoring.

### Correlation Engine
Groups related symptoms into meaningful incidents.

### Incident Engine
Stores state, severity, evidence, timelines, and lifecycle transitions.

### RCA Engine
Ranks probable root causes using deterministic evidence.

### Investigation Agent
Uses approved tools to explain incidents and summarize evidence.

### Remediation Planner
Produces safe structured recovery proposals.

### Runtime Orchestrator
Executes allow-listed infrastructure actions.

### Verification Engine
Checks whether remediation restored healthy behavior.

### Experiment Lab
Creates controlled ground-truth failures for demonstration and evaluation.

### Evaluation Engine
Calculates academic metrics such as precision, recall, F1, MTTD, MTTR, and RCA accuracy.

### Security and Governance
Provides authentication, authorization, redaction, rate limiting, and audit trails.

---

## 8. Core Dashboard Experience

### Operations Overview
Show:
- number of applications
- total services
- healthy/degraded/critical services
- active incidents
- live topology
- error-rate trend
- latency trend
- request/order volume
- recent incidents

### Application View
Show all services belonging to one monitored application and the telemetry connection status.

### Service Explorer
For a selected service show:
- health score
- status
- CPU/memory
- request rate
- error rate
- latency
- logs
- traces
- dependencies
- active incidents
- recent actions

### Incident Center
Show active and historical incidents with severity, state, root-cause candidate, confidence, and timestamps.

### Investigation View
Combine:
- incident timeline
- evidence
- correlated anomalies
- topology
- traces
- logs
- RCA ranking
- AI explanation
- remediation proposal

### Experiment Lab
Allow controlled demonstration faults and record expected ground truth.

### Evaluation Dashboard
Show experiment outcomes and calculated metrics.

---

## 9. Intelligence Strategy

EIOS should use a hybrid model.

### Layer 1 — Deterministic Rules
Examples:
- service unhealthy
- error rate above threshold
- CPU saturation
- memory exhaustion
- order throughput collapse

### Layer 2 — Dynamic Statistical Detection
Examples:
- rolling baseline
- Z-score
- EWMA
- rate-of-change detection

### Layer 3 — Optional ML Detection
Use an unsupervised anomaly detector such as Isolation Forest on service-level telemetry features.

### Layer 4 — LLM Assistance
Use LLMs only after evidence exists.

Good LLM responsibilities:
- summarize investigation evidence
- explain failure chains
- generate operator-friendly incident reports
- produce structured remediation suggestions

Bad LLM responsibilities:
- invent telemetry
- replace deterministic anomaly detection
- execute unrestricted shell commands
- decide high-risk infrastructure actions without policy checks

---

## 10. Major-Project Academic Contribution

The project should be evaluated as a system, not only shown as a UI.

The primary academic question can be framed as:

> How effectively can a hybrid observability intelligence platform detect, correlate, diagnose, and assist recovery from controlled failures in distributed microservice applications?

The project can compare:

- static thresholds
- statistical baselines
- hybrid detection

and evaluate:

- precision
- recall
- F1 score
- false-positive rate
- mean time to detect (MTTD)
- root-cause accuracy
- alert reduction
- mean time to recovery (MTTR)
- remediation success rate

---

## 11. Core Scope

The final university submission should prioritize:

1. Application onboarding.
2. Service discovery/catalog.
3. Live telemetry.
4. Service topology.
5. Hybrid anomaly detection.
6. Alert correlation.
7. Incident management.
8. Explainable RCA.
9. AI investigation assistance.
10. Human-approved remediation.
11. Recovery verification.
12. Experiment Lab.
13. Evaluation metrics.
14. Auditability and security.

---

## 12. Optional Scope

Only after the core system is stable:

- Kubernetes adapter
- multi-cluster management
- predictive failure forecasting
- advanced automatic scaling
- notifications
- SLO management
- cost optimization
- fully autonomous low-risk policies

---

## 13. Non-Goals for the Initial Major Project

- Replacing Prometheus, Jaeger, Grafana, or OpenTelemetry.
- Building a full commercial APM product.
- Letting an LLM execute arbitrary shell commands.
- Supporting every container orchestrator immediately.
- Supporting every telemetry backend immediately.
- Claiming full autonomous self-healing without measurable safeguards.

---

## 14. Final Demonstration Story

The final demo should tell one coherent story:

```text
Healthy application
      ↓
Controlled fault injected
      ↓
Telemetry changes
      ↓
Topology shows degradation
      ↓
EIOS detects anomaly
      ↓
Symptoms correlated into incident
      ↓
Root cause ranked
      ↓
AI explains evidence
      ↓
Recovery action proposed
      ↓
Operator approves
      ↓
Service is remediated
      ↓
EIOS verifies recovery
      ↓
Incident resolved
      ↓
Experiment metrics displayed
```

If this complete sequence works reliably for several different fault scenarios, EIOS qualifies as a strong university major project even without implementing every optional feature.
