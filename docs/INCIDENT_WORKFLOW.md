# EIOS Incident Workflow

## 1. Purpose

This document defines the complete lifecycle of an EIOS incident.

The important design rule is that an incident is not simply an alert shown in the UI. It is a stateful operational record that begins with abnormal evidence and ends only after resolution or explicit closure.

---

## 2. Incident State Machine

Recommended states:

```text
DETECTED
   ↓
CORRELATING
   ↓
INVESTIGATING
   ↓
ROOT_CAUSE_IDENTIFIED
   ↓
ACTION_RECOMMENDED
   ↓
AWAITING_APPROVAL
   ↓
REMEDIATING
   ↓
VERIFYING
   ↓
RESOLVED
```

Alternative terminal states:

```text
REJECTED
ESCALATED
FAILED_REMEDIATION
MANUALLY_CLOSED
```

---

## 3. Stage 1 — Detection

### Trigger
One or more detectors produce anomalies.

Example:

```text
14:32:08 payment.error_rate = 49%
14:32:09 checkout.error_rate increased
14:32:10 order_rate decreased
```

### Required Output
- anomaly ID
- detector
- affected service
- score/severity
- observed value
- baseline/threshold
- evidence references
- timestamp

---

## 4. Stage 2 — Correlation

The correlation engine evaluates recent anomalies and determines whether they represent the same operational problem.

### Correlation Evidence
- same application
- close timestamps
- shared topology path
- shared failed traces
- matching error pattern
- same controlled experiment/fault window

### Example

Instead of:

```text
Alert 1: payment errors
Alert 2: checkout errors
Alert 3: frontend errors
Alert 4: order rate low
```

EIOS creates:

```text
INC-1042 — Payment Path Failure
Correlated anomalies: 4
Affected path: frontend → checkout → payment
```

---

## 5. Stage 3 — Incident Creation

When evidence crosses incident criteria, create an incident.

### Minimum Incident Fields

```text
ID
Application
Title
Severity
State
Detected time
First evidence time
Affected services
Correlated anomaly IDs
Current RCA candidates
```

### Severity
Initial suggested levels:

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

Severity should be based on measurable impact, not solely on LLM interpretation.

---

## 6. Stage 4 — Evidence Collection

For each affected/candidate service, collect relevant evidence within a bounded time window.

### Evidence Types
- service metrics
- runtime/container state
- traces
- logs
- business events
- dependency edges
- recent restarts
- related historical incidents

The incident should retain references to the exact evidence used during RCA.

---

## 7. Stage 5 — Root Cause Analysis

The deterministic RCA engine calculates ranked candidates.

Example:

```text
Candidate            Score
Payment              0.94
Checkout             0.41
Frontend             0.14
```

### Evidence for Payment

```text
+ Earliest major anomaly occurred in payment.
+ Majority of failing checkout traces include payment.
+ Payment error rate increased before downstream symptoms.
+ Checkout CPU and memory remained normal.
+ Topology places payment downstream of checkout.
```

The UI must make this evidence visible.

---

## 8. Stage 6 — AI-Assisted Investigation

The investigation agent receives:
- incident metadata
- RCA ranking
- approved telemetry tools
- bounded time window

### Agent Responsibilities
- summarize what changed
- explain the likely failure chain
- retrieve additional approved evidence when necessary
- identify uncertainty
- recommend the next safe operational step

### Agent Must Not
- invent missing data
- execute infrastructure commands directly
- claim certainty unsupported by evidence

### Example Output

```text
The payment service is the strongest root-cause candidate.
Payment produced the earliest major error increase and appears in most failed checkout traces. Checkout degradation began after the payment anomaly, suggesting downstream propagation rather than checkout being the original source.
```

---

## 9. Stage 7 — Remediation Recommendation

The remediation planner creates a structured proposal.

Example:

```json
{
  "action": "restart_service",
  "target": "payment",
  "risk": "LOW",
  "confidence": 0.91,
  "reason": "Service error spike with high-confidence RCA and no evidence of upstream dependency failure"
}
```

The action must exist in the allow-listed action catalog.

---

## 10. Stage 8 — Approval

Default major-project mode: **Assisted**.

UI:

```text
Recommended Action
Restart Payment Service

Risk: LOW
Confidence: 91%

[Approve]
[Reject]
[View Evidence]
```

### Audit Record
Record:
- user
- time
- incident
- proposed action
- decision
- optional reason/comment

---

## 11. Stage 9 — Remediation

