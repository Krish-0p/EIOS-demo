"""Continuous, restart-safe inference; resource-changing actions remain manual."""
from datetime import datetime, timedelta, timezone
import logging
import math
import signal
import time
import threading

from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
from pydantic import ValidationError
from schemas import NormalizedEvent, Incident

from . import config
from .features import build_windows, FEATURE_VERSION
from .analytics import kpi_findings, memory_forecast
from .models import load, infer
from .store import Store
from .evidence import dependencies, correlate

log = logging.getLogger("eios.intelligence")


def commit_pending(consumer):
    """Retry transient group coordination without discarding durable offsets."""
    try:
        consumer.commit(asynchronous=False)
        return True
    except KafkaException as exc:
        error=exc.args[0]
        if error.code()==KafkaError._NO_OFFSET:
            return True
        coordination_codes={KafkaError.NOT_COORDINATOR,KafkaError.COORDINATOR_NOT_AVAILABLE,
                            KafkaError.REBALANCE_IN_PROGRESS,KafkaError.ILLEGAL_GENERATION,
                            KafkaError.UNKNOWN_MEMBER_ID,KafkaError._WAIT_COORD,KafkaError._STATE}
        if error.retriable() or error.code() in coordination_codes:
            log.warning('Offset commit postponed (Kafka code %s); durable input remains replayable',error.code())
            return False
        raise


def evaluate(store, cache, now, graph=None):
    cutoff = now-timedelta(seconds=config.LATENESS_SECONDS)
    observations = store.rows("""SELECT * FROM events WHERE observed_at > %s AND observed_at <= %s
        AND COALESCE(application_id,'6b42866e-e214-57e4-a7bd-e0ce18ade732'::uuid)='6b42866e-e214-57e4-a7bd-e0ce18ade732'::uuid
        AND ingested_at <= date_trunc('minute',observed_at)+INTERVAL '1 minute'+(%s*INTERVAL '1 second')
        AND (attributes->>'feature_version'=%s OR entity_kind='order')
        ORDER BY observed_at,event_id""", (now-timedelta(hours=1),cutoff,config.LATENESS_SECONDS,FEATURE_VERSION))
    store.upsert_windows(build_windows(observations, cutoff))
    latest = store.rows("""SELECT DISTINCT ON(service) * FROM feature_windows
        WHERE feature_version=%s AND application_id='6b42866e-e214-57e4-a7bd-e0ce18ade732'::uuid
        ORDER BY service,window_end DESC""", (FEATURE_VERSION,))
    models = {r["service"]: r for r in store.rows("SELECT * FROM model_registry WHERE state='active' AND application_id='6b42866e-e214-57e4-a7bd-e0ce18ade732'::uuid")}
    active_ids = {str(r["model_id"]) for r in models.values()}
    for key in list(cache):
        if key not in active_ids:
            cache.pop(key)
    ready, stale, scored, abstained = 0,0,0,0
    for window in latest:
        service = window["service"]
        if (now-window["window_end"]).total_seconds() > config.FRESH_SECONDS:
            stale += 1
            continue
        ready += 1
        metric_times = window["quality"].get("metric_last_at",{})
        window = {**window,"features":{name:value for name,value in window["features"].items()
            if name in metric_times and (now-datetime.fromisoformat(metric_times[name])).total_seconds() <= config.FRESH_SECONDS}}
        if not window["features"]:
            stale += 1
            ready -= 1
            continue
        record = models.get(service)
        version = str(record["model_id"]) if record else "rules"
        key = f"window:{service}:{version}"
        if store.window_processed(key,window["window_end"]):
            continue
        history = store.history(service)
        context = correlate(window,latest,graph or {})
        # All outputs plus the processed marker commit together. Replay cannot
        # advance the marker while losing a finding or its notification.
        with store.conn.transaction():
            for finding in kpi_findings(window, history):
                finding["analysis"].update(context)
                store.save_finding(window, finding)
            for horizon in (5,10):
                forecast = memory_forecast(history, now, horizon)
                store.save_forecast(window,horizon,forecast)
                if forecast["state"] == "ready" and forecast["values"]["warning"]:
                    warning = {"kind": "forecast", "detector": f"forecast:memory:{horizon}m:v1",
                        "severity": "medium", "title": f"{service}: memory trend approaches warning threshold",
                        "measurements": window["features"], "baseline": {"warning_threshold": config.MEMORY_WARN},
                        "analysis": {**forecast["values"],**context}, "signal": "memory", "score": .5}
                    store.save_finding({**window,"evidence_event_ids":forecast["evidence_event_ids"]}, warning)
            if record:
                try:
                    if version not in cache:
                        cache[version] = load(record)
                    analysis,finding = infer(cache[version],record,window)
                except (ValueError, OSError) as exc:
                    analysis,finding = {"state": "abstained", "reason": str(exc)},None
                    log.error("model unavailable for %s: %s",service,exc)
                store.state(f"inference:{service}", {**analysis, "window_end":window["window_end"].isoformat()})
                if analysis["state"] == "ready":
                    scored += 1
                    store.conn.execute("UPDATE model_registry SET last_inference_at=%s WHERE model_id=%s", (now,record["model_id"]))
                else:
                    abstained += 1
                if finding:
                    finding["analysis"].update(context)
                    store.save_finding(window,finding,record["model_id"])
            store.state(key,{"processed_at":now.isoformat(),"window_end":window["window_end"].isoformat()})
    store.state("worker", {"state":"ready" if ready else "unavailable", "last_analysis_at":now.isoformat(),
        "fresh_services":ready,"stale_services":stale,"active_models":len(models),
        "scored_windows_this_cycle":scored,"abstained_windows_this_cycle":abstained,
        "lateness_seconds":config.LATENESS_SECONDS,"feature_version":FEATURE_VERSION})


