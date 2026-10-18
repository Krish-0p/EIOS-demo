import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


KAFKA_ADDR = os.getenv("KAFKA_ADDR", "kafka:9092")
ORDERS_TOPIC = os.getenv("KAFKA_TOPIC", "orders")
EVENTS_TOPIC = os.getenv("EIOS_EVENTS_TOPIC", "eios.events")

# Own consumer group, so accounting and fraud-detection keep receiving every
# order. Kafka fans the topic out per group rather than sharing one queue.
CONSUMER_GROUP = os.getenv("EIOS_CONSUMER_GROUP", "eios-ingest")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
PROM_POLL_SECONDS = _int("EIOS_PROM_POLL_SECONDS", 30)

POSTGRES_DSN = os.getenv(
    "EIOS_POSTGRES_DSN",
    "postgresql://eios:eios@eios-postgres:5432/eios",
)

LOG_LEVEL = os.getenv("EIOS_LOG_LEVEL", "INFO")
