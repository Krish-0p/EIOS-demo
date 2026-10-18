# EIOS Codex Instructions

## Project Identity

EIOS (Enterprise Intelligence Operating System) is a university major project for intelligent monitoring, incident investigation, and controlled remediation of distributed microservice applications.

The OpenTelemetry Astronomy Shop is the primary demonstration environment. EIOS must, however, be designed as a generic observability and reliability control plane rather than as an Astronomy-Shop-specific dashboard.

## Read Before Significant Work

Before planning or implementing a significant feature, read the relevant project documents:

- `PROJECT.md` — current implemented state of EIOS.
- `README.md` — repository usage and startup information.
- `docs/EIOS_VISION.md` — target product vision and required user experience.
- `docs/EIOS_ARCHITECTURE.md` — target logical architecture and component responsibilities.
- `docs/INCIDENT_WORKFLOW.md` — incident lifecycle from detection to verified recovery.
- `docs/EVALUATION_PLAN.md` — experimental methodology and university evaluation requirements.
- `PLANS.md` — implementation roadmap and phase boundaries.

Treat `PROJECT.md` and the actual repository code as the source of truth for what currently exists. Treat the files under `docs/` as the target design.

## Core Product Goal

EIOS must implement the following closed-loop reliability workflow:

Telemetry Collection
→ Normalization
→ Service Health Analysis
→ Anomaly Detection
→ Alert Correlation
→ Incident Creation
→ Root Cause Analysis
→ AI-Assisted Investigation
→ Remediation Recommendation
→ Human Approval / Policy Decision
→ Controlled Remediation
→ Recovery Verification
→ Incident Resolution
→ Evaluation and Audit

Every major feature should support this workflow.

## Required Administrator Experience

The intended administrator flow is:

1. Log in to EIOS.
2. Create or register an application.
3. Add or discover the application's microservices.
4. Configure supported telemetry connections.
5. View all onboarded services and their live health.
6. Inspect metrics, traces, logs, events, dependencies, and service topology.
7. Use the Experiment Lab to stop a service or inject a supported fault in the demo environment.
8. Observe the impact on EIOS in real time.
9. See related alerts correlated into a single incident.
10. See probable root cause rankings with supporting evidence.
11. Receive an AI-assisted explanation and remediation recommendation.
12. Approve or reject controlled remediation actions.
13. Observe EIOS verify whether the system recovered.
14. Review the complete incident timeline, audit trail, and experiment results.

## Architecture Principles

- Keep EIOS logically separate from the monitored application.
- Do not rewrite OpenTelemetry Demo business logic unless required for instrumentation or controlled experiments.
- Prefer OpenTelemetry-compatible interfaces and vendor-neutral telemetry contracts.
- Avoid hard-coding core EIOS logic specifically to Astronomy Shop.
- Separate telemetry acquisition, normalization, intelligence, incidents, investigation, remediation, and presentation concerns.
- Prefer deterministic algorithms for anomaly scoring, correlation, RCA scoring, policies, approval checks, and safety decisions.
- Use LLMs for investigation assistance, explanation, summarization, and structured recommendations rather than for unrestricted infrastructure control.
- LLM output must never directly execute arbitrary shell commands.
- Infrastructure actions must pass through an allow-listed remediation/orchestration layer.
- Destructive or high-risk operations require explicit approval unless a documented low-risk automation policy allows them.
- All important actions must be auditable.
- Preserve currently working functionality while evolving the architecture incrementally.

## Engineering Rules

For significant changes:

1. Inspect the current implementation first.
2. Identify the relevant existing files, services, APIs, schemas, and dependencies.
3. Compare the current implementation with the target design.
4. Propose a concise implementation plan before making broad architectural changes.
5. Define acceptance criteria before implementation.
6. Prefer incremental changes over uncontrolled rewrites.
7. Keep changes scoped to the approved phase in `PLANS.md`.
8. Add or update tests when practical.
9. Build or run the affected components when practical.
10. Verify behavior using observable evidence rather than assuming success.
11. Update project documentation when architecture or interfaces materially change.
12. Do not automatically begin the next roadmap phase after finishing the current phase.

## Safety and Repository Rules

- Do not expose, log, commit, or hard-code secrets or API keys.
- Do not commit, push, publish, deploy, or delete important data unless explicitly requested.
- Do not execute destructive Docker, database, filesystem, or Git operations unless explicitly requested or required by a clearly approved task.
- Do not remove existing functionality merely because a redesign would be cleaner.
- Do not claim a feature is complete without verification.

## Definition of Major-Project Quality

A feature is not complete merely because a UI exists.

Prefer end-to-end functionality that can be demonstrated and measured. For example, a valid incident-management feature should prove that EIOS can detect a controlled failure, correlate evidence, identify a probable cause, recommend an action, perform an approved remediation, and verify recovery.

The final system should be technically explainable during a university viva and experimentally evaluable using metrics such as precision, recall, F1 score, root-cause accuracy, MTTD, MTTR, alert reduction, and remediation success rate.
