# EIOS Target Architecture

## 1. Architectural Goal

EIOS is a control and intelligence plane that runs alongside a monitored microservice application.

The monitored application should continue to operate independently. EIOS consumes telemetry and runtime metadata, analyzes the system, and performs only explicitly approved operational actions.

---

## 2. High-Level Context

```text
┌─────────────────────────────────────────────────────┐
│                MONITORED APPLICATION                │
│                                                     │
│  frontend → checkout → payment → accounting         │
│               ↓        ↓                            │
│              cart    shipping                       │
│                                                     │
│  Emits metrics, traces, logs, business events       │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                     EIOS                            │
│                                                     │
│  Registry / Discovery                              │
│          ↓                                          │
│  Telemetry Ingestion                               │
│          ↓                                          │
│  Normalization + Storage                           │
│          ↓                                          │
│  Topology + Health                                 │
│          ↓                                          │
│  Detection                                         │
│          ↓                                          │
│  Correlation → Incident                            │
│          ↓                                          │
│  RCA → Investigation Agent                         │
│          ↓                                          │
│  Remediation Planner → Policy / Approval            │
│          ↓                                          │
│  Runtime Adapter                                   │
│          ↓                                          │
│  Verification                                      │
│                                                     │
│  Dashboard / Experiment Lab / Evaluation / Audit    │
└─────────────────────────────────────────────────────┘
```

---

## 3. Architectural Principles

1. **Sidecar intelligence, not application replacement**  
   EIOS observes the application externally wherever possible.

2. **Vendor-neutral telemetry contracts**  
   Internal services should operate on canonical EIOS data models.

3. **Application-aware and service-aware data**  
   Every important telemetry record should map to a monitored application and, when possible, a service.

4. **Deterministic intelligence before generative AI**  
   Detection, correlation, scoring, policy, and safety decisions should remain reproducible.

5. **Human control over risky actions**  
   The default remediation mode is assisted, not unrestricted autonomous control.

6. **Evidence preservation**  
   Incidents must retain links to the metrics, events, traces, logs, and actions that explain them.

7. **Evaluation by design**  
   Fault injection and ground-truth records are first-class architectural components.

---

## 4. Logical Components

### 4.1 API Gateway / Orchestrator

Responsibilities:
- authentication integration
- API aggregation
- WebSocket/SSE real-time feeds
- routing to domain services
- application/service operations
- remediation approval API

The existing FastAPI orchestrator can evolve into this control-plane API.

---

### 4.2 Application Registry

Stores:
- application identity
- runtime type
- environment
- telemetry endpoints
- configuration status
- ownership/tags

Suggested table:

```text
applications
- id
- name
- environment
- runtime_type
- status
- telemetry_config_json
- created_at
- updated_at
```

---

### 4.3 Service Catalog / Discovery

Responsibilities:
- discover services from runtime/telemetry
- associate runtime identifiers with logical services
- maintain service health state
- maintain application membership
- persist service metadata

Suggested table:

```text
services
- id
- application_id
- name
- runtime_identifier
- namespace
- language
- version
- status
- health_score
- labels_json
- first_seen_at
- last_seen_at
```

---

### 4.4 Telemetry Ingestion

Connectors:
- Prometheus metrics
- Kafka/business events
- traces from Jaeger/OpenTelemetry
- logs from OpenSearch/OpenTelemetry

The connector layer should convert source-specific data into canonical records.

---

## 5. Canonical Data Contracts

### 5.1 Normalized Telemetry Event

Conceptual schema:

```json
{
  "id": "evt_...",
  "timestamp": "...",
  "application_id": "app_...",
  "service_id": "svc_...",
  "signal_type": "metric|trace|log|business_event|runtime",
  "name": "payment.error_rate",
  "metrics": {
    "value": 0.42
  },
  "attributes": {
    "source": "prometheus"
  },
  "trace_id": null,
  "source_reference": "..."
}
```

### 5.2 Anomaly

```text
anomaly
- id
- application_id
- service_id
- detector
- signal
- severity
- score
- baseline
- observed_value
- evidence_ids
- started_at
- ended_at
- status
```

### 5.3 Incident

```text
incident
- id
- application_id
- title
- severity
- state
- started_at
- detected_at
- resolved_at
- root_cause_service_id
- root_cause_score
- summary
```

