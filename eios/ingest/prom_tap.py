"""Canonical container and server-span metrics with source freshness.

Legacy cpu_ratio/memory_ratio remain percentages for compatibility.
New cpu_cores/memory_fraction use explicit units; missing data remains absent.
"""
from __future__ import annotations
import logging
import math
import os
from datetime import datetime, timezone
import httpx
import config
from schemas import Domain, Entity, EntityKind, NormalizedEvent
from sink import Sink
from telemetry.queries import prom_query, vector, selector as label_selector
from telemetry.identity import IdentityError

log = logging.getLogger("eios.prom")
MEMORY_SCALE = float(os.getenv("EIOS_MEMORY_SOURCE_SCALE", "0.01"))
FRESH_SECONDS = 180

def _query(client, expr):
    return prom_query(client,expr)

def _values(series, label):
    return vector(series,label,nonnegative=True)

def collect(client, matchers=None, failures=None):
    now = datetime.now(timezone.utc)
    events = []
    matchers = matchers or {}
    scoped = label_selector(matchers)
    for expr, legacy, canonical, scale in (
        ("container_cpu_utilization_ratio", "cpu_ratio", None, 1),
        ("container_memory_percent_ratio", "memory_ratio", "memory_fraction", MEMORY_SCALE),
    ):
        try:
            query = expr + ('{' + scoped + '}' if scoped else '')
            samples = _values(_query(client, query), "container_name")
            times = _values(_query(client, f"timestamp({query})"), "container_name")
            for name, (_, value) in samples.items():
                if name not in times:
                    continue
                at = datetime.fromtimestamp(times[name][1], timezone.utc)
                if not 0 <= (now - at).total_seconds() <= FRESH_SECONDS:
                    continue
                scaled = value * scale
                if canonical == "memory_fraction" and scaled > 1.05:
                    log.warning("invalid memory unit for %s: %s", name, value)
                    continue
                events.append(NormalizedEvent(
                    domain=Domain.INFRASTRUCTURE, source="prometheus", observed_at=at,
                    entity=Entity(kind=EntityKind.CONTAINER, id=name, service=name),
                    metrics={legacy: value, **({canonical: scaled} if canonical else {})},
                    attributes={"collector": "eios-ingest", "feature_version": "2.0",
                                "unit": "fraction" if canonical else "legacy_utilization"},
                    raw_ref=f"prometheus:{query}:{name}:{at.isoformat()}",
                ))
        except Exception:
            if failures is not None:
                failures.append('container query failed')
            log.exception("container metric unavailable: %s", expr)

    # Utilization is exporter/host-normalized and cannot establish core use.
    # CPU seconds per wall second is cores, independent of host CPU count.
    counter = 'container_cpu_usage_nanoseconds_total' + ('{' + scoped + '}' if scoped else '')
    try:
        samples = _values(_query(client, f'rate({counter}[1m]) / 1e9'), 'container_name')
        times = _values(_query(client, f'timestamp({counter})'), 'container_name')
        for name, (_, cores) in samples.items():
            if name not in times:
                continue
            at = datetime.fromtimestamp(times[name][1], timezone.utc)
            if not 0 <= (now-at).total_seconds() <= FRESH_SECONDS:
                continue
            events.append(NormalizedEvent(
                domain=Domain.INFRASTRUCTURE, source='prometheus', observed_at=at,
                entity=Entity(kind=EntityKind.CONTAINER, id=name, service=name),
                metrics={'cpu_cores':cores},
                attributes={'collector':'eios-ingest','feature_version':'2.1','unit':'cores',
                            'calculation':'rate(container_cpu_usage_nanoseconds_total[1m]) / 1e9'},
                raw_ref=f'prometheus:cpu-time-rate:{name}:{at.isoformat()}',
            ))
    except Exception:
        if failures is not None:
            failures.append('CPU time counter query failed')
        log.exception('CPU core measurement unavailable')

    # Filter inbound server spans to avoid double-counting client spans.
    selector = '{' + label_selector({**matchers,'span_kind':'SPAN_KIND_SERVER'}) + '}'
    errored = '{' + label_selector({**matchers,'span_kind':'SPAN_KIND_SERVER','status_code':'STATUS_CODE_ERROR'}) + '}'
    calls_expr = f"sum by(service_name)(rate(traces_span_metrics_calls_total{selector}[5m]))"
    errors_expr = f"sum by(service_name)(rate(traces_span_metrics_calls_total{errored}[5m]))"
    try:
        calls = _values(_query(client, calls_expr), "service_name")
        errors = _values(_query(client, f"({errors_expr}) or on(service_name) (({calls_expr}) * 0)"), "service_name")
        times = _values(_query(client,
            f"max by(service_name)(timestamp(traces_span_metrics_calls_total{selector}))"), "service_name")
        p95 = _values(_query(client,
            "histogram_quantile(0.95, sum by(service_name,le)(rate("
            f"traces_span_metrics_duration_milliseconds_bucket{selector}[5m])))"), "service_name")
        for name, (_, rate) in calls.items():
            if name not in times:
                continue
            source_at = datetime.fromtimestamp(times[name][1], timezone.utc)
            if not 0 <= (now - source_at).total_seconds() <= FRESH_SECONDS:
                continue
            metrics = {"request_rate_per_sec": rate}
            if name in errors:
                metrics["error_rate_per_sec"] = errors[name][1]
                if rate > 0:
                    metrics["error_fraction"] = min(1.0, errors[name][1] / rate)
            if name in p95 and rate > 0:
                metrics["latency_p95_ms"] = p95[name][1]
            events.append(NormalizedEvent(
                domain=Domain.INFRASTRUCTURE, source="prometheus:spanmetrics", observed_at=now,
                entity=Entity(kind=EntityKind.SERVICE, id=name, service=name),
                metrics=metrics, attributes={"collector": "eios-ingest", "feature_version": "2.0",
                    "source_observed_at": source_at.isoformat(), "rate_window": "5m"},
                raw_ref=f"prometheus:server-red:{name}:{source_at.isoformat()}",
            ))
    except Exception:
        if failures is not None:
            failures.append('server RED query failed')
        log.exception("server span metrics unavailable")
    return events

def run(sink: Sink, stop):
    log.info("polling %s every %ss", config.PROMETHEUS_URL, config.PROM_POLL_SECONDS)
    while not stop.is_set():
        try:
            for source in sink.sources('prometheus'):
                if source['scope'].get('derived_binding'):
                    continue  # Routed by the existing shared container collector.
                failures = []
                try:
                    with httpx.Client(base_url=source['endpoint']) as client:
                        events = collect(client,source['scope'].get('matchers'),failures)
                    emitted = 0
                    for event in events:
                        try:
                            sink.emit(event.model_copy(update={'application_id':source['application_id'],
                                'source_id':source['source_id']}))
                            emitted += 1
                        except IdentityError:
                            # A disabled/incompatible application binding must
                            # not stop collection for the remaining services.
                            log.warning('Metric identity rejected; other services continue')
                    sink.source_health(source['source_id'],error='Partial metric collection failed' if failures else None)
                    log.info("persisted %d metric events through source %s",emitted,source['source_id'])
                except Exception:
                    sink.source_health(source['source_id'],error='Metric collection or persistence failed')
                    log.exception('prometheus source failed')
        except Exception:
            log.exception('prometheus poll failed')
        stop.wait(config.PROM_POLL_SECONDS)
