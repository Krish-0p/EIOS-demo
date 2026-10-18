# EIOS

EIOS is an observability intelligence layer for the OpenTelemetry Astronomy Shop Demo. It consumes order events from Kafka and infrastructure metrics from Prometheus, normalizes them into a common event model, detects incidents, and exposes them through a FastAPI API and React dashboard.

The repository contains the complete EIOS project and the OpenTelemetry Demo substrate it observes. The EIOS layer is added through a fourth Docker Compose file, so the upstream OpenTelemetry Demo is not modified.

## Current verification status

`C:/Users/Krisss/Documents/EIOS` is the main project directory. Phase 3–15 source and verification fixes have been transferred here from the separate `eios2` working checkout. The original source was backed up before transfer. Existing database volumes and history are preserved. See [the verification report](docs/PHASE3_15_VERIFICATION.md) for measured results and remaining limitations. Older phase sections below describe their historical delivery boundaries.

Groq investigation supports `EIOS_INVESTIGATION_PROVIDER=groq`, `EIOS_INVESTIGATION_MODEL=openai/gpt-oss-20b`, and `GROQ_API_KEY`. Compose loads these from the local `opentelemetry-demo/.env` or shell environment. Keep keys private and out of version control. Recreate the orchestrator after configuration changes. Never paste keys into chat. Groq receives bounded incident evidence for requested investigations.

Compose defaults recovery verification to 600 seconds, allowing five-minute request metrics to shed previous faults plus sustained fresh confirmation. Override with `EIOS_VERIFICATION_SECONDS` (60–1800 seconds). Observations after an individual verification deadline cannot establish recovery. Existing verification records retain their original deadlines.

## Phase 2: unified telemetry

The existing Kafka and Prometheus collectors now attach application/service IDs, service name, environment, signal type, source identity, source timestamp, and source references before persistence and Kafka publication. Historical event IDs and values remain unchanged. Container metrics from the shared Docker collector follow the registered runtime owner, including the EIOS Platform application.

Application-scoped telemetry APIs are under `/api/applications/{id}/telemetry`: `/sources`, `/records`, and `/services/{service_id}/evidence/{trace|log}`. Trace/log evidence is fetched from the existing Jaeger/OpenSearch backends within bounded windows and persisted as small redacted snapshots. The Application Registry shows real source connection/freshness observations through shadcn components.

Administrators can activate Prometheus/Jaeger/OpenSearch source bindings with `POST /sources`. Shared backends require provably disjoint selectors; ambiguous service names cannot establish application identity. Source endpoint/scope is immutable after data exists. Saving the older application endpoint fields alone does not activate a binding. The existing Kafka `orders` connector remains attached to Astronomy Shop; additional Kafka topic/schema connectors are not implemented.

Existing name-based detectors and intelligence remain restricted to Astronomy Shop. Other applications have isolated telemetry storage and evidence access without borrowing its model/history. Source checks distinguish connection failures, stale observations, and unknown data; a healthy Kafka watermark can establish source freshness even when no new orders occur. Original business-event timestamps remain visible independently.

Startup uses additive versioned migrations and the existing volumes. See [the Phase 2 report](docs/PHASE2_IMPLEMENTATION.md) for migration hashes, real source-failure evidence, test results, and limits. Phase 3 has not started.

## Phase 1: accounts, applications, and services

The dashboard uses persistent PostgreSQL accounts and server-validated HttpOnly cookie sessions. Operational APIs require a signed-in session or an explicitly configured machine API key. On a fresh installation, use the dashboard to create the first administrator. After setup, only administrators can create accounts through `POST /api/auth/register`; supported roles are `administrator`, `operator`, and `viewer`. Registration cannot overwrite an existing account.

Open the dashboard at `http://127.0.0.1:5173` or `http://localhost:5173`. Its same-origin proxy forwards API and authenticated WebSocket traffic. Refresh validates the saved cookie with the server; Lock and Reboot revoke the session. The default absolute lifetime is 12 hours, configurable through `EIOS_SESSION_SECONDS`. Set `EIOS_COOKIE_SECURE=true` with HTTPS and configure `EIOS_CORS_ORIGINS` for the dashboard's public origin.