### 5.4 Incident Evidence

```text
incident_evidence
- incident_id
- evidence_type
- evidence_id
- weight
- reason
```

### 5.5 RCA Candidate

```text
rca_candidate
- incident_id
- service_id
- score
- rank
- evidence_json
```

### 5.6 Remediation Action

```text
remediation_action
- id
- incident_id
- action_type
- target_service_id
- risk
- confidence
- requested_by
- approved_by
- status
- started_at
- completed_at
- result_json
```

### 5.7 Verification Result

```text
verification_result
- id
- incident_id
- remediation_action_id
- outcome
- before_snapshot
- after_snapshot
- evaluated_at
```

---

## 6. Service Topology Engine

### Inputs
- trace spans
- service names
- source/destination relationships
- observed call frequency
- error distribution

### Internal Graph

Nodes:
- services

Edges:
- service A calls service B

Edge metadata:
- request rate
- error rate
- latency
- last observed timestamp

### Uses
- UI topology
- correlation
- RCA
- blast-radius analysis
- verification

---

## 7. Service Health Model

Each service receives a health state and optional numerical score.

Suggested states:

```text
UNKNOWN
HEALTHY
DEGRADED
CRITICAL
RECOVERING
```

Possible health inputs:
- runtime/container state
- error rate
- latency
- request rate deviation
- CPU
- memory
- anomaly count/severity
- dependency failures

The score must be reproducible and should not depend solely on an LLM.

---

## 8. Detection Engine

### Detector A — Static Rules
Examples:
- service down
- health check failure
- CPU > configured threshold
- memory threshold
- payment failure spike
- order throughput drop

### Detector B — Statistical Baseline
Per service/metric maintain a time-window baseline.

Possible methods:
- mean and standard deviation
- Z-score
- EWMA
- percentile baseline
- rate-of-change

### Detector C — ML Anomaly Detector
Optional academic enhancement.

Possible model:
- Isolation Forest

Input features may include:
- CPU
- memory
- request rate
- error rate
- P95 latency
- network activity

### Detection Output
Every anomaly must include:
- detector
- score
- reason
- evidence
- timestamp
- affected service

---

## 9. Correlation Engine

### Purpose
Convert multiple symptoms into fewer incidents.

### Inputs
- anomaly timestamps
- application/service identity
- topology relationships
- trace IDs
- error signatures
- fault windows

### Example

Raw anomalies:

```text
Payment errors high
Checkout errors high
Frontend failures high
Order rate low
Payment traces failing
```

Correlated result:

```text
Incident: Payment Path Failure
Correlated anomalies: 5
Primary affected chain: frontend → checkout → payment
```

### Initial Correlation Strategy
Use a configurable time window plus evidence similarity.

Example factors:
- occurred within N seconds
- same application
- same dependency chain
- shared failing traces
- common upstream/downstream path

---

## 10. Incident Engine

Responsibilities:
- create incidents
- assign severity
- maintain state machine
- store evidence
- store timeline events
- connect RCA, investigation, remediation, and verification

Incident states are defined in `INCIDENT_WORKFLOW.md`.

---

## 11. Root Cause Analysis Engine

RCA should rank candidate services rather than return an unexplained single answer.

Conceptual score:

```text
RCA_SCORE =
    w1 * temporal_precedence
  + w2 * anomaly_severity
  + w3 * trace_failure_concentration
  + w4 * topology_influence
  + w5 * propagation_consistency
  + w6 * known_failure_signature
```

Weights should be configurable and experimentally evaluated.

### Evidence Examples
- service produced the earliest major anomaly
- majority of failed traces pass through the service
- downstream services fail after the candidate service
- candidate has strong local error signal
- candidate matches injected ground truth

---

## 12. AI Investigation Agent

The agent sits after incident creation and deterministic evidence gathering.

### Tools

Conceptual tool interface:

```text
get_incident(id)
get_service_metrics(service_id, window)
get_service_logs(service_id, window)
get_recent_traces(service_id, window)
get_service_dependencies(service_id)
get_runtime_status(service_id)
get_rca_candidates(incident_id)
get_incident_history(service_id)
```

### Agent Output
Structured investigation:

```json
{
  "summary": "...",
  "probable_root_cause": "payment",
  "supporting_evidence": ["..."],
  "affected_services": ["checkout", "frontend"],
  "recommended_next_step": "restart_service"
}
```

