"""Settings shared by the worker and explicit model lifecycle commands."""
import os
from pathlib import Path

POSTGRES_DSN = os.getenv("EIOS_POSTGRES_DSN", "postgresql://eios:eios@eios-postgres:5432/eios")
KAFKA_ADDR = os.getenv("KAFKA_ADDR", "kafka:9092")
EVENTS_TOPIC = os.getenv("EIOS_EVENTS_TOPIC", "eios.events")
INCIDENTS_TOPIC = os.getenv("EIOS_INCIDENTS_TOPIC", "eios.incidents")
INSIGHTS_TOPIC = os.getenv("EIOS_INTELLIGENCE_TOPIC", "eios.intelligence")
GROUP = os.getenv("EIOS_INTELLIGENCE_GROUP", "eios-intelligence-v1")
EVAL_SECONDS = int(os.getenv("EIOS_INTELLIGENCE_EVAL_SECONDS", "30"))
LATENESS_SECONDS = int(os.getenv("EIOS_INTELLIGENCE_LATENESS_SECONDS", "90"))
FRESH_SECONDS = int(os.getenv("EIOS_INTELLIGENCE_FRESH_SECONDS", "240"))
COOLDOWN_SECONDS = int(os.getenv("EIOS_INTELLIGENCE_COOLDOWN_SECONDS", "180"))
ARTIFACT_DIR = Path(os.getenv("EIOS_MODEL_DIR", "/models"))
MIN_TRAIN_WINDOWS = int(os.getenv("EIOS_MIN_TRAIN_WINDOWS", "60"))
MAX_TRAIN_WINDOWS = int(os.getenv("EIOS_MAX_TRAIN_WINDOWS", "10080"))
MEMORY_WARN = float(os.getenv("EIOS_MEMORY_WARN", "0.85"))
ERROR_WARN = float(os.getenv("EIOS_ERROR_RATIO_WARN", "0.02"))
P95_WARN_MS = float(os.getenv("EIOS_LATENCY_P95_WARN_MS", "500"))
LOG_LEVEL = os.getenv("EIOS_LOG_LEVEL", "INFO")
