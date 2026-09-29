from __future__ import annotations

from sqlalchemy.orm import Session


def push_items(db: Session, items: list[dict]) -> dict:
    """Frozen contract (implemented by the RSS agent):

    Push entries to LumiRSS inbox ingest: POST {base_url}{inbox_endpoint}
    Authorization: Bearer {token}, JSON items with guid/bvid/title/url/published.
    Per-item idempotency by guid. Log successes/failures to lumirss_push_log.
    On failure create/refresh a lumirss_failure reminder. Retries with backoff
    (max 3). Returns {"pushed": int, "failed": int}.
    """
    raise NotImplementedError("implemented by the RSS agent")


def push_pending(db: Session) -> dict:
    """Push videos newer than the last successful push; no-op with
    {"pushed": 0, "failed": 0} when the section is unconfigured/disabled."""
    raise NotImplementedError("implemented by the RSS agent")


def test_connection(db: Session) -> tuple[bool, str]:
    raise NotImplementedError("implemented by the RSS agent")
