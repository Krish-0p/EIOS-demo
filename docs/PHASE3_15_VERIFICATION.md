# Phase 3–15 verification

Verification began on 18 October 2026 and remains in progress. Experiment times below are UTC; India Standard Time is UTC+05:30. This report distinguishes automated checks, live evidence, and unverified behavior.

## Main directory and preservation

The main project is **C:/Users/Krisss/Documents/EIOS**, confirmed by the user. Initial work used the IDE-provided eios2 directory. Inspection established that EIOS contained Phase 2 code while Phase 3–15 source existed in eios2. Phase source and verification fixes were transferred after backing up EIOS. Its original architecture documents and roadmap were preserved. Further work uses EIOS.

Live orchestrator workspace and Flagd mounts now resolve to EIOS. Compose retains the opentelemetry-demo project and original opentelemetry-demo_eios-pgdata volume. Unchanged demo containers retain creation-time directory labels; these labels do not select active EIOS source. Demo business logic was not rewritten.

Artifacts outside the project:

- C:/Users/Krisss/.codex/tmp/eios-verification-20261018/eios-pre-verification.dump — 41,618,623-byte PostgreSQL archive.
- C:/Users/Krisss/.codex/tmp/eios-verification-20261018/eios-root-before-sync/ — original EIOS source before transfer, excluding environment secrets.
- C:/Users/Krisss/.codex/tmp/eios-verification-20261018/live-evidence.json — resumable live evidence. Earlier copies preserve fuller observations; PostgreSQL is authoritative.

The archive was restored into a disposable database. Comparison found zero missing original keys: 110,184 events, 1,935 incidents, 99 cases, 14,971 feature windows, and 1,711 insights. There were zero original approvals. Verification approvals are additional records. All five migration versions are present: intelligence-v1, phase1-v1, auth-recovery-v1, phase2-v1, workflow-v1. Replay/preservation tests passed.

## Automated results

168 tests passed across seven suites. Docker and provider mocks in integration tests are not counted as live actions.

| Suite | Passed | Scope |
| --- | ---: | --- |
| Account/catalog | 17 | Sessions, revocation, expiry, origins, discovery, identities, private one-time recovery, signup roles, role changes, quotas |
| Telemetry | 17 | Identity, replay, units, source/evidence boundaries, outage states, isolation |
| Intelligence | 59 | Collection, clocks, features, analytics, model lifecycle, storage, outbox, replay, chat, transient commit retries |
| API compatibility | 6 | Persisted findings, feedback, cases, decisions, truthful empty model state |
| Workflow | 32 | Correlation, statistical history, RCA/abstention, approval safety, protected targets, once-only/interrupted execution, recovery outcomes/deadlines, cleanup retry, evaluation arithmetic/contamination, audit immutability, Groq protocol |
| Security | 10 | Redaction and quotas |
| Dashboard | 27 | Session restoration, registry, stale/unavailable state, pending requests, application switching |

Workflow and dashboard suites were rerun from EIOS after transfer. TypeScript/Vite production and Docker builds passed. Vite warns about an approximately 544 kB JavaScript bundle before gzip.

An intelligence rerun initially failed because its disposable database contained a separate API suite's fixtures. Rerunning on a fresh dedicated database passed 56/56. No live application data was cleared.

## Fixes established by verification

1. Baselines no longer create injected-fault windows or false ground-truth labels.
2. Evaluation's six-variable/seven-value assignment crash was fixed. Exact episode arithmetic is regression-tested.
3. Negative-control contamination now includes legacy fault windows for the Flagd application.
4. CPU cores now use rate(container_cpu_usage_nanoseconds_total[1m]) / 1e9. Exporter utilization cannot establish cores. Legacy values/history remain untouched; missing counters do not fabricate cores.
5. Operations pending requests are scoped to application and epoch, preventing switching stalls and late cross-application replacement.
6. Older fixtures now load complete migrations and assert current Security Center behavior.
7. Groq supports bounded read-only tools, persisted results, validated evidence IDs, and private environment configuration. The former model default was unavailable; live model listing confirmed openai/gpt-oss-20b is available.
8. Diagnostic evidence was bounded to avoid exhausting the 300 MB orchestrator limit; complete observations remain in PostgreSQL.
9. Recovery could previously count samples captured after its deadline. Such samples are now excluded. Compose defaults to a 600-second observation window because five-minute request metrics plus sustained fresh samples cannot reliably fit a 180-second window. Existing records retain their original deadlines.
10. A real Kafka NOT_COORDINATOR offset-commit error restarted intelligence once. Transient coordinator/rebalance errors now retain pending commits and retry while continuing polling; permanent authorization failures still propagate. Three regression tests passed and the intelligence image was rebuilt/restarted.

