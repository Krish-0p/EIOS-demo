import os


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


KAFKA_ADDR = os.getenv("KAFKA_ADDR", "kafka:9092")
INCIDENTS_TOPIC = os.getenv("EIOS_INCIDENTS_TOPIC", "eios.incidents")
CONSUMER_GROUP = os.getenv("EIOS_ORCH_GROUP", "eios-orchestrator")

POSTGRES_DSN = os.getenv(
    "EIOS_POSTGRES_DSN", "postgresql://eios:eios@eios-postgres:5432/eios"
)

FLAGD_UI_URL = os.getenv("FLAGD_UI_URL", "http://127.0.0.1:8080/feature")
LOG_LEVEL = os.getenv("EIOS_LOG_LEVEL", "INFO")

# Service health and topology sources. Both are container addresses: the
# orchestrator reads them from inside the compose network.
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
JAEGER_URL = os.getenv("JAEGER_URL", "http://jaeger:16686")
PROM_TIMEOUT = _float("EIOS_PROM_TIMEOUT", 15.0)

# Browser-facing Jaeger, for the per-service trace links. Goes through the
# Envoy proxy, and 127.0.0.1 rather than localhost, which resolves to IPv6 and
# times out on the dev machine.
JAEGER_UI_URL = os.getenv("JAEGER_UI_URL", "http://127.0.0.1:8080/jaeger/ui")

# Prometheus scrapes on a 60s interval to match the SDK export interval, so a
# rate window shorter than a few minutes gives a sparse, jumpy reading.
HEALTH_WINDOW = os.getenv("EIOS_HEALTH_WINDOW", "5m")
GRAPH_LOOKBACK_HOURS = _int("EIOS_GRAPH_LOOKBACK_HOURS", 1)

# Health thresholds. Deliberately looser than the detectors: this panel answers
# "is the substrate healthy", not "is this an incident".
ERROR_RATIO_WARN = _float("EIOS_ERROR_RATIO_WARN", 0.02)
ERROR_RATIO_CRITICAL = _float("EIOS_ERROR_RATIO_CRITICAL", 0.20)
LATENCY_P95_WARN_MS = _float("EIOS_LATENCY_P95_WARN_MS", 500.0)
CPU_WARN = _float("EIOS_CPU_WARN", 0.85)
MEMORY_WARN = _float("EIOS_MEMORY_WARN", 0.85)
MEMORY_CRITICAL = _float("EIOS_MEMORY_CRITICAL", 0.95)
