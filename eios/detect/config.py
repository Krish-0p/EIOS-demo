import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


KAFKA_ADDR = os.getenv("KAFKA_ADDR", "kafka:9092")
EVENTS_TOPIC = os.getenv("EIOS_EVENTS_TOPIC", "eios.events")
INCIDENTS_TOPIC = os.getenv("EIOS_INCIDENTS_TOPIC", "eios.incidents")
CONSUMER_GROUP = os.getenv("EIOS_DETECT_GROUP", "eios-detect")

POSTGRES_DSN = os.getenv(
    "EIOS_POSTGRES_DSN", "postgresql://eios:eios@eios-postgres:5432/eios"
)

# How often the rules run. Absence signals (no orders arriving) can only be
# seen on a timer, not on message arrival.
EVAL_SECONDS = _int("EIOS_EVAL_SECONDS", 30)

# Suppress a repeat of the same rule on the same entity for this long, so one
# sustained fault produces one incident rather than a stream of them.
COOLDOWN_SECONDS = _int("EIOS_COOLDOWN_SECONDS", 180)

# Rule state converts source CPU percentages to cores. memory_ratio remains
# percent (0-100); new events also carry explicitly named canonical metrics.
MEM_HIGH = _float("EIOS_MEM_HIGH", 92.0)
MEM_MEDIUM = _float("EIOS_MEM_MEDIUM", 85.0)
CPU_FLOOR = _float("EIOS_CPU_FLOOR", 0.50)
CPU_MULTIPLIER = _float("EIOS_CPU_MULTIPLIER", 3.0)
SUSTAINED_SAMPLES = _int("EIOS_SUSTAINED_SAMPLES", 3)

# Order rate. Baseline is measured over the older part of the window so a
# current collapse stands out against it.
ORDER_BASELINE_MIN = _float("EIOS_ORDER_BASELINE_MIN", 1.0)
ORDER_DROP_RATIO = _float("EIOS_ORDER_DROP_RATIO", 0.30)
ORDER_RECENT_SECONDS = _int("EIOS_ORDER_RECENT_SECONDS", 120)
ORDER_BASELINE_SECONDS = _int("EIOS_ORDER_BASELINE_SECONDS", 600)

LOG_LEVEL = os.getenv("EIOS_LOG_LEVEL", "INFO")
