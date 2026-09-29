from __future__ import annotations

from sqlalchemy.orm import Session

RULE_KEYS = (
    "stale_uploader",
    "long_unwatched",
    "never_watched",
    "important_unwatched",
    "low_confidence",
    "login_expired",
    "sync_failed",
    "risk_control",
    "lumirss_failure",
    "ai_failed",
)


def run_scan(db: Session) -> dict:
    """Frozen contract (implemented by the reminders agent):

    Evaluate every rule with thresholds from settings section 'reminders':
    - stale_uploader: last_video_at older than stale_days (per-up, not snoozed,
      not blacklisted, not missing)
    - long_unwatched: last_watched_at older than long_unwatched_days
    - never_watched: followed_at older than never_watched_days AND watched_count==0
    - important_unwatched: UP in an is_important group with a video newer than
      last_watched_at
    - low_confidence: latest pending ai_suggestion with confidence < threshold
    - login_expired / risk_control / sync_failed / lumirss_failure / ai_failed:
      derived from bilibili_account, sync_runs and lumirss_push_log state
    Dedup via dedup_key (unique): create when missing with status='open';
    auto-resolve stale_uploader/long_unwatched/low_confidence reminders whose
    condition cleared (status='resolved'). Snoozed users are skipped.
    Returns {"created": int, "resolved": int}.
    """
    raise NotImplementedError("implemented by the reminders agent")


def acknowledge(db: Session, reminder_id: int) -> bool:
    raise NotImplementedError("implemented by the reminders agent")
