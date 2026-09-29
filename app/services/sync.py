from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import SyncRun
from app.util import utcnow


def run_sync_kind(db: Session, kind: str) -> dict:
    """Entry point used by routes and the scheduler.

    kind: followings | watch_history | full | native_groups.
    Returns a stats dict; raises on unrecoverable errors (the caller records
    the failure on the SyncRun row). Maps bilibili AuthExpiredError ->
    login_status='expired' + login_expired reminder, RiskControlError ->
    risk_flag + risk_control reminder.
    """
    if kind == "followings":
        return run_followings_sync(db)
    if kind == "watch_history":
        return run_watch_history_sync(db)
    if kind == "full":
        stats = run_followings_sync(db)
        stats.update(run_watch_history_sync(db))
        return stats
    if kind == "native_groups":
        return run_native_groups_sync(db)
    raise ValueError(f"unknown sync kind: {kind}")


def run_followings_sync(db: Session) -> dict:
    """Frozen contract (implemented by the sync agent):

    - build client from stored cookies (skip cleanly with {"skipped": "not_logged_in"}
      when no cookies)
    - fetch all followings; upsert up_users (new rows: followed_at=now, ai_status='none');
      update uname/sign/face/special; set last_seen_at=now, missing=0 for present,
      missing=1 for previously-seen-but-absent users
    - for new users, optionally fetch latest archive (bounded by rate limits)
    - return {"total": int, "new": int, "updated": int, "missing": int}
    """
    raise NotImplementedError("implemented by the sync agent")


def run_watch_history_sync(db: Session) -> dict:
    """Frozen contract (implemented by the sync agent):

    - fetch recent history (max pages from sync settings, default 5 pages)
    - upsert watch_history rows (unique bvid+view_at)
    - per up: last_watched_at = latest view_at, watched_count = distinct bvid count
      for followed mids only
    - return {"fetched": int, "new": int, "ups_touched": int}
    """
    raise NotImplementedError("implemented by the sync agent")


def run_native_groups_sync(db: Session) -> dict:
    """Refresh the native tag list via bilibili.native_groups.list_tags.

    Returns {"tags": int}. Updates native_group_map.synced_at."""
    from app.services.bilibili.native_groups import list_tags

    tags = list_tags(db)
    return {"tags": len(tags)}


def latest_run(db: Session, kind: str | None = None) -> SyncRun | None:
    query = db.query(SyncRun)
    if kind:
        query = query.filter(SyncRun.kind == kind)
    return query.order_by(SyncRun.id.desc()).first()


def record_run(db: Session, kind: str, fn) -> SyncRun:  # noqa: ANN001
    """Run fn(db) inside a tracked SyncRun row; used by the scheduler."""
    run = SyncRun(kind=kind, status="running")
    db.add(run)
    db.commit()
    try:
        stats = fn(db)
        run.status = "success"
        run.stats_json = json.dumps(stats, ensure_ascii=False)
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error = str(exc)[:2000]
        raise
    finally:
        run.finished_at = utcnow()
        db.commit()
    return run
