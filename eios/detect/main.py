"""eios-detect: rule-based detection over normalized events.

A consumer thread keeps rolling state from `eios.events`; an evaluator thread
runs every rule on a timer. The timer matters because domain B's signal is
absence - orders stopping - which no arriving message can announce.
"""

from __future__ import annotations

import logging
import signal
import threading
import uuid
from datetime import datetime, timezone

from confluent_kafka import Consumer, KafkaError

import config
import rules
from rules import State
from schemas import Incident, NormalizedEvent
from store import Store

log = logging.getLogger("eios.detect")


def consume(state: State, stop: threading.Event) -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": config.KAFKA_ADDR,
            "group.id": config.CONSUMER_GROUP,
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe([config.EVENTS_TOPIC])
    log.info("consuming %s", config.EVENTS_TOPIC)
    try:
        while not stop.is_set():
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.error("kafka error: %s", msg.error())
                continue
            try:
                state.add(NormalizedEvent.model_validate_json(msg.value()))
            except Exception:
                log.exception("bad event, skipping")
    finally:
        consumer.close()


def evaluate(state: State, store: Store, stop: threading.Event) -> None:
    last_fired: dict[str, datetime] = {}

    while not stop.is_set():
        stop.wait(config.EVAL_SECONDS)
        if stop.is_set():
            break

        try:
            findings = rules.evaluate(state)
        except Exception:
            log.exception("rule evaluation failed")
            continue

        if not findings:
            continue

        now = datetime.now(timezone.utc)

        for finding in findings:
            key = finding.detector + "|" + finding.entity.key()
            previous = last_fired.get(key)
            if previous and (now - previous).total_seconds() < config.COOLDOWN_SECONDS:
                continue
            last_fired[key] = now
            labels = store.open_fault_labels(
                finding.domain.value, finding.entity.id
            )

            incident = Incident(
                domain=finding.domain,
                entity=finding.entity,
                window_start=finding.window_start,
                window_end=finding.window_end,
                detector=finding.detector,
                score=finding.score,
                severity=finding.severity,
                title=finding.title,
                features=finding.features,
                evidence_event_ids=[uuid.UUID(e) for e in finding.evidence],
                labels=labels,
            )
            store.save(incident)
            log.info(
                "INCIDENT %s %s score=%.2f labels=%s",
                finding.detector,
                finding.entity.key(),
                finding.score,
                labels,
            )


def main() -> None:
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    state = State()
    store = Store()
    threads = [
        threading.Thread(target=consume, args=(state, stop), name="consume"),
        threading.Thread(target=evaluate, args=(state, store, stop), name="evaluate"),
    ]
    for t in threads:
        t.start()
    log.info("eios-detect running, evaluating every %ss", config.EVAL_SECONDS)

    try:
        while not stop.is_set():
            stop.wait(1.0)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=10)
        store.close()
        log.info("eios-detect stopped")


if __name__ == "__main__":
    main()
