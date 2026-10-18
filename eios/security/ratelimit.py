"""Sliding-window in-memory rate limiter."""

from __future__ import annotations
import threading
import time
from collections import deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, requests: int, window_seconds: int) -> None:
        self._max = requests
        self._window = window_seconds
        self._buckets: dict[str, deque] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = deque()
            dq = self._buckets[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self._max:
                return False
            dq.append(now)
            return True


def make_rate_limit_dep(limiter: RateLimiter, key_fn=None):
    """Return a FastAPI dependency that enforces rate limiting."""

    async def _dep(request: Request):
        key = key_fn(request) if key_fn else (request.client.host if request.client else "unknown")
        if not limiter.is_allowed(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return _dep
