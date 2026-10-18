# EIOS Evaluation Plan

## 1. Purpose

EIOS is a university major project, so its quality should be demonstrated through repeatable experiments and measurable outcomes rather than screenshots alone.

The evaluation framework should answer:

1. Does EIOS detect controlled failures reliably?
2. How quickly does it detect them?
3. Does correlation reduce alert noise?
4. Does root-cause analysis identify the correct failing service?
5. Does remediation reduce recovery time?
6. Does EIOS verify recovery correctly?
7. How do different detection techniques compare?

---

## 2. Research Question

Recommended primary research question:

> How effectively can a hybrid observability intelligence platform detect, correlate, diagnose, and assist recovery from controlled failures in distributed microservice applications?

Possible secondary question:

> Does combining static rules with dynamic statistical anomaly detection improve failure detection quality compared with fixed thresholds alone?

---

## 3. Experimental Environment

Primary system under test:
- OpenTelemetry Astronomy Shop

Operations platform:
- EIOS

Runtime:
- Docker Compose for the main major-project implementation

Observability/data sources may include:
- OpenTelemetry
- Prometheus
- Jaeger
- Kafka
- OpenSearch/log backend where used

Traffic generation:
- existing Astronomy Shop load generator / Locust where applicable

---

## 4. Ground Truth

Every controlled experiment must create a ground-truth record.

Minimum fields:

```text
experiment_id
scenario
application
expected_root_cause_service
fault_start_time
fault_end_time
load_level
expected_failure_type
```

The existing EIOS fault-window mechanism should be reused or extended rather than replaced without reason.

---

## 5. Fault Scenarios

Initial evaluation scenarios:

### F1 — Payment Failure
Expected root cause: payment service.

Expected symptoms:
- payment errors
- checkout failures
- failed traces
- reduced successful orders

### F2 — Cart Failure
Expected root cause: cart service.

### F3 — Product Catalog Failure/Latency
Expected root cause: product-catalog service.

### F4 — Email Memory Leak
Expected root cause: email service.

### F5 — Ad High CPU
Expected root cause: ad service.

### F6 — Kafka Queue/Backpressure Problem
Expected root cause/domain: Kafka/event-processing path.

### F7 — Explicit Service Stop
Stop one selected container to provide a simple, deterministic service-down scenario.

---

## 6. Load Profiles

Run scenarios under more than one traffic level where feasible.

Example profiles:

```text
LOW
NORMAL
HIGH
```

Exact concurrency should be chosen based on the available machine and baseline stability.

The same scenario should be repeatable with the same configured load profile.

---

## 7. Detection Methods to Compare

### Baseline A — Static Threshold Rules
Examples:
- CPU threshold
- memory threshold
- error-rate threshold
- health-check failure

### Baseline B — Dynamic Statistical Detection
Examples:
- rolling average
- rolling standard deviation
- Z-score
- EWMA

### Candidate C — Hybrid EIOS Detection
Combination of:
- static rules
- statistical baseline
- optional ML score
- persistence/deduplication logic

### Optional Candidate D — Isolation Forest
Use only if the implementation is stable enough to evaluate fairly.

---

## 8. Detection Metrics

### True Positive (TP)
A relevant incident/anomaly is generated for an active ground-truth fault.

### False Positive (FP)
A relevant incident/anomaly is generated when no matching fault is active.

### False Negative (FN)
A fault occurs but EIOS fails to produce the expected detection.

### Precision

```text
Precision = TP / (TP + FP)
```

### Recall

```text
Recall = TP / (TP + FN)
```

### F1 Score

```text
F1 = 2 × (Precision × Recall) / (Precision + Recall)
```

### False Positive Rate
Track unexpected anomaly/incident generation during healthy control periods.

---

## 9. Time Metrics

### Mean Time to Detect (MTTD)

```text
MTTD = detection_time - fault_start_time
```

Calculate the mean across repeated runs.

### Incident Creation Latency

```text
incident_created_at - first_relevant_anomaly_at
```

### Investigation Latency

```text
investigation_completed_at - incident_created_at
```

### Remediation Execution Time

```text
remediation_completed_at - remediation_started_at
```

### Mean Time to Recovery (MTTR)

```text
MTTR = verified_recovery_time - fault_start_time
```

For assisted mode, optionally also report operator approval delay separately so human delay is not confused with system execution time.

---

## 10. Correlation Metrics

### Alert Reduction Ratio

```text
Alert Reduction = 1 - (number_of_incidents / number_of_raw_related_alerts)
```

Also report:
- raw anomaly count
- correlated incident count
- incorrectly merged incidents
- incorrectly split incidents

A useful correlation system should reduce noise without hiding distinct simultaneous failures.

