"""Versioned manual investigation recommendations."""
def recommendation(service, signal):
    catalog = {
        "cpu": ("inspect_cpu", "Investigate CPU workload", "Inspect profiles and traffic changes before changing capacity."),
        "memory": ("inspect_memory", "Investigate memory retention", "Inspect allocations, retention, and the container limit."),
        "errors": ("inspect_errors", "Inspect failing requests and dependencies", "Compare error traces with the change timeline and upstream callers."),
        "latency": ("inspect_latency", "Inspect slow requests", "Compare traces, dependency latency, and request volume."),
        "orders": ("inspect_checkout", "Inspect checkout and payment evidence", "Compare checkout traffic and payment errors before attributing an order drop."),
        "anomaly": ("inspect_evidence", "Review unusual service measurements", "Compare the cited window with its learned reference ranges."),
    }
    action, title, rationale = catalog.get(signal, catalog["anomaly"])
    return {"catalog_version": "1.0", "action": action, "target": service,
        "title": title, "rationale": rationale,
        "preconditions": ["Confirm current telemetry is fresh", "Review cited measurements and request context"],
        "requires_approval": True, "execution": "manual"}


