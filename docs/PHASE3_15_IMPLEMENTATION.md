# Phases 3–15 implementation report

Original delivery status: source implementation was delivered without verification at the user's request. The user later authorized the skipped checks. See [the subsequent verification report](PHASE3_15_VERIFICATION.md) for current tests, live experiments, fixes, and remaining limitations. Statements below about unexecuted checks describe the original delivery, not the later verification run.

## Phase 3 — Service discovery and live topology

Added `workflow_topology.py`, `topology_snapshots`, and `topology_history`. The persistent application/service catalog defines the node set. Fresh Docker discovery determines confirmed offline state. Failed/stale discovery reports UNKNOWN/STALE. Normalized application-scoped metric events supply CPU cores, memory fraction, request/error rates, and p95 latency with individual source timestamps. Unknown metrics remain absent.

The topology contract contains `application_id`, `observed_at`, `state`, `services`, `edges`, `dependency_state`, source/discovery state and service changes. Each node includes stable service ID, runtime instances, status/reason, health score/penalties, metric coverage, timestamps, and event references. Dependency edges include provenance (`registered`, `jaeger_dependencies`, `scoped_trace`), observed time, and declared/observed/stale state.

Jaeger's global dependency endpoint is used only for a backend with one enabled application owner and no tag scope. Shared backends use bounded trace searches with both endpoints checked against scope tags. Failed requests preserve previously observed edges as stale. Abnormal services receive bounded trace evidence snapshots through the existing Phase 2 evidence writer.

Legacy service APIs now adapt the canonical topology, defaulting to Astronomy Shop; `application_id` selects another application. Existing ServiceGraph and ServicePanel are reused. The raw RED collector remains available internally. Manual work: discover Astronomy Shop, inspect edges, stop/restart Payment, inspect persistence and freshness.

## Phase 4 — Real-time Operations dashboard

Added `OperationsWorkspace.tsx` and `lib/operations.ts`. The desktop opens Operations by default and remembers the selected application locally. REST snapshots remain authoritative; authenticated `/ws` frames invalidate the selected application's state. Twenty-second polling remains as a fallback. The server emits application-specific invalidations when observations and analysis change. Counts come from catalog/topology and persisted incident/finding tables.

Removed fabricated healthy/service counts from the desktop header, static inventory/cloud predictions from the sidebar, and fabricated Security Center alerts/audit records. API failures show unavailable; source failures remain labelled. Reports and the existing explorer remain accessible. Manual work: compare counts, disconnect APIs/sources, observe updates without refresh.

## Phase 5 — Hybrid detection and health

Existing ingest/detect/intelligence/model files and their historical records remain intact. `workflow_analysis.py` imports real persisted legacy incidents/findings with provenance. Static objectives and statistical deviations use one `operational_anomalies` schema: application/service IDs, category, detector, score, severity, times, current values, baseline and evidence. Existing model-backed findings are labelled ML; existing forecasts keep forecast provenance. No new untrained ML model is substituted.

Statistical baselines use one source observation per minute, at least twelve observations, no gaps over three minutes, rolling mean/stddev, EWMA alpha 0.25, and positive Z-score ≥3. Metric-specific minimum scales suppress zero-variance noise. Request metrics require traffic; stale/missing observations and the first two minutes after registration suppress scoring. SHA-256 fingerprints and five-minute buckets survive process restarts.

Health is `max(0,100-sum(penalties))`. Error, latency, CPU and memory penalties have respective maxima 60, 20, 20, 40; warning/critical objectives interpolate between half and full penalty. An unhealthy Docker health result adds 60. Confirmed offline scores zero; unknown/stale data has no score. Scores reflect available metrics, whose coverage is explicit. Rankings and scores are operational heuristics, not scientific probabilities.

Manual work: normal baseline, CPU, memory, request failure, telemetry loss, restart cooldown, detector evidence/provenance.

## Phase 6 — Correlation and incidents

Created `operational_incidents`, `incident_anomalies`, and append-only `incident_timeline`. New correlated incidents reference a normal legacy `cases` record and retain all raw anomaly/legacy IDs. Existing incident IDs are not rewritten.

An application-locked writer groups anomalies within five minutes when they share a service, retrieved trace, normalized error signature, or dependency path of at most three hops. Temporal proximity alone cannot group unrelated services. Severity uses worst anomaly and escalation for propagation to three or more services. Timeline records transitions and evidence matching rules. Detection/import fingerprints and unique anomaly membership make replay idempotent.

States: DETECTED, CORRELATING, INVESTIGATING, ROOT_CAUSE_IDENTIFIED, ACTION_RECOMMENDED, AWAITING_APPROVAL, REMEDIATING, VERIFYING, RESOLVED, ESCALATED. Invalid transitions fail. Manual work: one Payment fault, count raw anomalies/correlated incidents, inspect retained evidence and application isolation.

## Phase 7 — Deterministic RCA

`rca_rankings` stores versioned candidates and component scores. Maximum component weights: temporal precedence 20; severity 20; local errors 20; resource/runtime evidence 15; affected direct callers 15; failed trace concentration 10. Only actual anomaly services become candidates. Ranking requires direct evidence and score ≥35; otherwise it abstains. Injected experiment ground truth is never an RCA input. Operator UI shows scores, breakdowns and evidence IDs.

