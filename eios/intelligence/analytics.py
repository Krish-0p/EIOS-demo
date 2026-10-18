"""Evidence-based KPI findings and bounded memory trend forecasts."""
from datetime import timedelta
import math
import numpy as np

from . import config


from .recommendations import recommendation


def kpi_findings(window, history):
    features = window["features"]
    result = []
    for name, threshold, signal, title in (
        ("memory_fraction", config.MEMORY_WARN, "memory", "Memory approaching its limit"),
        ("error_fraction", config.ERROR_WARN, "errors", "Request errors above configured objective"),
        ("latency_p95_ms", config.P95_WARN_MS, "latency", "p95 latency above configured objective"),
    ):
        if name not in features or features[name] < threshold:
            continue
        if signal in ("errors", "latency") and features.get("request_rate_per_sec", 0) <= 0:
            continue
        critical = (name == "memory_fraction" and features[name] >= .95) or (name == "error_fraction" and features[name] >= .20)
        result.append({"kind": "kpi", "detector": f"kpi:{name}:v1",
            "severity": "critical" if critical else "medium", "title": f"{window['service']}: {title}",
            "measurements": features, "baseline": {"metric": name, "warning_threshold": threshold},
            "analysis": {"candidate_cause": "Threshold breach observed; cause requires investigation",
                "score_meaning": "Operational objective, not a learned anomaly probability"},
            "score": min(1.0, features[name] / (threshold * 2)), "signal": signal})
    # Absence is meaningful only with a healthy order source and request traffic.
    past = [w for w in history if window["window_start"] - timedelta(minutes=10) <= w["window_start"] < window["window_start"]
        and w["quality"].get("orders_source_healthy") and "orders_per_min" in w["features"]]
    if len(past) >= 5 and window["quality"].get("orders_source_healthy") and features.get("request_rate_per_sec", 0) > 0:
        baseline = float(np.median([w["features"]["orders_per_min"] for w in past]))
        orders = features.get("orders_per_min")
        if baseline >= 1 and orders is not None and orders <= baseline * .3:
            result.append({"kind": "kpi", "detector": "kpi:order_rate_drop:v1", "severity": "high",
                "title": "checkout: order throughput below recent reference", "measurements": features,
                "baseline": {"orders_per_min": baseline}, "analysis": {"candidate_cause":
                    "Orders decreased with collector health and request traffic present. Check checkout and payment evidence."},
                "score": min(1.0, 1 - orders / baseline), "signal": "orders"})
    return result


def memory_forecast(history, now, horizon_minutes=10):
    """Linear trend, with explicit abstention and measured backtest error.

    Drops, large gaps, unstable residuals and a failed persistence comparison
    suppress predictions. No unvalidated confidence band is displayed.
    """
    history = sorted(history, key=lambda w: w["window_end"])
    samples = [w for w in history if "memory_fraction" in w["features"]
        and now - timedelta(minutes=30) <= w["window_end"] <= now]
    result = {"state": "abstained", "reason": "insufficient_history", "values": {}, "evidence_event_ids": []}
    if len(samples) < 12:
        return result
    times = [w["window_end"] for w in samples]
    if (now - times[-1]).total_seconds() > config.FRESH_SECONDS:
        result["reason"] = "stale_data"
        return result
    if max((b-a).total_seconds() for a,b in zip(times, times[1:])) > 120:
        result["reason"] = "history_gap"
        return result
    x = np.array([(t-times[0]).total_seconds()/60 for t in times])
    y = np.array([w["features"]["memory_fraction"] for w in samples])
    if np.any(np.diff(y) < -.05):
        result["reason"] = "possible_restart_or_memory_release"
        return result
    slope, intercept = np.polyfit(x, y, 1)
    residual = float(np.mean(np.abs(y - (slope*x + intercept))))
    if residual > .025:
        result["reason"] = "unstable_trend"
        return result
    # Rolling-origin validation at the requested horizon; never fit future samples.
    errors, naive_errors = [], []
    for i in range(5, len(samples)):
        target = next((j for j in range(i+1, len(samples)) if x[j]-x[i] >= horizon_minutes), None)
        if target is None:
            continue
        a,b = np.polyfit(x[:i+1], y[:i+1], 1)
        errors.append(abs(float(a*x[target]+b-y[target])))
        naive_errors.append(abs(float(y[i]-y[target])))
    if len(errors) < 3:
        result["reason"] = "insufficient_horizon_validation"
        return result
    mae, persistence = float(np.mean(errors)), float(np.mean(naive_errors))
    if mae > persistence + .002:
        result["reason"] = "trend_worse_than_persistence"
        return result
    projected = float(y[-1] + slope * horizon_minutes)
    minutes_to_warning = ((config.MEMORY_WARN-y[-1]) / slope) if slope > .0001 and y[-1] < config.MEMORY_WARN else None
    result.update(state="ready", reason=None, values={
        "current_memory_fraction": float(y[-1]), "projected_memory_fraction": max(0.0, projected),
        "slope_fraction_per_minute": float(slope), "warning_threshold": config.MEMORY_WARN,
        "minutes_to_warning": float(minutes_to_warning) if minutes_to_warning is not None else None,
        "warning": bool(slope > .0001 and y[-1] < config.MEMORY_WARN <= projected),
        "validation_mae_fraction": mae, "persistence_mae_fraction": persistence,
        "validation_samples": len(errors), "residual_mae_fraction": residual,
        "limitation": "Local linear trend; no calibrated uncertainty band or guaranteed failure time"},
        evidence_event_ids=sorted({str(e) for w in samples for e in w["evidence_event_ids"]}))
    return result
