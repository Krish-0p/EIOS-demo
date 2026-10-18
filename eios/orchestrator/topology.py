"""Service topology and health, read from the substrate's own telemetry.

Two sources, both already running in the demo:

* **Prometheus** carries the `span_metrics` connector output, so RED figures
  (rate, errors, duration) exist per service without instrumenting anything
  new. It also carries `docker_stats`, which is where CPU and memory come from.
* **Jaeger** derives a service dependency graph from the traces it stores, so
  the call graph needs no separate collection either.

Nothing here writes. A failure to reach either backend degrades the view to
"unknown" rather than failing the request, because the dashboard showing
labelled gaps beats it showing an error page.
"""

from __future__ import annotations

import logging
import json
import time
from typing import Any, Iterable

import httpx

import config
from telemetry.queries import prom_query, vector, dependencies as query_dependencies

log = logging.getLogger("eios.topology")

# The spanmetrics connector always emits service.name, span.name, span.kind and
# status.code as dimensions; OTLP ingestion turns the dots into underscores.
ERROR_STATUS = "STATUS_CODE_ERROR"


def _prom(client: httpx.Client, expr: str) -> list[dict]:
    return prom_query(client,expr,timeout=config.PROM_TIMEOUT)


def _by_label(series: Iterable[dict], label: str) -> dict[str, float]:
    """Collapse an instant vector to {label value: sample}, dropping NaNs."""
    return {key:value for key,(_,value) in vector(series,label).items()}


def _scale(values: dict[str, float], factor: float) -> dict[str, float]:
    return {key: value * factor for key, value in values.items()}


def _kind_selector(client: httpx.Client, window: str) -> str:
    """Prefer inbound spans, but only if the label is actually present.

    `calls_total` counts client spans too, so an unfiltered rate double counts
    a request at both ends of a hop. Filtering on span_kind fixes that, and
    falling back keeps this working if a collector build drops the dimension.
    """
    probe = (
        "sum(rate(traces_span_metrics_calls_total"
        f'{{span_kind="SPAN_KIND_SERVER"}}[{window}]))'
    )
    try:
        if _prom(client, probe):
            return '{span_kind="SPAN_KIND_SERVER"}'
    except Exception:
        log.debug("span_kind probe failed, counting every span kind")
    return ""


def _merge_selector(selector: str, extra: str) -> str:
    """Add a matcher to a selector that may be empty."""
    if not selector:
        return "{" + extra + "}"
    return selector[:-1] + "," + extra + "}"


def _blank_row(name: str) -> dict[str, Any]:
    return {
        "service": name,
        "rate_per_sec": None,
        "error_rate_per_sec": None,
        "error_ratio": None,
        "latency_p95_ms": None,
        "latency_p99_ms": None,
        "cpu_ratio": None,
        "memory_ratio": None,
        "sources": [],
    }


def collect(window: str | None = None) -> dict[str, Any]:
    """One health row per service, plus a note of any source that was down."""
    window = window or config.HEALTH_WINDOW
    rows: dict[str, dict[str, Any]] = {}
    degraded_sources: list[str] = []

    def row(name: str) -> dict[str, Any]:
        return rows.setdefault(name, _blank_row(name))

    try:
        with httpx.Client(base_url=config.PROMETHEUS_URL) as client:
            selector = _kind_selector(client, window)
            errored = _merge_selector(selector, 'status_code="' + ERROR_STATUS + '"')

            calls = _by_label(
                _prom(
                    client,
                    "sum by (service_name) (rate(traces_span_metrics_calls_total"
                    f"{selector}[{window}]))",
                ),
                "service_name",
            )
            errors = _by_label(
                _prom(
                    client,
                    "sum by (service_name) (rate(traces_span_metrics_calls_total"
                    f"{errored}[{window}]))",
                ),
                "service_name",
            )
            p95 = _by_label(
                _prom(
                    client,
                    "histogram_quantile(0.95, sum by (service_name, le) "
                    "(rate(traces_span_metrics_duration_milliseconds_bucket"
                    f"{selector}[{window}])))",
                ),
                "service_name",
            )
            p99 = _by_label(
                _prom(
                    client,
                    "histogram_quantile(0.99, sum by (service_name, le) "
                    "(rate(traces_span_metrics_duration_milliseconds_bucket"
                    f"{selector}[{window}])))",
                ),
                "service_name",
            )
            # Both carry a `_ratio` suffix but are served as percentages, 0-100
            # (verified against a live Prometheus: memory peaks at ~95, not
            # ~0.95). Normalise here so everything downstream is a true ratio.
            cpu = _scale(
                _by_label(
                    _prom(client, "container_cpu_utilization_ratio"), "container_name"
                ),
                0.01,
            )
            memory = _scale(
                _by_label(
                    _prom(client, "container_memory_percent_ratio"), "container_name"
                ),
                0.01,
            )
            # Every service that has reported any telemetry, so one that has
            # gone quiet still appears rather than vanishing from the table.
            known = _by_label(_prom(client, "target_info"), "service_name")

        for name, value in calls.items():
            entry = row(name)
            entry["rate_per_sec"] = value
            entry["sources"].append("spanmetrics")
        for name, value in errors.items():
            row(name)["error_rate_per_sec"] = value
        for name, value in p95.items():
            row(name)["latency_p95_ms"] = value
        for name, value in p99.items():
            row(name)["latency_p99_ms"] = value
        for name, value in cpu.items():
            entry = row(name)
            entry["cpu_ratio"] = value
            entry["sources"].append("docker")
        for name, value in memory.items():
            row(name)["memory_ratio"] = value
        for name in known:
            row(name)["sources"].append("target_info")
    except Exception as exc:
        log.warning("prometheus unreachable: %s", exc)
        degraded_sources.append("prometheus")

    for entry in rows.values():
        rate = entry["rate_per_sec"]
        errs = entry["error_rate_per_sec"]
        if rate:
            entry["error_ratio"] = (errs or 0.0) / rate
        entry["sources"] = sorted(set(entry["sources"]))
        entry["status"], entry["reason"] = _classify(entry)

    return {
        "window": window,
        "services": sorted(rows.values(), key=lambda r: r["service"]),
        "degraded_sources": degraded_sources,
        "jaeger_ui": config.JAEGER_UI_URL,
    }