Manual work: fault several supported services; record Top-1/Top-3, first ranking time, abstention and score explanation. No RCA accuracy is claimed by this implementation report.

## Phase 8 — Bounded AI investigation

Added `workflow_investigation.py` and persistent `investigation_runs`. Configure an Ollama-compatible local provider with `EIOS_INVESTIGATION_URL` and `EIOS_INVESTIGATION_MODEL`. Without configuration, requests persist an unavailable result and do not block incidents.

Allow-listed read-only tools: incident, service metrics, persisted logs/traces, dependencies, anomalies, RCA, and incident history. Application/service membership is validated. Six model steps, sixteen tool calls, bounded output/evidence and a sixty-second logical budget limit the agent. HTTP requests time out individually. One active investigation per incident is permitted. Interrupted runs become unavailable for explicit retry.

Structured output contains summary, affected service IDs, ranked probable cause, supporting/conflicting evidence claims with IDs, next step and uncertainty. Returned IDs and candidate membership are validated; model prose remains subject to human review. Telemetry is treated as untrusted data. There are no shell, filesystem, Docker, SQL-write or action-execution tools. Manual work: configured/unconfigured provider, malformed/unsupported outputs, missing evidence, re-investigation and record persistence.

## Phases 9–10 — Planner, approval and safe runtime

The fixed action catalog supports start, stop, restart, runtime health inspection and bounded redacted diagnostics. Recommendations are derived from deterministic RCA; the model never creates commands. Proposals reference application/service, incident, legacy approval, parameters, risk, rationale, effect, ranking score and versioned policy. Proposals expire after fifteen minutes. Medium/high-risk changes require administrator approval; low-risk read-only proposals allow operators. Decisions record the authenticated actor, not a user-supplied actor string.

`RuntimeAdapter`/`DockerRuntimeAdapter` use existing Docker SDK helpers. Execution resolves the registered service's current container ID, rechecks application discovery scope and runtime key, checks action/state, validates recorded approval and current approver authorization, and claims a unique execution before changing Docker. Critical control-plane/infrastructure targets are protected. Uncertain interrupted commands never retry automatically. Direct legacy container mutation endpoints reject requests and point to approved proposals. Existing Docker inspection remains available.

Manual work: reject/approve, inspect durable decisions, unauthorized execution, expired approvals, wrong-application target, protected services, duplicate execution and actual approved action.

## Phase 11 — Sustained recovery verification

`recovery_verifications` stores pre-action snapshots, criteria, distinct post-action samples, deadline and outcome. The default window is 180 seconds, configurable to 60–1800 seconds. Recovery requires at least three distinct good source observations spanning at least 45 seconds, healthy affected services, fresh metrics and request/error/latency evidence. `eios.verification.resource_only=true` can explicitly waive traffic for a resource-only service.

Outcomes are RECOVERED, PARTIALLY_RECOVERED, FAILED and INCONCLUSIVE. Only RECOVERED resolves the case/incident. A successful Docker call enters VERIFYING. Other terminal outcomes escalate and request new evidence. The server workflow runs these observations after deployment; no recovery experiment was executed during implementation.

## Phase 12 — Experiment Lab

Created durable experiment intents/runs with ground-truth windows, saved prior flag/runtime/load state, start/end/deadline, actor and linked evidence artifacts. Supported configured scenarios include Payment, cart, product catalog, email memory, ad CPU, Kafka queue and explicit service stop. A healthy `baseline` scenario supplies explicit negative-control runs. Unsupported flags/variants are shown as unavailable rather than guessed.

Flagd faults are limited to the configured demo application. Service-stop targets use stable catalog identity and the safe runtime resolver. A global active-run constraint prevents overlapping experiments; open legacy faults also block new experiments. Cleanup restores exact prior values, runs at deadline and resumes after failure/restart. Failed cleanup retains an open ground-truth window and prevents the next experiment. DB/file/Docker changes use durable intent and compensation, not an impossible shared transaction. Legacy fault stop now restores the fault before closing its window; legacy start serializes intent and compensates failed persistence.

Existing traffic is observed by default. Managed concurrency requires `EIOS_LOCUST_URL` and records saved/requested user counts with restoration. The API accepts duration, scenario, target, variant and load profile. The UI exposes run state, cleanup retry, artifacts and annotations. Manual work: normal baseline, Payment, CPU/memory, interrupted activation and cleanup, overlapping faults, load restoration.

## Phase 13 — Academic evaluation

Created immutable `operational_evaluations`. Actual emitted anomaly records are compared by static/statistical/ML/hybrid category, using completed fault episodes and explicit uncontaminated baseline episodes. Coverage must be at least 80%; missing observations and excluded runs are reported. Missing model deployment excludes an ML episode rather than implying a working model.

TP/FN are fault episodes with/without expected-service detection; FP/TN are baseline episodes with/without expected-service alerts. Human annotations can attribute/exclude anomaly evidence. Alert-level FP annotations are retained independently; episode metrics are not silently mixed with alert units. Precision/F1 remain null without negative controls. Unrelated symptoms are not automatically labelled false positives.