Historical CPU-core values before correction remain unsuitable for clean model training or mixed-period accuracy claims.

## Live verification

- PostgreSQL connectivity, fresh metrics, actual business orders, feature windows, findings, cases, anomalies, RCA rankings, approvals and executions were observed.
- Kafka availability and real order ingestion recovered after checkout restart; a later sample showed 31 business events in five minutes.
- Prometheus, Jaeger and OpenSearch returned real metrics/dependencies/traces/logs. All four configured source kinds reported connected/fresh.
- Ten operational/report APIs passed. Administrator/operator/viewer login and logout passed through the dashboard proxy. A real operations WebSocket frame passed through that proxy.
- Viewer mutations, operator governance access, operator service-change approvals, invalid origins, unauthenticated reads, and direct Docker mutation bypass were rejected.
- Administrator docker ps returned actual container inventory and exit code 0.
- Temporarily disabled Jaeger reported unknown; its original configuration was restored.
- Ad/checkout/payment trace and log requests returned persisted, correctly scoped evidence. Sample Reports insight IDs were found in PostgreSQL.
- Rejected proposals stayed blocked. Approved actions entered VERIFYING with actor/container records. Ineffective actions became FAILED/ESCALATED rather than falsely resolving.
- Stopped checkout remained OFFLINE under service ID 7ca05049-9579-5904-b4d7-f3ad3df07efd. Approved start restored runtime and real orders.
- Payment cleanup resumed after downtime spanning its deadline: deadline 16:05:34.808534, confirmed cleanup 16:05:49.084829.
- Persisted evaluations and JSON/CSV exports worked; exported JSON matched saved metrics.

## Fault evidence

No experiment or open recorded fault existed initially, but paymentUnreachable=on was active in Flagd. Its onset was unknown. The observation was recorded and the flag cleared. The old EIOS copy was also cleared before rebinding.

| Scenario | Experiment ID | UTC start | Confirmed end | Evidence |
| --- | --- | --- | --- | --- |
| Payment warm-up | dc771f58-bdd7-4159-9908-c1fb4a9584b5 | 16:02:34.808534 | 16:05:49.084829 | Checkout errors predated activation; payment server metrics initially absent. Causal attribution is confounded. Restart-resumable cleanup passed. |
| CPU before correction | a7d048cd-0dc9-4466-a31d-3dabf0846257 | 16:06:12.961072 | 16:09:19.080024 | Docker approximately 379% CPU while EIOS underreported cores; exposed collector defect. |
| Checkout stop | 6587d002-503a-4a1b-98c4-dbbdf5347545 | 16:09:48.275167 | 16:11:19.612789 | Offline detection 16:09:55.420341, delay 7.15 s. Incident c331034f-7fcb-4a2e-bc98-6e7c0c27d3ea; approved start entered VERIFYING. |
| CPU corrected | bea2267c-b805-4436-a1e3-f5a85389ab72 | 16:11:36.333017 | 16:13:42.449199 | 2.4375 cores at 16:12:19.681; detection 16:12:29.227489, delay 52.89 s. Later near 0.017 cores. |
| Memory 10x | 607b231d-2449-439e-a444-7f1900e7fae9 | 16:14:18.066932 | 16:16:20.420741 | Real email traffic and growth, but no threshold crossing established. |
| Memory 100x | 732a6206-f177-4ed1-8086-9262954f3b21 | 16:16:41.211258 | 16:18:42.377611 | Memory approximately 0.662 to 0.733 fraction; short run below static threshold. |
| Payment repeat | 7a3ca116-4882-4a61-b6d7-6b7bc69f1928 | 16:18:46.519945 | 16:20:46.960100 | Real checkout traffic/payment metrics now present; persisted episode evidence retained. |
| Baseline 1 | 20d8a815-8715-49b1-a42b-52755dcf1493 | 16:50:50.301492 | 16:52:23.452628 | No target alert; correctly excluded because source coverage 0.75 is below 0.80. |