The onboarding dialog now provides the persistent Application Registry and Service Catalog. Administrators create applications with environment, Docker scope, labels, and telemetry endpoint configuration. Administrators/operators discover or manually register services. Discovery requires a Compose project, Docker labels, or explicit container names; combined selectors narrow the scope. Services retain stable identities when containers stop, disappear, or are recreated. Background discovery runs every 30 seconds; the open catalog polls every 10 seconds.

Dashboard development and Docker builds use Bun 1.3.11 with `bun install --frozen-lockfile`. Docker build contexts exclude local `node_modules`, build output, and environment files.

Startup applies a versioned, additive migration to the existing database volume. Legacy events, incidents, cases, and intelligence history map to the default Astronomy Shop application without changing IDs. Existing producers retain their contracts; database triggers attach persisted identities. Name-based telemetry APIs remain available for Astronomy Shop. Other applications have independent runtime catalogs; registering an endpoint does not activate a telemetry connector. Explicit `attributes.application_id` identifies application-scoped event input; absent identity belongs to the legacy pipeline. Connector/provenance redesign remains outside Phase 1.

Registry endpoints are `GET/POST /api/applications`, `GET/POST /api/applications/{id}/services`, and `POST /api/applications/{id}/discovery`. Scoped history is available at `/api/applications/{id}/services/{service_id}/history`; `/api/events` and `/api/incidents` accept an optional `application_id`. Unknown discovery state differs from confirmed offline state. Telemetry freshness is independent of runtime availability.

Use the existing startup command below; do not remove PostgreSQL volumes for this migration. The initial historical backfill can briefly block writers. See [the Phase 1 implementation report](docs/PHASE1_IMPLEMENTATION.md) for evidence, compatibility notes, and remaining limits.

## Architecture

```text
OpenTelemetry Demo
  ├── checkout ── Kafka orders topic
  ├── payment / cart / product-catalog
  └── Prometheus metrics

EIOS
  ├── ingest ── consumes Kafka and Prometheus data
  ├── detect ── creates incidents
  ├── orchestrator ── REST API and WebSocket feed
  └── dashboard ── operations interface

PostgreSQL ── stores normalized events, incidents, and fault windows
```

## Repository Layout

```text
EIOS/
├── opentelemetry-demo/       # Upstream substrate
├── eios/                     # EIOS application and compose layer
│   ├── dashboard/            # React + Vite dashboard
│   ├── db/                   # PostgreSQL initialization and migrations
│   ├── detect/               # Incident detection rules
│   ├── ingest/               # Kafka and Prometheus ingestion
│   ├── orchestrator/         # FastAPI API and WebSocket server
│   ├── schemas/              # Shared event and incident contracts
│   ├── security/              # Redaction, rate limiting, and auditing
│   └── compose.eios.yaml      # EIOS Docker Compose layer
├── start.ps1                 # Windows startup script
├── compose.eios.yaml          # Root-level EIOS Compose entry point
├── compose.eios.security.yaml  # Optional hardened security configuration
└── README.md
```

## Prerequisites

- Windows 10/11
- Docker Desktop with WSL 2
- Docker Compose v2
- Git
- Node.js and npm are optional for local dashboard development
- Docker needs approximately 8 GB of memory for the full stack

## First-Time Setup

The EIOS Compose file uses build contexts relative to the OpenTelemetry Demo directory. Keep both repositories in the same parent directory:

```text
D:\Eios\
├── eios\
└── opentelemetry-demo\
```

From the OpenTelemetry Demo directory, start the complete stack:

```powershell
cd D:\Eios\opentelemetry-demo
docker compose -f compose.yaml -f compose.full.yaml `
  -f compose.observability.yaml `
  -f ..\eios\compose.eios.yaml up -d
```

Alternatively, run the provided Windows startup script:

```powershell
cd D:\Eios\eios
.\start.ps1
```

Use `127.0.0.1`, not `localhost`, for host access. On Windows, localhost can resolve to IPv6 first and hang when Docker is listening on IPv4.

## URLs

