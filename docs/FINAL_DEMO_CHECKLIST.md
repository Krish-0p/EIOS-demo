# EIOS manual demo validation checklist

This is the original manual checklist. The user subsequently authorized automated and live verification; measured results are maintained in [PHASE3_15_VERIFICATION.md](PHASE3_15_VERIFICATION.md). Unchecked items here are not a current execution log.

## Prepare and preserve data

- [ ] Use the intended checkout and existing PostgreSQL volume. Save a database backup through your normal backup process.
- [ ] Build/recreate EIOS orchestrator/dashboard manually using the existing Compose files. Do not use `down -v` or delete volumes.
- [ ] Confirm existing migrations followed by `auth-recovery-v1` and `workflow-v1` apply. Confirm existing event/incident/case/approval IDs and history remain available.
- [ ] Configure `EIOS_INVESTIGATION_URL`/`EIOS_INVESTIGATION_MODEL` if AI investigation is part of the demonstration. Confirm the model supports Ollama structured tool calls.
- [ ] Leave `EIOS_ENABLE_ADMIN_WORKSPACE=false` for the primary demonstration. Configure managed Locust only if explicitly needed.
- [ ] If the administrator password is lost, run `docker exec -it eios-orchestrator python recover_password.py --username admin --issue-token` manually. Paste the private token into “I have a recovery token”; choose a new password. Never publish the token.

## Identity and application

- [ ] Verify sign-in and session restoration after browser refresh; verify sign-out revokes the session.
- [ ] Verify first-admin setup, viewer self-signup and administrator creation of an operator account.
- [ ] Verify viewer mutation requests fail on the server; operator cannot administer users/apps or approve service changes.
- [ ] Select Astronomy Shop in Operations. Verify service count against registered catalog membership.
- [ ] Discover services. Confirm runtime identity, telemetry timestamps/units, source availability and dependency provenance.
- [ ] Stop/restart a registered application service manually. Confirm it remains visible as OFFLINE, then recovers.
- [ ] Disable a source temporarily; confirm UNKNOWN/STALE/UNAVAILABLE rather than healthy fabricated values.

## Normal baseline

- [ ] Establish stable existing traffic and fresh telemetry.
- [ ] Run an explicit `baseline` experiment for a duration sufficient for at least several observations.
- [ ] Record normal anomalies if any. Confirm no startup/insufficient-history baseline score is invented.
- [ ] Leave a five-minute recovery buffer between faults and healthy negative controls.

## Controlled Payment demonstration

- [ ] Choose a supported Payment scenario/variant and the registered Payment service. Record experiment ID and expected service.
- [ ] Record confirmed fault start time and telemetry change.
- [ ] Observe topology state and operational counters without refreshing the browser.
- [ ] Record first anomaly detection, detector/category, event/trace references and baseline/current measurements.
- [ ] Record correlated incident creation time, raw anomaly count, grouped service set and correlation reasons.
- [ ] Inspect incident timeline and persisted legacy case linkage.
- [ ] Record first RCA time, Top-1/Top-3, score breakdown and abstention behavior. Never label scores as calibrated probabilities.
- [ ] Request AI investigation. Confirm all cited IDs exist, missing logs/traces are acknowledged and no tool can change infrastructure.
- [ ] Generate a deterministic recommendation. Record action, target ID, rationale, risk and expiry.
- [ ] Reject one proposal and confirm the decision persists without executing Docker.
- [ ] Generate another proposal; administrator approves. Confirm operator-only approval fails for service changes.
- [ ] Confirm unapproved/expired/repeated/wrong-application/protected-target actions fail.
- [ ] Execute the approved action. Record command start/end, approving/executing actor and target container.
- [ ] Confirm command acceptance enters VERIFYING and does not immediately resolve the incident.
- [ ] If Flagd failure remains active, confirm a restart alone does not falsely prove recovery. Record experiment cleanup separately.
- [ ] Clear the actual fault through Experiment Lab cleanup. Confirm its ground-truth end time is recorded only after restoration.
- [ ] Observe at least three fresh good source observations sustained for at least 45 seconds. Confirm before/after measurements and actual verification outcome.
- [ ] Confirm only RECOVERED resolves the incident/case; FAILED/PARTIALLY_RECOVERED/INCONCLUSIVE escalate.

## Failure and restart scenarios

- [ ] Exercise CPU and memory scenarios supported by the real flag configuration.
- [ ] Stop the orchestrator during an active experiment; restart it and confirm cleanup resumes.
- [ ] Exercise failed cleanup; confirm the open ground-truth window and overlap protection remain.
- [ ] Exercise interrupted execution; confirm no automatic duplicate Docker action occurs.
- [ ] Observe AI provider failure and workflow analysis failure without breaking existing ingest/detection.
- [ ] Confirm stale snapshots are not accepted as current health and missing telemetry cannot establish recovery.

## Academic evaluation and audit

- [ ] Run repeated healthy baseline and fault episodes under documented traffic conditions.
- [ ] Add independent TP/FP/exclusion annotations with rationale where needed.
- [ ] Generate a persisted evaluation and inspect coverage, denominators, excluded episodes and exact input IDs.
- [ ] Verify precision/F1 remain unavailable without usable negative controls; no trained-model result is inferred from absent model output.
- [ ] Export JSON/CSV; reproduce TP/FP/FN, MTTD, alert reduction, RCA accuracy, verification success and MTTR from saved records.
- [ ] Record timings: fault start, detection, incident creation, first RCA, approval, execution, fault clear and verified recovery.
- [ ] Load governance audit and assess every page of the chain. Inspect login, registry, experiment, proposal/decision, execution, verification and evaluation history.
- [ ] Run the complete journey more than once and record machine/load/model versions and limitations.

## UI and final readiness

- [ ] Exercise loading, empty, unavailable and stale states on the actual presentation machine.
- [ ] Confirm application switching never displays another application's pending response.
- [ ] Confirm keyboard navigation, narrow layouts, long identifiers, scrollable graph and incident details are usable.
- [ ] Confirm Reports and Service Explorer still expose existing persisted history.
- [ ] Record failures and fixes before calling the project demo-ready. Until these checks are complete, readiness remains unverified.
