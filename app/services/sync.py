from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import BilibiliAccount, SyncRun, UpUser, WatchHistory
from app.services.bilibili.errors import AuthExpiredError, RiskControlError
from app.util import utcnow

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
_DEFAULT_HISTORY_PAGES = 5
_DEFAULT_HISTORY_WINDOW = 14  # days; window-based fetch makes day stats complete


def run_sync_kind(db: Session, kind: str) -> dict:
    """Entry point used by routes and the scheduler.

    kind: followings | watch_history | full | native_groups | native_overwrite |
    native_incremental. Returns a stats dict; raises on unrecoverable errors
    (the caller records the failure on the SyncRun row). Maps bilibili
    AuthExpiredError -> login_status='expired' + login_expired reminder,
    RiskControlError -> risk_flag + risk_control reminder.

    "full" (the manual「立即同步」button) pulls followings + watch history and
    then OVERWRITES bilibili native groups from local groups (backup first).
    Scheduled native maintenance uses "native_incremental" (diff-based).
    """
    if kind == "followings":
        stats = run_followings_sync(db)
        stats["archives_refreshed"] = refresh_archives(db)
        return stats
    if kind == "watch_history":
        return run_watch_history_sync(db)
    if kind == "full":
        stats = run_followings_sync(db)
        stats["archives_refreshed"] = refresh_archives(db)
        # history keys are prefixed: both sub-stats used to collide on "new"
        history = run_watch_history_sync(db)
        stats["history_fetched"] = history.get("fetched", 0)
        stats["history_new"] = history.get("new", 0)
        stats["ups_touched"] = history.get("ups_touched", 0)
        from app.services import native_sync

        stats["native"] = native_sync.push_overwrite(db)
        return stats
    if kind == "native_overwrite":
        from app.services import native_sync

        return native_sync.push_overwrite(db)
    if kind == "native_incremental":
        from app.services import native_sync

        return native_sync.push_incremental(db)
    if kind == "native_groups":
        return run_native_groups_sync(db)
    raise ValueError(f"unknown sync kind: {kind}")


def refresh_archives(db: Session) -> int:
    """Refresh recent uploads (title + 分区) for the UPs with the oldest data.

    Bounded per run (default 40 UPs, one request each, shared throttled client)
    so a full refresh converges over a few syncs without hammering upstream.
    """
    from datetime import UTC, datetime, timedelta

    from app.services.bilibili.cookies import load_cookies
    from app.services.bilibili.followings import fetch_recent_archives

    if not load_cookies(db):
        return 0
    cutoff = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    stale = (
        db.query(UpUser)
        .filter(
            UpUser.missing.is_(False),
            (UpUser.last_video_at.is_(None)) | (UpUser.last_video_at < cutoff),
        )
        .order_by(UpUser.last_video_at.asc().nulls_first())
        .limit(40)
        .all()
    )
    if not stale:
        return 0
    return fetch_recent_archives(db, [up.mid for up in stale], max_ups=40)


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
    # Imported inside the function so tests can monkeypatch the fetchers.
    from app.services.bilibili.cookies import load_cookies
    from app.services.bilibili.followings import fetch_followings

    if not load_cookies(db):
        return {"skipped": "not_logged_in"}

    rows = _fetch_guarded(db, fetch_followings, db)
    now = utcnow()

    ups_by_mid: dict[int, UpUser] = {up.mid: up for up in db.query(UpUser).all()}
    seen_mids: set[int] = set()
    new = updated = 0
    for row in rows:
        mid = _int_or(row.get("mid"), None)
        if mid is None or mid in seen_mids:
            continue
        seen_mids.add(mid)
        up = ups_by_mid.get(mid)
        if up is None:
            db.add(
                UpUser(
                    mid=mid,
                    uname=str(row.get("uname") or f"UP {mid}"),
                    sign=str(row.get("sign") or ""),
                    face=str(row.get("face") or ""),
                    official_type=_int_or(row.get("official_type"), -1),
                    special=bool(row.get("special") or False),
                    followed_at=now,
                    ai_status="none",
                    last_seen_at=now,
                    missing=False,
                )
            )
            new += 1
        else:
            if row.get("uname"):
                up.uname = str(row["uname"])
            if row.get("sign") is not None:
                up.sign = str(row["sign"])
            if row.get("face"):
                up.face = str(row["face"])
            official_type = row.get("official_type")
            if official_type is not None:
                up.official_type = _int_or(official_type, up.official_type)
            up.special = bool(row.get("special", up.special))
            up.last_seen_at = now
            up.missing = False
            updated += 1

    missing = 0
    for mid, up in ups_by_mid.items():
        if mid not in seen_mids:
            up.missing = True
            missing += 1

    db.commit()
    return {"total": len(rows), "new": new, "updated": updated, "missing": missing}