def _classify(entry: dict[str, Any]) -> tuple[str, str]:
    """Worst matching condition wins, and the reason says which one it was.

    Explicit thresholds rather than a model: this is the substrate health
    panel, and it has to stay readable when a detector disagrees with it.
    """
    ratio = entry["error_ratio"]
    p95 = entry["latency_p95_ms"]
    cpu = entry["cpu_ratio"]
    memory = entry["memory_ratio"]

    if ratio is not None and ratio >= config.ERROR_RATIO_CRITICAL:
        return "critical", f"{ratio:.0%} of calls failing"
    if memory is not None and memory >= config.MEMORY_CRITICAL:
        return "critical", f"memory at {memory:.0%}"

    if ratio is not None and ratio >= config.ERROR_RATIO_WARN:
        return "degraded", f"{ratio:.1%} of calls failing"
    if p95 is not None and p95 >= config.LATENCY_P95_WARN_MS:
        return "degraded", f"p95 {p95:.0f}ms"
    if cpu is not None and cpu >= config.CPU_WARN:
        return "degraded", f"CPU at {cpu:.0%}"
    if memory is not None and memory >= config.MEMORY_WARN:
        return "degraded", f"memory at {memory:.0%}"

    if entry["rate_per_sec"]:
        return "healthy", "serving traffic"
    if entry["cpu_ratio"] is not None:
        # The container is up and reporting stats, it just is not being called.
        return "idle", "up, no traffic in window"
    return "unknown", "no telemetry in window"


def graph(lookback_hours: int | None = None) -> dict[str, Any]:
    """Service call graph, as Jaeger derives it from stored traces.

    Jaeger's memory backend recomputes this from whatever traces it still
    holds, so the graph is only as deep as MEMORY_MAX_TRACES allows.
    """
    hours = lookback_hours or config.GRAPH_LOOKBACK_HOURS
    end_ms = int(time.time() * 1000)
    lookback_ms = hours * 3600 * 1000
    try:
        with httpx.Client(base_url=config.JAEGER_URL) as client:
            data = query_dependencies(client,lookback_ms,timeout=config.PROM_TIMEOUT)
    except Exception as exc:
        log.warning("jaeger dependencies unavailable: %s", exc)
        return {"edges": [], "nodes": [], "available": False, "reason": str(exc)}

    # Jaeger reports a self-edge whenever one span calls another inside the
    # same service, which is most of them. On a topology map that is noise: it
    # draws as a degenerate loop and makes a service its own neighbour.
    edges = [
        {
            "source": item.get("parent"),
            "target": item.get("child"),
            "calls": item.get("callCount", 0),
        }
        for item in data
        if item.get("parent")
        and item.get("child")
        and item.get("parent") != item.get("child")
    ]
    nodes = sorted({name for edge in edges for name in (edge["source"], edge["target"])})
    return {"edges": edges, "nodes": nodes, "available": True, "reason": None}


def operations(service: str, window: str | None = None, limit: int = 8) -> list[dict]:
    """Busiest spans for one service, so a bad row can be opened up."""
    window = window or config.HEALTH_WINDOW
    try:
        with httpx.Client(base_url=config.PROMETHEUS_URL) as client:
            selector = _kind_selector(client, window)
            scoped = _merge_selector(selector, 'service_name=' + json.dumps(service))
            errored = _merge_selector(scoped, 'status_code="' + ERROR_STATUS + '"')

            calls = _by_label(
                _prom(
                    client,
                    "sum by (span_name) (rate(traces_span_metrics_calls_total"
                    f"{scoped}[{window}]))",
                ),
                "span_name",
            )
            errors = _by_label(
                _prom(
                    client,
                    "sum by (span_name) (rate(traces_span_metrics_calls_total"
                    f"{errored}[{window}]))",
                ),
                "span_name",
            )
            p95 = _by_label(
                _prom(
                    client,
                    "histogram_quantile(0.95, sum by (span_name, le) "
                    "(rate(traces_span_metrics_duration_milliseconds_bucket"
                    f"{scoped}[{window}])))",
                ),
                "span_name",
            )
    except Exception as exc:
        log.warning("operation breakdown failed for %s: %s", service, exc)
        return []

    rows = [
        {
            "span_name": name,
            "rate_per_sec": rate,
            "error_rate_per_sec": errors.get(name, 0.0),
            "error_ratio": (errors.get(name, 0.0) / rate) if rate else None,
            "latency_p95_ms": p95.get(name),
        }
        for name, rate in calls.items()
    ]
    rows.sort(key=lambda r: r["rate_per_sec"], reverse=True)
    return rows[:limit]
