# EIOS

The intelligence layer for the EIOS capstone. It attaches to a running
OpenTelemetry Demo, reads that stack's telemetry, and turns it into events and
incidents.

EIOS lives outside the demo repository and is layered on with a fourth compose
file. No upstream file is modified, so updating the substrate stays a plain
`git pull`.

## Running

Start the substrate and the EIOS layer together, from the `opentelemetry-demo`
directory:

```
docker compose -f compose.yaml -f compose.full.yaml \
               -f compose.observability.yaml -f ../eios/compose.eios.yaml up -d
```

Use `127.0.0.1` rather than `localhost` for anything on the host. On the
development machine `localhost` resolves to IPv6 first and times out after
about 15 seconds, which looks like a dead service when the container is fine.

| What | Where |
| --- | --- |
| Storefront | http://127.0.0.1:8080/ |
| Jaeger | http://127.0.0.1:8080/jaeger/ui/ |
| Grafana | http://127.0.0.1:8080/grafana/ |
| Fault injection (flagd) | http://127.0.0.1:8080/feature |
| Prometheus | http://127.0.0.1:9090 |
| EIOS Postgres | `127.0.0.1:5433`, database `eios`, user `eios` |

## Layout

```
schemas/     shared contracts - the seam every workstream builds against
ingest/      substrate taps, producing normalized events
db/          Postgres DDL, applied on first start
```

## The contracts

Two shapes carry everything. Agree changes to them as a team, because all four
workstreams depend on them.

`NormalizedEvent` flattens all three detection domains into one form. Numeric
signals go in `metrics`, which is the only field detection reads; context goes
in `attributes`, which investigation and correlation read.

`Incident` is what a detector emits. `detector` records which one fired, so
rule and model results stay comparable on the same window. `labels` carries
ground truth such as `{"injected_fault": "paymentFailure"}`, which is what lets
the Stage 3 harness score precision and recall without hand labelling.

## Taps

| Domain | Source | Notes |
| --- | --- | --- |
| B, e-commerce | Kafka topic `orders` | Protobuf `OrderResult` from checkout. EIOS joins as its own consumer group, so accounting and fraud-detection still receive every order. |
| C, infrastructure | Prometheus | Container CPU and memory. Metrics arrive by OTLP push, not scraping, so there is no `up` series and querying it returns empty. That is normal. |
| A, attack | not built yet | The demo has no authentication at all, so attack traffic has to be generated. Arrives over the same sink. |

## Injecting faults

Toggle flags at http://127.0.0.1:8080/feature. Read the live flag list from
flagd's OFREP endpoint rather than the published documentation, which is out of
date: the running build uses shorter keys such as `paymentFailure`, not
`paymentServiceFailure`.

Useful ones: `paymentFailure`, `cartFailure` and `productCatalogFailure` for
domain B; `emailMemoryLeak`, `adHighCpu` and `kafkaQueueProblems` for domain C.

Every toggle should be recorded in the `fault_windows` table. That table is the
ground truth the evaluation harness scores against, so a fault that is not
recorded is a fault that cannot be measured.

## Repository layout

This repository contains the EIOS layer only. The substrate it observes, the
OpenTelemetry Demo, is a separate upstream project and is deliberately not
vendored here: EIOS attaches to it without modifying a single upstream file, so
the substrate stays updatable with a plain `git pull`.

`ingest/proto/demo.proto` is the one exception. It is copied from the demo
(Apache-2.0) so the ingest service can decode the protobuf order messages that
checkout publishes to Kafka.

## First-time setup

```
# 1. Clone this repository and the substrate side by side
git clone https://github.com/Krish-0p/EIOS.git eios
git clone https://github.com/open-telemetry/opentelemetry-demo.git

# 2. Bring both up together, from the demo directory
cd opentelemetry-demo
docker compose -f compose.yaml -f compose.full.yaml \
               -f compose.observability.yaml -f ../eios/compose.eios.yaml up -d
```

The two directories must sit next to each other, because the EIOS compose file
refers to build contexts at `../eios`.

Docker needs roughly 8 GB of memory for the full stack. If it is tight, drop
`opensearch` and `telemetry-docs` from the observability layer — neither is a
signal EIOS reads.

docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml -f ../eios/compose.eios.yaml up -d

.\eios\start.ps1   
.\eios\start.ps1 -Demo 