The agent may recommend an action but cannot execute it directly.

---

## 13. Remediation Planner

Responsibilities:
- translate investigation result into structured action proposal
- assign risk
- validate that action is supported
- check prerequisites

Initial action catalog:

```text
restart_service
stop_service
start_service
run_health_check
capture_diagnostics
toggle_demo_fault
```

Future actions:

```text
scale_service
rollback_deployment
change_traffic_weight
```

---

## 14. Policy and Approval Layer

### Modes

**Observe**  
No remediation execution.

**Assisted**  
Recommendations require operator approval.

**Autonomous**  
Only allow-listed low-risk actions may run automatically.

### Policy Inputs
- user role
- action type
- target service
- risk level
- environment
- incident severity
- automation mode

---

## 15. Runtime Adapter

Infrastructure control must be abstracted.

```text
RuntimeAdapter
├── DockerRuntimeAdapter
└── KubernetesRuntimeAdapter (future)
```

Example interface:

```text
list_services()
get_status(service)
restart(service)
stop(service)
start(service)
get_resource_usage(service)
get_logs(service)
health_check(service)
```

This avoids coupling incident logic directly to the Docker socket.

---

## 16. Verification Engine

A remediation command returning success is not enough.

Verification compares pre-action and post-action state.

### Possible Checks
- target service is healthy
- error rate returned below acceptable baseline
- latency normalized
- request/order throughput recovered
- downstream anomalies stopped
- incident evidence is no longer active

### Verification Outcomes

```text
RECOVERED
PARTIALLY_RECOVERED
FAILED
INCONCLUSIVE
```

---

## 17. Experiment Lab Architecture

Experiment Lab is the ground-truth system for evaluation.

### Experiment Record

```text
experiment
- id
- application_id
- scenario
- target_service_id
- started_at
- ended_at
- expected_failure
- load_profile
- status
```

The existing fault-window concept can be evolved into or linked with this model.

### Initial Fault Scenarios
- payment failure
- cart failure
- product catalog failure
- memory leak
- high CPU
- Kafka queue problem
- manually stop one service

---

## 18. Storage Architecture

### PostgreSQL
Use for:
- applications
- services
- normalized metadata/events where appropriate
- anomalies
- incidents
- RCA candidates
- actions
- verification
- experiments
- audit references

### Telemetry Backends
Keep Prometheus/Jaeger/OpenSearch where appropriate rather than duplicating all raw telemetry indefinitely.

EIOS should store source references and the evidence required for reproducibility.

### Kafka
Use for event-driven internal workflows when it provides real value, for example:

```text
telemetry.normalized
anomaly.detected
incident.created
incident.updated
remediation.requested
remediation.completed
verification.completed
```

Do not introduce Kafka topics only to make the architecture look more complex.

---

## 19. Frontend Architecture

Recommended major views:

```text
Login
Dashboard
Applications
Application Detail
Service Explorer
Topology
Incidents
Incident Investigation
Experiment Lab
Evaluation
Security/Audit
Settings
```

The current desktop-style UI may be retained where useful, but the primary UX must make the operational workflow obvious.

---

## 20. Security Architecture

Required controls:
- authentication
- role-based access control
- API protection
- PII/secret redaction
- rate limiting
- append-only/tamper-evident audit records
- action approval history
- secret management through environment/configuration rather than source code

Roles:

```text
Viewer
Operator
Administrator
```

---

## 21. Deployment Strategy

### Major Project MVP
- Docker Compose
- OpenTelemetry Astronomy Shop
- EIOS services
- PostgreSQL
- Kafka
- Prometheus
- Jaeger
- OpenSearch when required

### Future
- Kubernetes adapter
- multi-application deployments
- external telemetry backends

---

## 22. Target Architecture Summary

```text
Application Registry
        ↓
Service Discovery
        ↓
Telemetry Connectors
        ↓
Canonical Telemetry Model
        ↓
Topology + Health
        ↓
Detection
        ↓
Correlation
        ↓
Incident Engine
        ↓
Deterministic RCA
        ↓
AI Investigation
        ↓
Remediation Planner
        ↓
Policy / Human Approval
        ↓
Runtime Adapter
        ↓
Verification
        ↓
Resolution + Evaluation + Audit
```