---

## 11. RCA Metrics

Because experiments have known root causes, RCA can be measured directly.

### Top-1 RCA Accuracy

```text
Correct if expected root cause is ranked #1.
```

### Top-3 RCA Accuracy

```text
Correct if expected root cause appears in the first three candidates.
```

### Mean Reciprocal Rank (Optional)
Useful when ranking quality matters.

### RCA Latency

```text
rca_completed_at - incident_created_at
```

---

## 12. Remediation Metrics

### Recommendation Correctness
For known experiment scenarios, record whether the proposed action is appropriate.

### Remediation Success Rate

```text
successful_verified_recoveries / executed_remediations
```

### Failed Remediation Rate
Record actions that executed but did not restore service health.

### Verification Accuracy
Compare EIOS verification result with observed ground truth.

---

## 13. Experiment Matrix

A minimum useful experiment matrix could be:

```text
7 fault scenarios
× 3 repetitions
× 2 load profiles
= 42 fault runs
```

If system resources permit:

```text
7 scenarios
× 5 repetitions
× 3 load profiles
= 105 fault runs
```

Choose the final matrix based on available hardware and semester time. Consistency is more important than inflating the number of runs.

---

## 14. Healthy Control Runs

Include periods where no fault is injected.

Purpose:
- measure false positives
- establish normal telemetry baselines
- test whether detectors remain quiet under expected traffic variation

---

## 15. Data to Persist Per Experiment

```text
experiment metadata
fault start/end
load profile
raw anomalies
correlated incidents
incident timestamps
RCA rankings
AI investigation output
recommended action
approval timestamps
execution timestamps
verification snapshots
final outcome
```

This makes results reproducible and enables automatic metric calculation.

---

## 16. Evaluation Dashboard

Recommended sections:

### Overview
- total experiments
- successful detections
- missed detections
- false positives
- successful recoveries

### Detection
- precision
- recall
- F1
- MTTD

### Correlation
- average alerts per incident
- alert reduction ratio

### RCA
- top-1 accuracy
- top-3 accuracy
- average RCA latency

### Recovery
- remediation success rate
- average MTTR
- before/after service health

### Scenario Breakdown
Show results per fault type.

---

## 17. Detector Comparison Table

The final report should be able to produce a table similar to:

```text
Detector              Precision   Recall   F1   MTTD
Static Rules          measured    measured measured measured
Dynamic Baseline      measured    measured measured measured
Hybrid EIOS           measured    measured measured measured
```

Do not insert made-up values in the final report. All values must come from actual experiment runs.

---

## 18. RCA Comparison Table

Example structure:

```text
Scenario                Expected Root Cause    Rank    Correct Top-1
Payment Failure         payment                measured yes/no
Cart Failure            cart                   measured yes/no
High CPU                ad                     measured yes/no
Memory Leak             email                  measured yes/no
```

---

## 19. Recovery Comparison

Where practical, compare:

### Manual Workflow
Operator uses raw tools and manually identifies/recovers service.

### EIOS-Assisted Workflow
EIOS detects, correlates, performs RCA, recommends action, and verifies recovery.

Measure:
- time to identify likely cause
- number of tools/screens used
- time to recovery

This comparison should be clearly labeled as an experimental workflow comparison, not a universal claim about commercial observability platforms.

---

## 20. Provisional Engineering Targets

These are development goals, not claimed final results.

Suggested targets for a stable demo:

```text
Controlled service-down detection: reliable across repeated runs
Incident created within seconds of persistent failure evidence
Known fault appears in RCA top-3 for most experiment runs
Recovery verification correctly distinguishes successful vs failed recovery
No arbitrary infrastructure action bypasses approval/policy controls
```

Numerical thresholds should be finalized only after baseline testing.

---

## 21. Threats to Validity

The final report should acknowledge limitations:

- Astronomy Shop is a demo environment rather than production infrastructure.
- Controlled faults may be easier to label than real-world incidents.
- Results on one machine/load profile may not generalize to all deployments.
- LLM investigation quality can vary by model.
- Docker Compose results do not automatically prove Kubernetes-scale behavior.
- Some telemetry signals may be unavailable or delayed.

Explicitly documenting these limitations improves the academic quality of the project.

---

## 22. Minimum Evaluation Required for Final Submission

At minimum, the final EIOS submission should demonstrate:

1. Several repeatable controlled fault types.
2. Ground-truth fault windows/experiments.
3. Automatic detection metrics.
4. MTTD measurement.
5. Alert correlation results.
6. RCA accuracy measurement.
7. At least one end-to-end remediation + verification scenario.
8. Experiment history visible in the system.
9. Results generated from real EIOS data rather than manually entered numbers.
