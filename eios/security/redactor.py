"""PII and secrets redaction utility for EIOS.

Redacts sensitive data from strings and event objects before
they reach Kafka, PostgreSQL, logs, or the AI layer.
"""

from __future__ import annotations
import re
import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Compiled patterns ──────────────────────────────────────────────────────────
_PATTERNS = [
    # JWT (3 base64url parts)
    (re.compile(r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"), "[JWT_REDACTED]"),
    # Bearer tokens
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_=+/]{16,}"), "bearer [REDACTED]"),
    # Authorization header value
    (re.compile(r"(?i)(authorization|x-api-key)\s*:\s*\S+"), r"\1: [REDACTED]"),
    # API keys
    (re.compile(r"(?i)(api[_\-]?key|apikey|api_secret)\s*[=:\s]\s*[\"']?([A-Za-z0-9\-_]{16,})"), r"\1=[API_KEY_REDACTED]"),
    # Passwords in key=value
    (re.compile(r"(?i)(password|passwd|pwd)\s*[=:\s]\s*[\"']?([^\s\"',;]+)"), r"\1=[PASSWORD_REDACTED]"),
    # DSN with password
    (re.compile(r"(postgresql|mysql|redis|mongodb)://([^:]+):([^@]+)@"), r"\1://\2:[REDACTED]@"),
    # AWS keys
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[AWS_KEY_REDACTED]"),
    # Credit cards (basic Luhn patterns)
    (re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"), "[CARD_REDACTED]"),
    # Private key blocks
    (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----", re.DOTALL), "[PRIVATE_KEY_REDACTED]"),
]


def redact(text: str) -> str:
    """Apply all redaction patterns to a string."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(d: dict) -> dict:
    """Recursively redact all string values in a dict."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = redact(v)
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        elif isinstance(v, list):
            result[k] = [redact(i) if isinstance(i, str) else i for i in v]
        else:
            result[k] = v
    return result


def redact_event(event):
    """Return a copy of NormalizedEvent with attributes redacted."""
    safe = copy.copy(event)
    safe.attributes = redact_dict(dict(event.attributes))
    return safe