def validate_event(payload, now):
    event = NormalizedEvent.model_validate_json(payload)
    if event.observed_at.tzinfo is None or event.ingested_at.tzinfo is None:
        raise ValueError("Event timestamps require timezones")
    if event.observed_at > now+timedelta(seconds=60):
        raise ValueError("Event timestamp is in the future")
    if any(not math.isfinite(value) for value in event.metrics.values()):
        raise ValueError("Event contains non-finite metrics")
    return event


def main():
    logging.basicConfig(level=config.LOG_LEVEL,format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    store = Store()
    consumer = Consumer({"bootstrap.servers":config.KAFKA_ADDR,"group.id":config.GROUP,
        "auto.offset.reset":"earliest","enable.auto.commit":False,"enable.auto.offset.store":False,
        "max.poll.interval.ms":300000})
    producer = Producer({"bootstrap.servers":config.KAFKA_ADDR,"enable.idempotence":True,
        "message.timeout.ms":10000})
    consumer.subscribe([config.EVENTS_TOPIC,config.INCIDENTS_TOPIC])
    cache = {}
    next_eval,next_publish,next_commit,next_graph = 0,0,0,0
    graph = {}
    pending_offsets = False
    store.state("worker",{"state":"starting"})
    try:
        while not stop.is_set():
            msg = consumer.poll(.1)
            if msg is not None:
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        log.warning("Kafka: %s",msg.error())
                else:
                    try:
                        if msg.topic() == config.EVENTS_TOPIC:
                            store.ingest(validate_event(msg.value(),datetime.now(timezone.utc)))
                        else:
                            store.enrich_incident(Incident.model_validate_json(msg.value()))
                    except (ValidationError,ValueError):
                        # No raw input or validator text: it may contain secrets.
                        store.reject(msg,"Invalid contract, timestamp, or numeric metric")
                        log.warning("Rejected %s:%s:%s",msg.topic(),msg.partition(),msg.offset())
                    # Database failures escape and restart the worker before
                    # offset commit; Kafka then replays the durable input.
                    consumer.store_offsets(message=msg)
                    pending_offsets = True
            current = time.monotonic()
            if pending_offsets and current >= next_commit:
                pending_offsets = not commit_pending(consumer)
                next_commit = current+1
            if current >= next_eval:
                if current >= next_graph:
                    graph = dependencies()
                    next_graph = current+300
                evaluate(store,cache,datetime.now(timezone.utc),graph)
                next_eval = current+config.EVAL_SECONDS
            if current >= next_publish:
                store.publish_pending(producer,limit=200)
                next_publish = current+5
    except Exception:
        try:
            store.state("worker",{"state":"error","process_state":"error"})
        except Exception:
            pass
        raise
    finally:
        consumer.close()
        producer.flush(3)
        store.close()


if __name__ == "__main__":
    main()
