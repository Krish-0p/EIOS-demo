# Intelligence Agent backend

The Intelligence Agent runs continuously in `eios-intelligence`. It reads normalized Kafka events, persists closed minute windows, evaluates KPI objectives, produces memory forecasts, and scores active service models. PostgreSQL holds the history and registry; the `eios-models` Docker volume holds locally generated model artifacts. No GPU, paid API, or LLM is required.

Open the dashboard at `http://127.0.0.1:5173` and select the existing **Reports** sidebar icon. Reports uses the EIOS theme and window controls, with Overview, Anomalies & Findings, Predictions, KPIs, and Models tabs. Service and finding-period filters query stored analytics; KPI and prediction panels show their latest snapshots. Missing metrics, stale observations, unavailable sources, and forecast abstentions are explicit. Findings expose measurements, baseline, candidate causes, evidence event IDs, and manual recommendations. Confirm and Dismiss record feedback under the signed-in administrator name. Models are read-only; training, promotion, and rollback remain explicit operator steps below.

Reports refreshes every 30 seconds while open. Use its Refresh control for an immediate update. Minimize or close removes the window; select Reports again to reopen it. The taskbar also provides a Reports shortcut. After rebuilding the dashboard, reload the browser to receive the new assets.

The REST API and Swagger at `http://127.0.0.1:8000/docs` remain available. The existing AI Assistant endpoint summarizes stored measurements and findings. This is a deterministic analytics assistant, not an unrestricted natural-language model.

## Start and inspect

From the repository root in PowerShell:

```powershell
.\eios\start.ps1 -Build
```