These are engineering checks, not a balanced academic benchmark. Source defects, pre-existing checkout latency, short memory runs, and no deployed ML prevent broad accuracy claims. Saved evaluations must retain actual exclusions and denominators.

## Pending and limitations

- Second baseline, real Groq investigation, cleanup failure/retry and positive sustained recovery have now completed. Final cleanup evidence follows below.
- Supported browser runtime returned no available sessions twice. Visual layout, keyboard interaction, responsive behavior and the full browser journey remain unverified; React/API checks do not replace browser checks.
- Production model_registry is empty. Isolated training/artifact/inference tests pass; deployed ML and balanced comparisons remain unverified. Do not silently train using invalid historic CPU units.
- Checkout retains high reported p95 after errors return to zero. The initial 180-second verification window was insufficient; failed/inconclusive outcomes remain recorded. The corrected 600-second configuration demonstrated successful sustained recovery for an isolated service.
- Telemetry-only names and old diagnostic container names remain in historical catalog data. Preserve IDs; future filtering should distinguish telemetry identities and registered runtime inventory.
- Decorative/fixed data remains outside canonical Operations/Reports: OS header volume/battery, terminal greeting posture/version, filesystem examples and System Monitor mesh footer. These are not measured system health. Reports and Operations do not invent rows on API failure.
- Managed Locust mutation was not exercised; existing load was used without inventing concurrency. No independent watchdog exists, so orchestrator downtime can extend faults.
- Quotas are per process; PostgreSQL hash chains are not external signed audit guarantees. Per-application grants and broader production hardening remain outside this verification.

## Subsequent evidence

- Baseline 2, experiment 7d4799d7-0010-4c7e-aaf1-4e90cd40c678, ran 16:53:35.919248–16:55:57.497463 UTC and supplied an eligible negative control. Baseline 1 remained explicitly excluded for insufficient coverage.
- Governance integrity verified the entire available chain, 103 records at that observation.
- Independent exclusion annotations were saved for the confounded warm-up Payment episode and the CPU episode affected by the measurement defect. These runs remain in history.
- Real Groq requests authenticated successfully. The unavailable legacy model returned 404; the current model list included openai/gpt-oss-20b. An oversized first design returned 413; repeated large contexts then hit a 429 quota. A bounded two-request design now retrieves a compact, scoped incident bundle and returns structured JSON without arbitrary actions.
- A real Groq investigation completed through the live HTTP API: investigation 79e7a4a2-59b6-4cb2-b93e-3ae75828b44e, model openai/gpt-oss-20b. Tool and final requests both returned 200. Record citations and service/candidate membership passed validation; results persisted.
- Cleanup failure/retry was exercised against a real active fault using a deliberately nonexistent Flagd path in only the diagnostic process. Experiment 008b175e-d5f9-4756-8a8f-6cbdf87141b7 stayed CLEANUP_FAILED with its ground-truth window open; retry through the normal API restored the flag and completed at 17:01:18.638951. It is explicitly excluded from detector benchmarking.
- Service-stop experiment 6c44feb8-6cd3-4551-a0d0-8322af071cb2 targeted telemetry-docs, started at 17:01:25.808727, and detected offline at 17:01:47.753939. Incident cee165e4-55b9-4a04-ba6c-a3969cb09673 and case a5b6e7a6-5fc3-41f8-9ba2-035fa2369b65 were persisted. Approved start execution 5a780cc4-c5da-43b9-80fd-7e3bc8a766ec entered VERIFYING. Repeated execution returned 409 and wrong-application decision returned 404. The original 180-second verification ended INCONCLUSIVE at 17:05:29.868965 after a diagnostic orchestrator restart; late observations did not falsely resolve it. A repeat uses the corrected 600-second default.
- A complete bind-mount inspection found zero references to eios2. The running Compose verification setting was confirmed as EIOS_VERIFICATION_SECONDS=600. Workflow regression rerun passed 32/32, including rejection of post-deadline samples.

