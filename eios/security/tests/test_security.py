"""Security tests — no DB/Kafka required."""
import pytest
from security.redactor import redact, redact_dict
from security.ratelimit import RateLimiter


# ── Redactor ──────────────────────────────────────────────────────────────────

def test_jwt_redacted():
    assert "[JWT_REDACTED]" in redact("token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123")

def test_password_redacted():
    assert "[PASSWORD_REDACTED]" in redact("password=mysecret123")

def test_api_key_redacted():
    assert "[API_KEY_REDACTED]" in redact("api_key=ABCDEFGHIJKLMNOP12")

def test_card_redacted():
    assert "[CARD_REDACTED]" in redact("card: 4111111111111111")

def test_dsn_redacted():
    assert "[REDACTED]" in redact("postgresql://user:mypassword@host/db")

def test_clean_text_unchanged():
    assert redact("hello world") == "hello world"

def test_redact_dict():
    d = {"url": "postgresql://u:secret@host/db", "safe": "value"}
    r = redact_dict(d)
    assert "[REDACTED]" in r["url"]
    assert r["safe"] == "value"


# ── Rate limiter ──────────────────────────────────────────────────────────────

def test_allows_under_limit():
    lim = RateLimiter(5, 60)
    assert all(lim.is_allowed("k") for _ in range(5))

def test_blocks_over_limit():
    lim = RateLimiter(2, 60)
    lim.is_allowed("k"); lim.is_allowed("k")
    assert not lim.is_allowed("k")

def test_different_keys_independent():
    lim = RateLimiter(1, 60)
    lim.is_allowed("a")
    assert lim.is_allowed("b")