`-Build` rebuilds the EIOS images after backend changes. Subsequent starts can use `.\eios\start.ps1`. Use `-Demo` to raise the existing load generator to 20 users when preparing an order-throughput demonstration. Docker Desktop starts automatically when needed.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/intelligence/status
Invoke-RestMethod 'http://127.0.0.1:8000/api/intelligence/kpis?service=ad'
Invoke-RestMethod 'http://127.0.0.1:8000/api/intelligence/insights?service=ad'
Invoke-RestMethod 'http://127.0.0.1:8000/api/intelligence/forecasts?service=email'
Invoke-RestMethod http://127.0.0.1:8000/api/intelligence/models
docker logs eios-intelligence --tail 30
```

The initial status is `unavailable` while the first complete windows close, then `learning` until an operator trains and activates a model. This normally takes about three minutes for the first data windows. Active model scoring is visible through `/api/intelligence/inferences`. A healthy worker without an active model still performs KPI analysis and memory forecasting.

## Measurements and freshness

Canonical feature schema `2.0` contains `cpu_cores`, `memory_fraction`, `request_rate_per_sec`, `error_rate_per_sec`, `error_fraction`, `latency_p95_ms`, and `orders_per_min`. One CPU core is `1.0`; memory and error values are fractions. The deployed Docker collector publishes CPU and memory percentages despite its metric suffixes, so ingestion scales them by `0.01`. Source scales can be changed with `EIOS_CPU_SOURCE_SCALE` and `EIOS_MEMORY_SOURCE_SCALE` if the collector implementation changes. Verify actual units before doing so.

Container events use the underlying Prometheus sample timestamp. RED events retain the contributing counter timestamp and query timestamp. Orders use the Kafka message timestamp and a stable identity derived from topic, partition, and offset. Replaying an old order therefore does not create current traffic. Legacy CPU/memory event fields remain available; legacy rule output is labelled `rule-v1` and excluded from model training windows.

Minute windows close after a configurable 90-second lateness allowance. Events received after that allowance remain in the raw store but do not rewrite sealed model windows. Repeated polling of the same gauge sample does not increase coverage. The worker refuses metrics older than 240 seconds at inference time. Missing metrics remain absent.

RED rates are derived from five-minute server-span counters. Stored p95 values are averages of five-minute p95 snapshots, not recomputed percentiles for each minute. Errors can be zero only when a calls series exists. Zero order throughput requires fresh, caught-up Kafka source-health observations covering the minute; throughput-drop analysis additionally requires request traffic and an established order baseline.

Ingestion stores each event and its delivery intent in one transaction. Its outbox publisher retries Kafka delivery. Intelligence outputs, incidents, case updates, and notification intents commit before Kafka offsets advance. Outbox delivery is at least once: consumers must deduplicate IDs. REST history is authoritative after WebSocket reconnects. No existing database volume is deleted; additive migrations run under a database lock on startup.

## Train the first ad CPU model

Collect representative healthy operation first. At least 60 complete healthy minute windows are required, with at least 40 training windows and 10 validation windows after a five-minute gap. Allow roughly 70–90 minutes, including warmup and different healthy traffic levels. Existing legacy event counts do not satisfy this requirement.

Record the start and end of a period you have checked for normal behavior:

```powershell
$trainingStart = (Get-Date).ToUniversalTime().ToString('o')
# Run healthy traffic at representative loads; capture the end afterward.
$trainingEnd = (Get-Date).ToUniversalTime().AddMinutes(-3).ToString('o')
docker exec eios-intelligence python -m intelligence.cli train --service ad --features cpu_cores --start $trainingStart --end $trainingEnd --healthy
```

The comment represents a real collection interval: do not run the two timestamp assignments back to back. `--healthy` confirms your review of that interval. The command also excludes recorded fault windows, five-minute fault/recovery margins, and operator-confirmed anomalous windows. Fault labels are never model input features. The same stored feature schema feeds both training and inference.

Training creates a candidate and returns its UUID and validation results. Candidate creation does not activate it:

```powershell
$modelId = 'replace-with-returned-model-uuid'
docker exec eios-intelligence python -m intelligence.cli promote --model $modelId
Invoke-RestMethod 'http://127.0.0.1:8000/api/intelligence/inferences?service=ad'
```

Promotion checks artifact checksum, dependency version, validation size, and a healthy holdout alert fraction of at most 10%. Treat that gate as a development safeguard, not evidence of fault detection accuracy. Metadata includes training/validation intervals, feature names, algorithm, dependencies, checksum, reference ranges, and last inference. Artifacts are loaded only from the owned model volume.

Isolation Forest produces raw unusualness scores and a normalized score, neither a failure probability. Trees cannot estimate distance beyond their outermost split; an extreme CPU excursion can score like a healthy edge. The backend therefore also applies an explicit CPU range guard at `max(0.5 cores, 3 × training p95 CPU)`. Results expose separate forest and guard components. Operational severity comes from observed impact rather than a claimed probability.

To activate a previously registered version again:

```powershell
docker exec eios-intelligence python -m intelligence.cli rollback --model $previousModelId
```

Rollback uses the same validation and artifact checks as promotion. Feedback does not retrain or replace a model automatically. Train a new candidate from a reviewed later healthy interval, compare it, and explicitly promote it.

## Forecasts and investigation

Memory forecasts project five and ten minutes from recent minute observations. They abstain on insufficient history, missing intervals, stale data, possible restart/memory release, unstable trends, insufficient horizon validation, or failure to match a persistence baseline. With continuous observations, five-minute validation needs roughly 14 samples and ten-minute validation roughly 19. Predictions include measured rolling-origin MAE, persistence MAE, current usage, slope, and a warning threshold. No unvalidated confidence band or guaranteed failure time is shown.

KPI findings reference configured memory, request-error, latency, and order-throughput objectives. Jaeger dependency snapshots and concurrent neighboring measurements support candidate causes. Graph proximity and temporal coincidence are not presented as causal proof. When Jaeger is unavailable, its evidence state is explicit and metric analysis continues.

Findings cite raw event IDs. Related service evidence includes its own IDs and observation intervals. Cases use stable UUIDs stored in PostgreSQL and group same-service incidents in 30-minute episodes. They are investigation records, not proof that a fault has resolved. The current implementation does not perform complete log or trace-content root-cause analysis.

```powershell
$feedback = @{ insight_id = $insightId; verdict = 'confirm'; operator = 'student'; notes = 'Reviewed evidence' } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/intelligence/feedback -Method Post -ContentType 'application/json' -Body $feedback
```

Verdicts are `confirm`, `dismiss`, `useful`, and `not_useful`. Feedback and approval decisions are durable and audited. `/api/cases/{case_id}/approvals` creates a review request; `/api/approvals/{approval_id}/action` records `approve` or `reject`. Neither endpoint executes a restart, scaling operation, or resource change. All recommendations in this release are manual.

## Evaluation

Train and validate first. Then record later healthy traffic and complete, scoped fault episodes. Leave at least five minutes between the model's validation interval and the test interval. Toggle supported demo faults through the existing fault API/UI and always stop them afterward. `adHighCpu` is the first model scenario. `emailMemoryLeak` exercises memory trends. Payment errors are visible through payment RED metrics and related checkout/order evidence; the current fault expectation maps payment faults to checkout, so an evaluation must not silently treat that mapping as payment-service ground truth.

```powershell
docker exec eios-intelligence python -m intelligence.cli evaluate --model $modelId --start $testStart --end $testEnd --reviewed
docker exec eios-intelligence python -m intelligence.cli evaluate-forecasts --service email --start $testStart --end $testEnd
Invoke-RestMethod 'http://127.0.0.1:8000/api/intelligence/evaluations?service=ad'
```

The evaluation harness compares the model plus explicit CPU guard with a CPU/memory rule baseline on the same minute windows. It records window precision/recall/F1, false alert windows per healthy hour, episode recall, and signal delay. It excludes incomplete features, boundary/recovery windows, and other services' fault intervals from healthy negatives. Undefined metrics are null. Signal delay excludes the additional live lateness/evaluation delay, which is stated in each result. This first evaluator requires complete recorded infrastructure faults scoped to the model service; payment/order evaluation needs a reviewed service-scope mapping before extending it.

Forecast evaluation pairs stored five/ten-minute projections with later observed memory. It reports realized MAE against persistence, false warning forecasts, and warning lead time from the actual prediction creation timestamp. Missing future observations and predictions created after their target time are excluded. Forecast horizons start at the input window observation time; delivery follows the configured lateness allowance.

Unit and disposable PostgreSQL tests exercise units, stale samples, absence handling, forecast backtesting, source timestamps, model checksums, chronological separation, promotion/rollback, replay, transaction rollback, cases, and outbox retry. Synthetic tests demonstrate plumbing and analytical behavior; they do not establish real fault precision/recall. Live fault/forecast quality must still be measured using the protocol above.

Run them from the repository root after building the images:

```powershell
.\eios\scripts\test-intelligence.ps1
```

The script creates and removes its own temporary PostgreSQL container. It never points the tests at the application database.

## Additive API surface

`/api/intelligence/status`, `/insights`, `/kpis`, `/history?service=...`, `/forecasts`, `/models`, `/inferences`, `/feedback`, and `/evaluations` expose stored analytics. `/api/incidents/{incident_id}/intelligence` links incidents to their findings. Existing incident WebSocket messages keep their shape; intelligence notifications add `type: "intelligence"`. Existing `/api/ai/chat`, `/api/cases`, and `/api/approvals` preserve their main response fields and now use persistent data.

The Reports window consumes these endpoints without introducing a separate Intelligence Center. Its trend plots show stored samples and preserve gaps; they do not interpolate missing data or fabricate forecasts.