## Phase coverage

| Phase | Evidence and remaining boundary |
| --- | --- |
| 3: discovery/topology | Real catalog/runtime/dependency reads, offline persistence and stable identity observed; historical telemetry-only inventory remains noisy. |
| 4: real-time dashboard | REST, same-origin proxy and actual WebSocket frames pass; request races covered by React tests; visual browser checks unavailable. |
| 5: hybrid detection/health | Static/statistical paths and corrected CPU signal exercised; short memory episodes stayed below objectives; production ML is not deployed. |
| 6: correlation/incidents | Real anomalies, grouped incidents, case linkage and timelines observed; unrelated-evidence/idempotency tests pass. |
| 7: deterministic RCA | Real ranked records and score breakdowns observed; isolated abstention/provenance tests pass. Weight quality is not established by these small experiments. |
| 8: AI investigation | Real provider/API result with validated IDs; failure/quota cases persisted; factual prose errors remain a review requirement. |
| 9: planner/policy | Persisted proposals, rejection, approval roles and policy checks pass. |
| 10: runtime | Approved start/restart executed; unapproved/repeated/wrong-application bypass rejected; expiry/protected/interruption tests pass. |
| 11: recovery | FAILED, INCONCLUSIVE and RECOVERED observed live; strict deadlines tested; sustained recovery resolved an actual incident and case. |
| 12: experiments | Payment/CPU/memory/service-stop/baseline runs, deadline restart cleanup and failed-restore retry exercised; managed load remains untested. |
| 13: evaluation | Saved inputs, exclusions, coverage checks, exact arithmetic tests, JSON/CSV exports and an eligible negative control observed; not a balanced benchmark. |
| 14: security/governance | Server roles, sessions, origin enforcement, private recovery, quotas and audit integrity checked; no external signed audit anchor. |
| 15: journey/polish | Backend journey and component states exercised; browser visual/accessibility/responsive review remains blocked. |
- **AI quality limitation:** completed output still contained contradictory statements about direct evidence and incorrect unit rendering (for example, describing approximately 13,078 ms as 13 ms). The completed state means schema/citation checks passed, not that prose is factually validated. Unreviewed AI explanations are not demo-ready. Deterministic measurements and rankings remain authoritative.

## Final outcome

- The positive full journey completed for telemetry-docs: offline detection 17:06:21.950273 UTC, incident 6a99061e-22e9-42db-a655-43ccbec2c3d7, approved start execution 25065080-d60a-4055-a104-bc9872ca2553, and recovery c63bb6af-422a-4da0-8d2e-b5b18571ef82 at 17:08:33.023620 UTC after three fresh samples spanning 53.79 seconds. Incident and case resolved in PostgreSQL.
- Final evaluation `72cf8509-003f-43b8-b953-04dccd14fd3c` persisted 12 episodes: static precision 1.0/recall 0.714/F1 0.833, statistical precision 1.0/recall 0.286/F1 0.444, hybrid precision 1.0/recall 0.857/F1 0.923, MTTD 61.18 s and MTTR 174.42 s. Four episodes were explicitly excluded; ML had no deployed model.
- Final audit checked 146 records with valid integrity. Temporary verification accounts were disabled and their sessions revoked. Database counts were 130,905 events, 2,280 incidents, 146 cases, 5 approvals, 18,063 feature windows, 2,056 insights, 2,962 anomalies and 457 RCA rankings. The disposable verification PostgreSQL container was stopped; the production PostgreSQL volume was preserved.
- Test suite result: 168 passing. Dashboard build and TypeScript checks passed. Remaining handoff limits are browser-runtime availability, deployed ML absence, AI prose review, high historical checkout latency, and broader balanced-load benchmarking.
