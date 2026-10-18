"""Safe flagd toggling.

The demo's flagd watches a bind-mounted JSON file and reloads on write. Edit it
as JSON, never as text: flagd validates the whole document, so one bad variant
name anywhere makes it reject every flag in the file and silently keep serving
the old values.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading

log = logging.getLogger("eios.flags")

CONFIG_PATH = os.getenv("FLAGD_CONFIG", "/etc/flagd/demo.flagd.json")
_lock = threading.Lock()


class FlagError(Exception):
    pass


def _load() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _save(doc: dict) -> None:
    """Write atomically so flagd never observes a half-written file.

    mkstemp creates its file 0600 and os.replace carries that mode onto the
    target. flagd runs as a non-root user, so inheriting it locks flagd out of
    its own config and it crash-loops on the next restart - with the damage
    only showing up long after the write that caused it. Force the mode back
    to readable before the file is moved into place.
    """
    directory = os.path.dirname(CONFIG_PATH)
    try:
        mode = stat.S_IMODE(os.stat(CONFIG_PATH).st_mode) | 0o644
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2)
            handle.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def available() -> bool:
    return os.path.exists(CONFIG_PATH)


def list_flags() -> list[dict]:
    doc = _load()
    return [
        {
            "key": key,
            "defaultVariant": flag.get("defaultVariant"),
            "variants": list(flag.get("variants", {}).keys()),
            "description": flag.get("description", ""),
            "on": flag.get("defaultVariant") not in (None, "off"),
        }
        for key, flag in sorted(doc.get("flags", {}).items())
    ]


def set_variant(flag_key: str, variant: str) -> dict:
    """Point a flag at one of its own variants.

    Validated before writing, because an invalid variant would poison the whole
    file for every other flag.
    """
    with _lock:
        doc = _load()
        flags = doc.get("flags", {})
        flag = flags.get(flag_key)
        if flag is None:
            raise FlagError(f"No flag named {flag_key}")

        variants = flag.get("variants", {})
        if variant not in variants:
            raise FlagError(
                f"{flag_key} has no variant {variant}. "
                f"Available: {', '.join(sorted(variants))}"
            )

        previous = flag.get("defaultVariant")
        flag["defaultVariant"] = variant
        _save(doc)
        log.info("flag %s: %s -> %s", flag_key, previous, variant)
        return {"flag_key": flag_key, "previous": previous, "variant": variant}


def turn_off(flag_key: str) -> dict:
    return set_variant(flag_key, "off")


# Which domain and entity each fault is expected to disturb. Without this a
# recorded window cannot attribute anything, and would otherwise label every
# unrelated incident that merely overlapped it.
EXPECTATIONS: dict[str, tuple[str, str | None]] = {
    "paymentFailure": ("ecommerce", "checkout"),
    "paymentUnreachable": ("ecommerce", "checkout"),
    "cartFailure": ("ecommerce", "checkout"),
    "productCatalogFailure": ("ecommerce", "checkout"),
    "adFailure": ("infrastructure", "ad"),
    "adHighCpu": ("infrastructure", "ad"),
    "adManualGc": ("infrastructure", "ad"),
    "emailMemoryLeak": ("infrastructure", "email"),
    "recommendationCacheFailure": ("infrastructure", "recommendation"),
    "kafkaQueueProblems": ("infrastructure", "kafka"),
    "imageSlowLoad": ("infrastructure", "frontend-proxy"),
    "intlShippingSlowdown": ("infrastructure", "shipping"),
    "loadGeneratorFloodHomepage": ("infrastructure", "frontend"),
}


def expectation(flag_key: str) -> tuple[str | None, str | None]:
    return EXPECTATIONS.get(flag_key, (None, None))
