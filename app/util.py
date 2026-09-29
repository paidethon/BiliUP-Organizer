from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> str:
    """Canonical UTC timestamp string, matching SQLite CURRENT_TIMESTAMP format."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def iso_z(ts: str | None) -> str | None:
    """Convert stored timestamps to RFC3339 for API responses."""
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return dt.isoformat().replace("+00:00", "Z")
    except ValueError:
        return ts
