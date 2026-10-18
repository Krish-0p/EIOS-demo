"""The same closed, timestamped feature builder is used for training and inference."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import statistics

FEATURE_VERSION = "2.0"
NUMERIC_FEATURES = (
    "cpu_cores", "memory_fraction", "request_rate_per_sec", "error_rate_per_sec",
    "error_fraction", "latency_p95_ms", "orders_per_min",
)
UNITS = {"cpu_cores": "cores", "memory_fraction": "fraction", "error_fraction": "fraction",
         "request_rate_per_sec": "requests/s", "error_rate_per_sec": "errors/s",
         "latency_p95_ms": "ms", "orders_per_min": "orders/min"}


def bucket(at):
    return at.astimezone(timezone.utc).replace(second=0, microsecond=0)


def build_windows(rows, cutoff):
    """Aggregate unique source samples; never impute missing metrics.

    Gauges and five-minute RED snapshots are averaged within each minute, not
    advertised as a recomputed whole-window latency quantile. Evidence is kept.
    Only complete buckets older than the lateness allowance are eligible.
    """
    groups = defaultdict(list)
    for row in rows:
        if row.get('application_id') and str(row['application_id'])!='6b42866e-e214-57e4-a7bd-e0ce18ade732':
            continue  # Legacy feature/model keys are scoped to the demo.
        at = row["observed_at"]
        if at.tzinfo is None or at > cutoff:
            continue
        start = bucket(at)
        if start + timedelta(minutes=1) > cutoff:
            continue
        service = row.get("entity_service") or row["entity_id"]
        if row["entity_kind"] == "order" or row.get("attributes", {}).get("feature_version") == FEATURE_VERSION:
            groups[(service, start)].append(row)

    output = []
    for (service, start), observations in sorted(groups.items()):
        values = defaultdict(dict)
        evidence = set()
        order_ids = set()
        heartbeats = set()
        latest = {}
        for row in observations:
            at = row["observed_at"]
            if row["entity_kind"] == "order":
                order_ids.add(row["entity_id"])
                evidence.add(str(row["event_id"]))
                continue
            metrics = row["metrics"]
            source_at = at
            if row.get("attributes",{}).get("source_observed_at"):
                try:
                    source_at = datetime.fromisoformat(row["attributes"]["source_observed_at"])
                    if source_at.tzinfo is None or not 0 <= (at-source_at).total_seconds() <= 180:
                        continue
                except ValueError:
                    continue
            if metrics.get("orders_source_healthy") == 1:
                heartbeats.add(at)
                evidence.add(str(row["event_id"]))
            for name in NUMERIC_FEATURES:
                value = metrics.get(name)
                if value is None or not math.isfinite(value) or value < 0:
                    continue
                if name in ("memory_fraction", "error_fraction") and value > 1.05:
                    continue
                # Polling an unchanged source sample does not add coverage.
                key = (row["source"], at)
                values[name][key] = float(value)
                latest[name] = max(source_at, latest.get(name, source_at))
                evidence.add(str(row["event_id"]))
        features = {name: statistics.mean(samples.values()) for name, samples in values.items()}
        healthy_orders = (len(heartbeats) >= 2
            and min(heartbeats) <= start + timedelta(seconds=35)
            and max(heartbeats) >= start + timedelta(seconds=25))
        if order_ids or healthy_orders:
            features["orders_per_min"] = float(len(order_ids))
            latest["orders_per_min"] = max(heartbeats or {r["observed_at"] for r in observations})
        if not features:
            continue
        output.append({"service": service, "window_start": start,
            "window_end": start + timedelta(minutes=1), "feature_version": FEATURE_VERSION,
            "features": features, "evidence_event_ids": sorted(evidence),
            "quality": {"metric_samples": {k: len(v) for k, v in values.items()},
                "metric_last_at": {k: v.isoformat() for k, v in latest.items()},
                "orders_source_healthy": healthy_orders,
                "missing_metrics": [k for k in NUMERIC_FEATURES if k not in features],
                "units": UNITS, "latency_aggregation": "mean_of_5m_p95_snapshots"}})
    return output


def usable(window, names):
    return window["feature_version"] == FEATURE_VERSION and all(
        name in window["features"] and math.isfinite(window["features"][name]) for name in names)


def chronological_split(windows, fraction=0.7, gap_seconds=300):
    """Hold out later windows with a gap covering the RED rolling interval."""
    ordered = sorted(windows, key=lambda w: w["window_start"])
    split = int(len(ordered) * fraction)
    train = ordered[:split]
    if not train:
        return [], []
    boundary = train[-1]["window_end"] + timedelta(seconds=gap_seconds)
    return train, [w for w in ordered[split:] if w["window_start"] >= boundary]
