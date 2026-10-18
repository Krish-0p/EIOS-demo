"""Timestamped dependency and neighboring metric evidence, without causal claims."""
from datetime import datetime, timezone
import os
import time
import httpx
from telemetry.queries import dependencies as query_dependencies


def dependencies():
    collected = datetime.now(timezone.utc).isoformat()
    lookback_ms = 3600000
    try:
        with httpx.Client(base_url=os.getenv('JAEGER_URL','http://jaeger:16686')) as client:
            edges = [{"parent":edge['parent'],"child":edge['child'],'call_count':edge.get('callCount',0)}
                for edge in query_dependencies(client,lookback_ms)]
        return {"state":"available","collected_at":collected,"lookback_ms":lookback_ms,"edges":edges}
    except (httpx.HTTPError,ValueError,TypeError):
        return {"state":"unavailable","collected_at":collected,"lookback_ms":lookback_ms,"edges":[]}


def correlate(window, latest, graph):
    service = window["service"]
    edges = [edge for edge in graph.get("edges",[]) if service in (edge["parent"],edge["child"])]
    neighbors = {edge["parent"] for edge in edges}|{edge["child"] for edge in edges}
    neighbors.discard(service)
    related = [{"service":row["service"],"window_end":row["window_end"].isoformat(),
        "measurements":row["features"],"evidence_event_ids":[str(e) for e in row["evidence_event_ids"]]}
        for row in latest if row["service"] in neighbors
        and abs((row["window_end"]-window["window_end"]).total_seconds()) <= 120]
    candidates = [{"service":row["service"],"reason":"Dependency has concurrent request errors",
        "error_fraction":row["measurements"]["error_fraction"],"causality":"unconfirmed"}
        for row in related if row["measurements"].get("error_fraction",0) >= .02]
    return {"dependency_evidence":{"state":graph.get("state","unavailable"),
        "collected_at":graph.get("collected_at"),"lookback_ms":graph.get("lookback_ms"),"edges":edges},
        "related_services":related,"candidate_causes":candidates,
        "causality_limitation":"Concurrent changes and call dependencies support investigation, not proof of root cause"}