| Service | URL |
| --- | --- |
| Storefront | http://127.0.0.1:8080/ |
| EIOS Dashboard | http://127.0.0.1:5173/ |
| EIOS API | http://127.0.0.1:8000 |
| Prometheus | http://127.0.0.1:9090 |
| Jaeger | http://127.0.0.1:8080/jaeger/ui/ |
| Grafana | http://127.0.0.1:8080/grafana/ |
| Flagd fault injection | http://127.0.0.1:8080/feature |
| EIOS PostgreSQL | 127.0.0.1:5433 |

## Architecture and Data Flow

1. The OpenTelemetry Demo generates order events and telemetry.
2. The EIOS ingest service reads Kafka order results and Prometheus metrics.
3. Normalized events are written to PostgreSQL.
4. The detect service evaluates rules and writes incidents.
5. The orchestrator exposes statistics, incidents, flags, fault windows, security status, and audit data through REST APIs and WebSockets.
6. The dashboard displays the live operations view.

## Detection Domains

| Domain | Signal | Current State |
| --- | --- | --- |
| B — E-commerce | Order-result Kafka messages | Implemented |
| C — Infrastructure | Container CPU and memory metrics | Implemented |
| A — Attack | Authentication and traffic signals | Not implemented yet |

The normalized event model stores numeric signals in `metrics` and contextual information in `attributes`. Incidents include the detector name, severity, score, evidence, labels, and detection time.

## Fault Injection

Use the Flagd interface at:

```text
http://127.0.0.1:8080/feature
```

Useful flags include:

- `paymentFailure`
- `cartFailure`
- `productCatalogFailure`
- `emailMemoryLeak`
- `adHighCpu`
- `kafkaQueueProblems`

Every fault toggle is recorded in the `fault_windows` table. This record is the ground truth used to evaluate detector precision and recall.

## Run the Dashboard Locally

The dashboard is included in the Docker stack, so the recommended route is the Docker deployment above.

For local development, install dependencies and start Vite:

```powershell
cd D:\Eios\eios\dashboard
npm install
npm run dev
```

The dashboard uses `http://127.0.0.1:8000` by default. If the API is unavailable, the page displays a fetch error until `eios-orchestrator` is running.

## Run Without Docker

The Python services can be started individually from their directories after installing their requirements:

```powershell
cd D:\Eios\eios\orchestrator
python -m pip install -r requirements.txt
python main.py
```

The dashboard still requires the PostgreSQL and Kafka services to be available through the configured environment variables.

## Stop the Stack

```powershell
cd D:\Eios\opentelemetry-demo
docker compose -f compose.yaml -f compose.full.yaml `
  -f compose.observability.yaml `
  -f ..\eios\compose.eios.yaml down
```

To stop and remove persistent volumes:

```powershell
docker compose -f compose.yaml -f compose.full.yaml `
  -f compose.observability.yaml `
  -f ..\eios\compose.eios.yaml down -v
```

## Security and Operations

- API keys can protect the orchestrator endpoints.
- Security middleware supports redaction, rate limiting, and audit logging.
- Fault windows are persisted in PostgreSQL.
- The dashboard reconnects to the incident WebSocket automatically when the connection drops.
- Use the `security` test suite for unit tests:

```powershell
cd D:\Eios\eios
python -m pytest -q security\tests
```

## Troubleshooting

### Dashboard shows “Could not reach the orchestrator”

1. Confirm the orchestrator container is running:

```powershell
docker ps --filter "name=eios-orchestrator"
```

2. Confirm port 8000 is published:

```powershell
docker port eios-orchestrator
```

3. Test the API:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/stats
```

4. Inspect the orchestrator logs:

```powershell
docker logs eios-orchestrator --tail 200
```

The dashboard uses `127.0.0.1` intentionally. A localhost change may resolve to IPv6 and fail against the IPv4-only container port.

### API returns a database timeout

Inspect the PostgreSQL service and orchestrator logs:

```powershell
docker ps --filter "name=eios-postgres"
docker logs eios-orchestrator --tail 200
```

The orchestrator uses a PostgreSQL connection pool. A blocked, closed, or unavailable database connection can cause requests to wait until the pool timeout.

### Payment remains unhealthy

Restart only the payment service after confirming that its port is available:

```powershell
docker compose -f compose.yaml -f compose.full.yaml `
  -f compose.observability.yaml `
  -f ..\eios\compose.eios.yaml up -d --force-recreate payment