def run_watch_history_sync(db: Session) -> dict:
    """Frozen contract (implemented by the sync agent):

    - fetch recent history covering the configured window (default 14 days,
      capped by max pages from sync settings)
    - upsert watch_history rows (unique bvid+view_at), storing video duration
    - per up: last_watched_at = latest view_at, watched_count = distinct bvid count
      for followed mids only
    - return {"fetched": int, "new": int, "ups_touched": int}
    """
    from app.services.bilibili.cookies import load_cookies
    from app.services.bilibili.followings import fetch_history
    from app.services.settings_store import get_section_raw

    if not load_cookies(db):
        return {"skipped": "not_logged_in"}

    sync_cfg = get_section_raw(db, "sync")
    max_pages = _int_or(sync_cfg.get("history_max_pages"), _DEFAULT_HISTORY_PAGES) or _DEFAULT_HISTORY_PAGES
    window_days = (
        _int_or(sync_cfg.get("history_window_days"), _DEFAULT_HISTORY_WINDOW) or _DEFAULT_HISTORY_WINDOW
    )

    entries = _fetch_guarded(db, fetch_history, db, max_pages=max_pages, window_days=window_days)

    ups_by_mid: dict[int, UpUser] = {up.mid: up for up in db.query(UpUser).all()}

    pairs: list[tuple[str, str, dict]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        bvid = str(entry.get("bvid") or "").strip()
        view_at = _norm_timestamp(entry.get("view_at"))
        if not bvid or not view_at:
            continue
        key = (bvid, view_at)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((bvid, view_at, entry))

    existing: dict[tuple[str, str], WatchHistory] = {}
    if pairs:
        rows = db.query(WatchHistory).filter(WatchHistory.bvid.in_([p[0] for p in pairs])).all()
        for row in rows:
            existing.setdefault((row.bvid, row.view_at), row)

    new = 0
    touched: set[int] = set()
    for bvid, view_at, entry in pairs:
        up_mid = _int_or(entry.get("author_mid"), None)
        row = existing.get((bvid, view_at))
        if row is None:
            db.add(
                WatchHistory(
                    bvid=bvid,
                    up_mid=up_mid,
                    title=str(entry.get("title") or ""),
                    view_at=view_at,
                    progress=_int_or(entry.get("progress"), 0),
                    duration_seconds=_int_or(entry.get("duration"), None),
                )
            )
            new += 1
        else:
            if entry.get("title"):
                row.title = str(entry["title"])
            progress = _int_or(entry.get("progress"), None)
            if progress is not None:
                row.progress = progress
            duration = _int_or(entry.get("duration"), None)
            if duration:
                row.duration_seconds = duration
        if up_mid is not None and up_mid in ups_by_mid:
            touched.add(up_mid)

    db.flush()
    for mid in touched:
        up = ups_by_mid[mid]
        watched = db.query(WatchHistory).filter(WatchHistory.up_mid == mid).all()
        up.last_watched_at = max(r.view_at for r in watched)
        up.watched_count = len({r.bvid for r in watched})

    db.commit()
    return {"fetched": len(entries), "new": new, "ups_touched": len(touched)}


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


def _fetch_guarded(db: Session, fetch, /, *args, **kwargs):
    """Invoke a bilibili fetcher, persisting account flags on auth/risk errors.

    The flag change is committed before re-raising: the route/scheduler callers
    roll the session back when they record the failed SyncRun, which would
    otherwise discard the flag.
    """
    try:
        return fetch(*args, **kwargs)
    except AuthExpiredError:
        _flag_account(db, login_status="expired")
        raise
    except RiskControlError:
        _flag_account(db, risk_flag=True)
        raise


def _flag_account(db: Session, **fields) -> None:
    account = db.get(BilibiliAccount, 1)
    if account is None:
        return
    for name, value in fields.items():
        setattr(account, name, value)
    db.commit()


def _int_or(value, default: int | None) -> int | None:
    """Coerce to int; None/garbage falls back to default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _norm_timestamp(value) -> str | None:
    """Normalize an upstream view_at (epoch seconds or ISO 8601) to the canonical
    UTC 'YYYY-MM-DD HH:MM:SS' string used across the app, so lexicographic MAX()
    over view_at stays correct. Unparseable values are passed through unchanged
    (still deterministic, so upsert idempotency holds)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_ts(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _epoch_to_ts(int(text))
    candidate = text.replace("T", " ")
    for suffix in ("Z", "+00:00"):
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)]
    try:
        return datetime.strptime(candidate[:19], _TS_FORMAT).strftime(_TS_FORMAT)
    except ValueError:
        return text


def _epoch_to_ts(epoch: float) -> str | None:
    try:
        return datetime.fromtimestamp(epoch, tz=UTC).strftime(_TS_FORMAT)
    except (OverflowError, OSError, ValueError):
        return None
