from .redactor import redact, redact_dict, redact_event
from .audit import AuditLogger

__all__ = ["redact", "redact_dict", "redact_event", "AuditLogger", "RateLimiter", "make_rate_limit_dep"]


def __getattr__(name):
    """Redaction workers do not need the API framework's rate-limit helpers."""
    if name in ("RateLimiter", "make_rate_limit_dep"):
        from . import ratelimit
        return getattr(ratelimit, name)
    raise AttributeError(name)
