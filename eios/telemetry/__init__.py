"""Shared telemetry identity, bounded source queries, and provenance."""

from uuid import UUID, uuid5

DEFAULT_APPLICATION_ID = UUID("6b42866e-e214-57e4-a7bd-e0ce18ade732")


def source_id(application_id, kind):
    return uuid5(UUID(str(application_id)), f"telemetry:{kind}")
