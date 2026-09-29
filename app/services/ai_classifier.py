from __future__ import annotations

from sqlalchemy.orm import Session


def _ai_config(db: Session) -> dict:  # noqa: ANN001
    from app.services.settings_store import get_section_raw

    return get_section_raw(db, "ai")


def run_classification(db: Session, batch_size: int = 20) -> dict:
    """Frozen contract (implemented by the AI agent):

    - config from settings section 'ai'; if not configured raise
      ApiError(400, 'ai_not_configured', ...)
    - pick up to batch_size up_users where ai_status in ('none','error') and
      missing == 0, ordered by followed_at asc
    - build one prompt with existing group names + UP profiles (name, sign,
      recent video titles); call OpenAI-compatible POST {base_url}/chat/completions
      (httpx, 30s timeout, model from settings)
    - parse strict JSON array [{mid, group, confidence (0-1), rationale}]
    - map group names to groups_local (create missing ones with is_important=0,
      color default), insert ai_suggestions rows status='pending'
    - mark ai_status='pending' (awaiting review) on processed users
    - return {"classified": int, "pending": int, "created_groups": [names]}
    - on parse/HTTP failure: mark processed users ai_status='error', raise
      ApiError(502, 'ai_failed', detail)
    """
    raise NotImplementedError("implemented by the AI agent")


def decide(db: Session, ids: list[int], decision: str) -> dict:
    """Shared with review_routes.decide; kept here for scheduled auto-apply
    when confidence >= threshold and auto_apply enabled. Returns {"decided": int}."""
    raise NotImplementedError("implemented by the AI agent")


def test_connection(db: Session) -> tuple[bool, str]:
    """Send a tiny completion; return (ok, message)."""
    raise NotImplementedError("implemented by the AI agent")