Exports include TP/FP/FN/TN, precision/recall/F1, MTTD, anomaly/incident counts and alert reduction, first-ranking Top-1/Top-3 and latency, verification success, verified MTTR, experiment duration and telemetry/processing delay. Input IDs, annotation snapshots, versioned definitions and denominators are persisted. Recommendation accuracy stays unknown without independent correctness labels. Command success never substitutes for verified recovery. JSON/CSV exports support university graphs/tables. Existing model evaluation remains available; this phase uses actual live output rather than its separate surrogate rule baseline.

No academic results were generated. Manual work: repeated baseline/fault runs, annotations, metric denominator inspection and exports.

## Phase 14 — RBAC, security and governance

Backend roles enforce viewer reads, operator investigations/proposals/experiments/approved execution and administrator application/user administration plus service-changing approvals. Machine keys default to viewer unless explicitly assigned another role. Cookie sessions and WebSockets retain server validation and origin checks. Public account actions and normal APIs have per-process bounded rate limits; distributed rate limiting is not implemented.

The previous demo recovery behavior exposed reset tokens publicly. Public forgot-password requests now return generic instructions. Administrators issue private one-time recovery tokens, or a host administrator runs `recover_password.py`. Reset consumption is row-locked and revokes all existing sessions/recovery tokens. Public signup cannot race first-administrator setup. Administrator role changes revoke sessions; self-demotion/last-admin removal is rejected.

Critical workflow actions use a serialized SHA-256 append-only governance chain. Legacy mutating APIs receive a compatibility reference; login/logout and catalog changes join the governance chain through existing audit calls. Timeline and governance records reject UPDATE/DELETE/TRUNCATE. An integrity API supports paginated manual assessment; this is tamper evidence within PostgreSQL, not an externally signed audit guarantee. Table owners/superusers can alter schemas.

Terminal/filesystem APIs are disabled by default; optional enablement requires administrator role. Filesystem boundary checks use path ancestry and block hidden/secret directories. Fake Security Center fallback data and browser API-key management UI were removed. Actual server redaction preview remains available. No permission/integrity checks were executed in this change.

## Phase 15 — Demo journey and readiness

The desktop's Operations window connects application selection, topology, anomalies, incident detail, timeline, RCA, AI investigation, deterministic recommendations, approval, Docker execution, sustained verification, experiments, evaluation exports and governance. Empty/unavailable states have explicit text. Existing Reports, registry, graph and explorer are retained.

Updated README/PROJECT and added the manual demo checklist. No visual/browser/responsive checks were executed. The deliverable is an unverified implementation candidate, not a demonstrated production-ready system.

## Known limits and future work

- All new source, migrations and interactions require the user's manual validation. No runtime accuracy, latency or reliability result is asserted.
- Legacy name-based intelligence/models remain limited to Astronomy Shop; new static/statistical workflows use application IDs. Model training is not automatically enabled for arbitrary applications.
- Correlation uses a five-minute heuristic and up-to-three-hop dependencies. It can under-group sparse evidence or over-group independent failures on the same chain; parameters need experimental tuning.
- Statistical thresholds and RCA weights are engineering choices; their quality has not been measured. Existing detector duplicates remain preserved as raw provenance.
- Jaeger evidence is bounded and depends on retention/sampling. Shared-backend trace-derived dependency searches examine a bounded subset; missing edges stay unknown.
- PostgreSQL and Docker/Flagd are not one transaction. Intents, unique claims and compensation reduce ambiguity but cannot eliminate failures between external side effects and DB commits. Operator inspection is required for uncertain actions and failed cleanup.
- Experiments require a running orchestrator for automatic deadline cleanup; prolonged downtime extends fault exposure until recovery/manual cleanup. An independent fault watchdog is future work.
- Restarting Payment does not clear a persistent Flagd failure. Expect FAILED/INCONCLUSIVE unless the fault condition is removed. Experiment cleanup is distinct from approved remediation and must be considered when attributing recovery.
- Recovery currently uses generic health objectives and an explicit resource-only override. Additional service-specific business SLOs need configuration/design.
- AI needs a configured model supporting structured tool calls. Citation validation checks IDs, not the semantic truth of every generated sentence.
- Existing traffic is not assigned a fabricated user count. Managed load requires a reachable configured Locust control endpoint.
- Evaluations use experiment episodes, not per-second classification. MTTR includes fault duration/cleanup and cannot by itself establish causal remediation benefit.
- Topology history is append-only observation storage without automated retention. Configure operational retention after measuring storage needs.
- Rate limits are per process; distributed quotas, independent signed audit anchors, granular per-application user grants, Kubernetes, scaling and autonomous remediation are future work.

## Deployment boundary

Changes were authored in `C:\Users\Krisss\Documents\eios2`. The older `C:\Users\Krisss\Documents\EIOS` running checkout was read for architecture documents but was not updated/restarted for Phases 3–15. Build/start the intended checkout manually. Do not start two checkouts with the same container names or remove database volumes.
