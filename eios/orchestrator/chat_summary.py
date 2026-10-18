"""Plain-language summaries of observed telemetry, without inferred root causes."""
from datetime import timezone


def request_summary(windows):
    def impact(window):
        values = window["features"]
        return max(values.get("error_fraction", 0) / .02,
                   values.get("latency_p95_ms", 0) / 500)

    relevant = [w for w in windows if any(key in w["features"] for key in
        ("request_rate_per_sec", "error_fraction", "latency_p95_ms", "orders_per_min"))]
    if not relevant:
        return ["No fresh request, error, latency, or order measurements are available. "
                "Check telemetry collection before drawing conclusions about service health."]

    ranked = sorted(relevant, key=lambda w: (-impact(w), w["service"]))
    affected = [w for w in ranked if impact(w) >= 1]
    selected = (affected or ranked)[:3]
    lines = [f"{selected[0]['service']} needs attention in this snapshot." if affected else
             "No elevated error ratio or latency was found in the available measurements. "
             "Missing measurements may still hide problems."]
    for window in selected:
        values = window["features"]
        details = []
        if "error_fraction" in values:
            details.append(f"Measured request error ratio: {values['error_fraction']:.1%}.")
        if "latency_p95_ms" in values:
            latency = values["latency_p95_ms"]
            duration = f"{latency / 1000:.2f} seconds" if latency >= 1000 else f"{latency:.2f} ms"
            details.append(f"Stored p95 latency: {duration}.")
        if "orders_per_min" in values:
            orders = values["orders_per_min"]
            details.append("No completed orders were observed in this window." if orders == 0 else
                           f"Completed orders: {orders:.2f} per minute.")
        if "request_rate_per_sec" in values:
            rate = values["request_rate_per_sec"] * 60
            details.append(f"Observed traffic: about {rate:.2f} requests per minute.")
            if rate < 5:
                details.append("Traffic is low; a small number of requests can strongly affect the error ratio.")
        observed = window["window_end"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"{window['service']} (window ending {observed})\n" + "\n".join(details))
    if len(affected) > len(selected):
        lines.append(f"{len(affected) - len(selected)} other services have elevated errors or latency. "
                     "See Reports > KPIs for the full view.")
    if affected:
        if any(w["service"] == "checkout" for w in selected):
            lines.append("Next: inspect checkout logs and traces around these times. "
                         "Check payment calls and Kafka publishing for errors. "
                         "These measurements alone do not establish which dependency caused the failure.")
        else:
            lines.append("Next: inspect logs and traces for the affected services around these times "
                         "and check failing or slow dependency calls. The cause is not yet established.")
    lines.append("Latency values average five-minute p95 histogram snapshots; "
                 "they are not the duration of a single transaction.")
    return lines


def intelligence_note(state):
    if state["state"] == "learning":
        return ("Model analysis is learning: no active model is ready to provide inference. "
                "Stored measurements and rule findings remain available.")
    if state["state"] == "unavailable":
        return "Intelligence is unavailable or telemetry is stale. Treat stored findings as historical evidence."
    if state["state"] == "degraded":
        return "Model analysis is partially available; some models are not ready."
    return "Model analysis is ready. Anomaly scores measure unusualness, not failure probability."