```

Then inspect its health and logs:

```powershell
docker inspect payment --format "{{.State.Health.Status}}"
docker logs --tail 100 payment
```

## License

The OpenTelemetry Demo portion is Apache License 2.0. EIOS project-specific code follows the repository license terms.
<!-- markdownlint-disable-next-line -->
# <img src="https://opentelemetry.io/img/logos/opentelemetry-logo-nav.png" alt="OTel logo" width="45"> OpenTelemetry Demo

[![Slack](https://img.shields.io/badge/slack-@cncf/otel/demo-brightgreen.svg?logo=slack)](https://cloud-native.slack.com/archives/C03B4CWV4DA)
[![Version](https://img.shields.io/github/v/release/open-telemetry/opentelemetry-demo?color=blueviolet)](https://github.com/open-telemetry/opentelemetry-demo/releases)
[![Commits](https://img.shields.io/github/commits-since/open-telemetry/opentelemetry-demo/latest?color=ff69b4&include_prereleases)](https://github.com/open-telemetry/opentelemetry-demo/graphs/commit-activity)
[![Downloads](https://img.shields.io/docker/pulls/otel/demo)](https://hub.docker.com/r/otel/demo)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?color=red)](https://github.com/open-telemetry/opentelemetry-demo/blob/main/LICENSE)
[![Telemetry Tests](https://github.com/open-telemetry/opentelemetry-demo/actions/workflows/run-telemetry-tests.yml/badge.svg)](https://github.com/open-telemetry/opentelemetry-demo/actions/workflows/run-telemetry-tests.yml)
[![Artifact Hub](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/opentelemetry-demo)](https://artifacthub.io/packages/helm/opentelemetry-helm/opentelemetry-demo)
[![FOSSA Status](https://app.fossa.com/api/projects/custom%2B162%2Fgithub.com%2Fopen-telemetry%2Fopentelemetry-demo.svg?type=shield&issueType=license)](https://app.fossa.com/projects/custom%2B162%2Fgithub.com%2Fopen-telemetry%2Fopentelemetry-demo?ref=badge_shield&issueType=license)
[![FOSSA Status](https://app.fossa.com/api/projects/custom%2B162%2Fgithub.com%2Fopen-telemetry%2Fopentelemetry-demo.svg?type=shield&issueType=security)](https://app.fossa.com/projects/custom%2B162%2Fgithub.com%2Fopen-telemetry%2Fopentelemetry-demo?ref=badge_shield&issueType=security)
[![OpenSSF Scorecard for opentelemetry-demo](https://api.scorecard.dev/projects/github.com/open-telemetry/opentelemetry-demo/badge)](https://scorecard.dev/viewer/?uri=github.com/open-telemetry/opentelemetry-demo)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/9247/badge)](https://www.bestpractices.dev/en/projects/9247)

## Welcome to the OpenTelemetry Astronomy Shop Demo

This repository contains the OpenTelemetry Astronomy Shop, a microservice-based
distributed system intended to illustrate the implementation of OpenTelemetry in
a near real-world environment.

Our goals are threefold:

- Provide a realistic example of a distributed system that can be used to
  demonstrate OpenTelemetry instrumentation and observability.
- Build a base for vendors, tooling authors, and others to extend and
  demonstrate their OpenTelemetry integrations.
- Create a living example for OpenTelemetry contributors to use for testing new
  versions of the API, SDK, and other components or enhancements.

We've already made [huge
progress](https://github.com/open-telemetry/opentelemetry-demo/blob/main/CHANGELOG.md),
and development is ongoing. We hope to represent the full feature set of
OpenTelemetry across its languages in the future.

If you'd like to help (**which we would love**), check out our [contributing
guidance](./CONTRIBUTING.md).

If you'd like to extend this demo or maintain a fork of it, read our
[fork guidance](https://opentelemetry.io/docs/demo/forking/).

## Quick start

You can be up and running with the demo in a few minutes. Check out the docs for
your preferred deployment method:

- [Docker](https://opentelemetry.io/docs/demo/docker_deployment/)
- [Kubernetes](https://opentelemetry.io/docs/demo/kubernetes_deployment/)

## Documentation

For detailed documentation, see [Demo Documentation][docs]. If you're curious
about a specific feature, the [docs landing page][docs] can point you in the
right direction.

## Demos featuring the Astronomy Shop

We welcome any vendor to fork the project to demonstrate their services and
adding a link below. The community is committed to maintaining the project and
keeping it up to date for you.

|                           |                |                                  |
|---------------------------|----------------|----------------------------------|
| [AlibabaCloud LogService] | [Elastic]      | [Oracle]                         |
| [Amazon Web Services]     | [Google Cloud] | [Parseable]                      |
| [Apache Doris]            | [Grafana Labs] | [Sentry]                         |
| [AppDynamics]             | [Guance]       | [ServiceNow Cloud Observability] |
| [Aspecto]                 | [Honeycomb.io] | [SigNoz]                         |
| [Axiom]                   | [Instana]      | [SolarWinds Observability]       |
| [Axoflow]                 | [Kloudfuse]    | [Splunk]                         |
| [Azure Data Explorer]     | [Kopai]        | [Sumo Logic]                     |
| [Bronto]                  | [Last9]        | [TelemetryHub]                   |
| [Causely]                 | [Liatrio]      | [Teletrace]                      |
| [ClickStack]              | [Logz.io]      | [Tinybird]                       |
| [Coralogix]               | [New Relic]    | [Tracetest]                      |
| [Dash0]                   | [Oodle]        | [Tsuga]                          |
| [Datadog]                 | [OpenObserve]  | [Uptrace]                        |
| [Dynatrace]               | [OpenSearch]   | [VictoriaMetrics]                |

## Contributing

To get involved with the project see our [CONTRIBUTING](CONTRIBUTING.md)
documentation. Our [SIG Calls](CONTRIBUTING.md#join-a-sig-call) are every other
Wednesday at 8:30 AM PST and anyone is welcome.

### Maintainers

- [Cyrille Le Clerc](https://github.com/cyrille-leclerc), Datadog
- [Juliano Costa](https://github.com/julianocosta89), Datadog
- [Shenoy Pratik](https://github.com/ps48), AWS OpenSearch

For more information about the maintainer role, see the [community repository](https://github.com/open-telemetry/community/blob/main/guides/contributor/membership.md#maintainer).

### Approvers

- [D&#xF3;nal O'Sullivan](https://github.com/osullivandonal), Elastic
- [Piotr Kie&#x142;kowicz](https://github.com/Kielek), Splunk

For more information about the approver role, see the [community repository](https://github.com/open-telemetry/community/blob/main/guides/contributor/membership.md#approver).

### Emeritus

- [Austin Parker](https://github.com/austinlparker), Maintainer
- [Carter Socha](https://github.com/cartersocha), Maintainer
- [Cedric Ziel](https://github.com/cedricziel), Approver
- [Michael Maxwell](https://github.com/mic-max), Approver
- [Mikko Viitanen](https://github.com/mviitane), Maintainer
- [Morgan McLean](https://github.com/mtwo), Approver
- [Penghan Wang](https://github.com/wph95), Approver
- [Pierre Tessier](https://github.com/puckpuck), Maintainer
- [Reiley Yang](https://github.com/reyang), Approver
- [Roger Coll](https://github.com/rogercoll), Maintainer
- [Ziqi Zhao](https://github.com/fatsheep9146), Approver

For more information about the emeritus role, see the [community repository](https://github.com/open-telemetry/community/blob/main/guides/contributor/membership.md#emeritus-maintainerapprovertriager).

### Thanks to all the people who have contributed

[![contributors](https://contributors-img.web.app/image?repo=open-telemetry/opentelemetry-demo)](https://github.com/open-telemetry/opentelemetry-demo/graphs/contributors)

[docs]: https://opentelemetry.io/docs/demo/

<!-- Links for Demos featuring the Astronomy Shop section -->

[AlibabaCloud LogService]: https://github.com/aliyun-sls/opentelemetry-demo
[Amazon Web Services]: https://github.com/aws-observability/observability-best-practices/blob/main/sandbox/otel-demo-thegame/README.md
[AppDynamics]: https://community.splunk.com/t5/AppDynamics-Knowledge-Base/How-to-observe-Kubernetes-deployment-of-OpenTelemetry-demo-app/ta-p/741454
[Apache Doris]: https://github.com/apache/doris-opentelemetry-demo
[Aspecto]: https://github.com/aspecto-io/opentelemetry-demo
[Axiom]: https://play.axiom.co/axiom-play-qf1k/dashboards/otel.traces.otel-demo-traces
[Axoflow]: https://axoflow.com/opentelemetry-support-in-more-detail-in-axosyslog-and-syslog-ng/
[Azure Data Explorer]: https://github.com/Azure/Azure-kusto-opentelemetry-demo
[Bronto]: https://docs.bronto.io/getting-started/otel-demo
[Causely]: https://github.com/causely-oss/otel-demo
[ClickStack]: https://github.com/ClickHouse/opentelemetry-demo
[Coralogix]: https://coralogix.com/blog/configure-otel-demo-send-telemetry-data-coralogix
[Dash0]: https://github.com/dash0hq/opentelemetry-demo
[Datadog]: https://docs.datadoghq.com/opentelemetry/guide/otel_demo_to_datadog
[Dynatrace]: https://www.dynatrace.com/news/blog/opentelemetry-demo-application-with-dynatrace/
[Elastic]: https://github.com/elastic/opentelemetry-demo
[Google Cloud]: https://github.com/GoogleCloudPlatform/opentelemetry-demo
[Grafana Labs]: https://github.com/grafana/opentelemetry-demo
[Guance]: https://github.com/GuanceCloud/opentelemetry-demo
[Honeycomb.io]: https://github.com/honeycombio/opentelemetry-demo
[Instana]: https://github.com/instana/opentelemetry-demo
[Kloudfuse]: https://github.com/kloudfuse/opentelemetry-demo
[Kopai]: https://github.com/kopai-app/opentelemetry-demo/tree/main/kopai
[Last9]: https://last9.io/docs/integrations-opentelemetry-demo/
[Liatrio]: https://github.com/liatrio/opentelemetry-demo
[Logz.io]: https://logz.io/learn/how-to-run-opentelemetry-demo-with-logz-io/
[New Relic]: https://github.com/newrelic/opentelemetry-demo
[Oodle]: https://blog.oodle.ai/meet-oodle-unified-and-ai-native-observability/
[OpenSearch]: https://github.com/opensearch-project/opentelemetry-demo
[OpenObserve]: https://openobserve.ai/blog/opentelemetry-astronomy-shop-demo/
[Oracle]: https://github.com/oracle-quickstart/oci-o11y-solutions/blob/main/knowledge-content/opentelemetry-demo
[Parseable]: https://www.parseable.com/blog/open-telemetry-demo-with-parseable-a-complete-observability-setup
[Sentry]: https://github.com/getsentry/opentelemetry-demo
[ServiceNow Cloud Observability]: https://docs.lightstep.com/otel/quick-start-operator#send-data-from-the-opentelemetry-demo
[SigNoz]: https://signoz.io/blog/opentelemetry-demo/
[SolarWinds Observability]: https://github.com/solarwinds/opentelemetry-demo
[Splunk]: https://github.com/signalfx/opentelemetry-demo
[Sumo Logic]: https://www.sumologic.com/blog/common-opentelemetry-demo-application/
[TelemetryHub]: https://github.com/TelemetryHub/opentelemetry-demo/tree/telemetryhub-backend
[Teletrace]: https://github.com/teletrace/opentelemetry-demo
[Tinybird]: https://github.com/tinybirdco/opentelemetry-demo
[Tracetest]: https://github.com/kubeshop/opentelemetry-demo
[Tsuga]: https://github.com/tsuga-dev/opentelemetry-demo
[Uptrace]: https://github.com/uptrace/uptrace/tree/master/example/opentelemetry-demo
[VictoriaMetrics]: https://github.com/VictoriaMetrics-Community/opentelemetry-demo
