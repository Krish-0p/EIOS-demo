"""eios-ingest: substrate taps to normalized events.

Two taps run in parallel threads, both writing through one Sink:
  * kafka_tap  - domain B, the substrate's `orders` topic
  * prom_tap   - domain C, container CPU and memory from Prometheus

Domain A arrives later from the attack generator, over the same Sink.
"""

from __future__ import annotations

import logging
import signal
import threading

import config
from sink import Sink

import kafka_tap
import prom_tap


def main() -> None:
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    log = logging.getLogger("eios.ingest")

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    sink = Sink()
    taps = [
        threading.Thread(target=kafka_tap.run, args=(sink, stop), name="kafka-tap"),
        threading.Thread(target=prom_tap.run, args=(sink, stop), name="prom-tap"),
    ]
    for tap in taps:
        tap.start()
    log.info("eios-ingest running, %d taps", len(taps))

    try:
        while not stop.is_set():
            try:
                sink.publish_pending()
            except Exception:
                log.exception("event delivery unavailable; persisted outbox will retry")
            stop.wait(1.0)
    finally:
        stop.set()
        for tap in taps:
            tap.join(timeout=10)
        sink.close()
        log.info("eios-ingest stopped")


if __name__ == "__main__":
    main()