After approval, the runtime adapter executes the structured action.

Example:

```text
DockerRuntimeAdapter.restart("payment")
```

Do not allow arbitrary LLM-generated shell commands.

### Execution Record
Record:
- action start time
- action end time
- runtime response
- success/failure
- diagnostics

A successful runtime command does not automatically resolve the incident.

---

## 12. Stage 10 — Verification

After remediation, EIOS enters `VERIFYING`.

### Before Snapshot
Example:

```text
payment health: CRITICAL
error rate: 49%
p95 latency: 1800 ms
order rate: 42/min
```

### After Snapshot
Example:

```text
payment health: HEALTHY
error rate: 1.5%
p95 latency: 430 ms
order rate: 121/min
```

### Verification Criteria
Possible checks:
- target service running and healthy
- error rate below recovery threshold
- latency near baseline
- request/business throughput recovered
- related downstream anomalies cleared

### Outcomes

```text
RECOVERED
PARTIALLY_RECOVERED
FAILED
INCONCLUSIVE
```

---

## 13. Stage 11 — Resolution

Incident may enter `RESOLVED` only when:
- verification succeeds, or
- an authorized operator explicitly closes it with a reason.

### Resolution Record
Store:
- resolution time
- successful action
- verification evidence
- MTTD
- remediation time
- MTTR
- final root cause

---

## 14. Failed Remediation

If verification fails:

```text
REMEDIATING
   ↓
VERIFYING
   ↓
FAILED_REMEDIATION
```

Then EIOS may:
- propose another approved action
- request more investigation
- escalate to an operator

Example:

```text
Restart completed, but payment error rate remains high.
Recovery verification failed.
Recommended next step: capture diagnostics and inspect upstream dependency.
```

---

## 15. Incident Timeline

Every stage should append a timeline event.

Example:

```text
14:32:08  Payment anomaly detected
14:32:10  Four related anomalies correlated
14:32:11  INC-1042 created
14:32:14  RCA ranked Payment first (0.94)
14:32:18  Investigation completed
14:32:20  Restart recommended
14:32:26  Restart approved by operator
14:32:27  Payment restart executed
14:32:40  Verification started
14:33:02  Telemetry normalized
14:33:04  Incident resolved
```

This timeline is important for both demo quality and academic measurement.

---

## 16. Demonstration Scenario — Service Stop

This is the simplest end-to-end demo.

### Initial State

```text
frontend        HEALTHY
checkout        HEALTHY
payment         HEALTHY
cart            HEALTHY
```

### Experiment
Admin opens Experiment Lab and selects:

```text
Target: payment
Action: Stop Service
```

### Expected Runtime Effect

```text
payment container stops
```

### Expected Telemetry Effect

```text
payment unavailable
checkout errors increase
failed traces include payment path
order throughput decreases
```

### Expected EIOS Behavior

```text
Payment topology node → red
Checkout topology node → degraded
Anomalies detected
Related anomalies correlated
Incident created
Payment ranked as root cause
Investigation explanation generated
Restart payment recommended
Admin approves
Payment restarted
Verification confirms recovery
Incident resolved
```

This scenario should work reliably before more sophisticated fault scenarios are considered complete.

---

## 17. Demonstration Scenario — Resource Fault

Example: email memory leak or ad high CPU.

Expected behavior:
- resource detector identifies abnormal usage
- topology impact may remain local initially
- incident evidence includes resource history
- RCA identifies the affected service
- remediation recommendation is appropriate to the scenario

This demonstrates that EIOS can handle both transaction failures and infrastructure/resource anomalies.

---

## 18. Required Real-Time UI Behavior

During an active incident, the UI should update without manual refresh where practical.

Important real-time elements:
- service health
- topology node state
- active anomaly count
- incident state
- incident timeline
- remediation execution status
- verification result

Use WebSockets/SSE or the existing real-time mechanism consistently.

---

## 19. Incident Quality Rules

An incident should not be created from every small metric deviation.

Use:
- detector severity
- persistence/duration
- multiple supporting signals
- correlation confidence
- cooldown/deduplication

The objective is to reduce alert noise rather than reproduce it in another UI.

---

## 20. Incident Success Criteria

For a controlled experiment, an ideal EIOS incident should demonstrate:

```text
Correct detection
+ correct correlation
+ correct affected-service set
+ correct root-cause ranking
+ understandable explanation
+ safe remediation proposal
+ auditable approval
+ successful controlled execution
+ measurable recovery verification
```
