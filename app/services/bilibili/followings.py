from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.bilibili.client import API_BASE, HISTORY_PAGE_SIZE
from app.services.bilibili.errors import BiliError
from app.services.bilibili.qrlogin import build_client
from app.services.bilibili.video_zones import VIDEO_ZONES

if TYPE_CHECKING:
    from app.services.bilibili.client import BiliClient

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
_ARCHIVE_FETCH_PAGE_CAP = 10  # one request per UP with ps<=10: small, throttled

log = logging.getLogger(__name__)


def fetch_followings(db: Session, client: BiliClient | None = None) -> list[dict]:
    """Fetch every followings entry for the stored account.

    Returns a list of dicts with at least:
    mid, uname, sign, face, official_type, special(bool), followed_at (ISO).
    Wbi-signed, paginated (ps=50), rate-limited.
    """
    own = client is None
    c = client or build_client(db)
    try:
        rows = c.get_all_followings(_account_mid(db, c))
        return [_following_row(row) for row in rows]
    finally:
        if own:
            c.close()


def fetch_latest_archive(db: Session, mid: int, client: BiliClient | None = None) -> dict | None:
    """Latest upload for an UP: {bvid, title, pubdate(ISO), pic, length} or None."""
    own = client is None
    c = client or build_client(db)
    try:
        arc = c.get_latest_archive(mid)
    finally:
        if own:
            c.close()
    if not arc:
        return None
    return {
        "bvid": str(arc.get("bvid") or ""),
        "title": str(arc.get("title") or ""),
        "pubdate": _epoch_ts(arc.get("created")),
        "pic": str(arc.get("pic") or ""),
        "length": str(arc.get("length") or ""),
    }


def fetch_history(
    db: Session,
    max_pages: int = 5,
    client: BiliClient | None = None,
    window_days: int | None = None,
) -> dict:
    """Recent watch history, newest first.

    Returns {"entries": [...], "truncated": bool}. Entries carry bvid, title,
    author_mid/author_name/author_face, view_at(ISO), progress, duration.
    ``truncated`` is True when pagination stopped at max_pages while the last
    page was still full — stats callers must surface that as incomplete
    coverage instead of pretending the window is fully fetched. When
    window_days is given, pagination also stops once entries fall out of that
    window (whichever of the window edge or max_pages comes first).
    """
    own = client is None
    c = client or build_client(db)
    try:
        entries: list[dict] = []
        oldest_allowed: str | None = None
        if window_days is not None:
            edge = datetime.now(UTC) - timedelta(days=max(1, int(window_days)))
            oldest_allowed = edge.strftime(_TS_FORMAT)
        truncated = False
        for page in range(1, max(1, max_pages) + 1):
            data = c.get_history(page=page)
            rows = data["list"]
            if not rows:
                break
            stop = False
            for row in rows:
                entry = _history_row(row)
                if entry is None:
                    continue
                if oldest_allowed is not None and (entry["view_at"] or "") < oldest_allowed:
                    stop = True
                    break
                entries.append(entry)
            if stop or len(rows) < HISTORY_PAGE_SIZE:
                break  # short page means we hit the end
            if page == max(1, max_pages):
                truncated = True  # page cap reached with more data upstream
        return {"entries": entries, "truncated": truncated}
    finally:
        if own:
            c.close()


def fetch_recent_archives(
    db: Session,
    mids: list[int],
    client: BiliClient | None = None,
    per_up: int = 10,
    max_ups: int = 40,
) -> int:
    """Fetch the newest uploads for the given UPs and cache them locally.

    One shared, rate-limited client for the whole batch; one upstream request
    per UP (ps bounded to per_up). Stores top videos (bvid/title/tname/pubdate/
    duration) into the videos table and refreshes up_users.last_video_* so the
    classifier and stale-UP rules work on real data. Returns the number of UPs
    refreshed. Bounded by max_ups to respect upstream rate limits per run.
    """
    if not mids:
        return 0
    own = client is None
    c = client or build_client(db)
    refreshed = 0
    try:
        for mid in mids[:max_ups]:
            try:
                archives = c.get_user_archives(mid, page=1, page_size=min(per_up, _ARCHIVE_FETCH_PAGE_CAP))
            except BiliError as exc:
                log.warning("archives fetch failed for mid %s: %s", mid, exc)
                continue
            try:
                _store_archives(db, mid, archives["vlist"][:per_up], tlist=archives.get("tlist") or {})
            except IntegrityError as exc:
                db.rollback()
                log.warning("archives store failed for mid %s: %s", mid, exc)
                continue
            refreshed += 1
    finally:
        if own:
            c.close()
    db.commit()
    return refreshed


def _store_archives(db: Session, mid: int, vlist: list[dict], tlist: dict[str, str] | None = None) -> None:
    """Upsert archive rows into videos and refresh the UP's last-video fields.

    bvid is unique across the whole table — different UPs' upload lists can
    contain the same entry (cross-UP collabs, reposts), so dedupe by bvid
    globally, not just within this UP. The 分区名 comes from arc tname when
    present, else from the response's tlist typeid index (vlist items carry
    only typeid — storing nothing would leave videos.tname permanently NULL
    and the weekly 内容分区 chart empty).
    """
    from app.models import UpUser, Video

    bvids = [str(arc.get("bvid") or "") for arc in vlist]
    bvids = [b for b in bvids if b]
    existing = {row.bvid: row for row in db.query(Video).filter(Video.bvid.in_(bvids)).all()} if bvids else {}
    latest = vlist[0] if vlist else None
    for arc in vlist:
        bvid = str(arc.get("bvid") or "")
        if not bvid:
            continue
        title = str(arc.get("title") or "")
        tname = _archive_tname(arc, tlist)
        pubdate = _epoch_ts(arc.get("created"))
        length = str(arc.get("length") or "") or None
        row = existing.get(bvid)
        if row is None:
            db.add(
                Video(
                    bvid=bvid,
                    up_mid=mid,
                    title=title,
                    tname=tname,
                    pubdate=pubdate,
                    duration=length,
                )
            )
        else:
            if row.up_mid == mid:
                row.title = title or row.title
                row.tname = tname or row.tname
                row.pubdate = pubdate or row.pubdate
                row.duration = length or row.duration
    if latest is not None:
        up = db.query(UpUser).filter(UpUser.mid == mid).first()
        if up is not None:
            up.last_video_bvid = str(latest.get("bvid") or "") or up.last_video_bvid
            up.last_video_title = str(latest.get("title") or "") or up.last_video_title
            up.last_video_at = _epoch_ts(latest.get("created")) or up.last_video_at
    db.commit()


def fetch_user_card(db: Session, mid: int, client: BiliClient | None = None) -> dict | None:
    """Public user card: {mid, uname, sign, face, official_type} or None."""
    own = client is None
    c = client or build_client(db)
    try:
        data = c._request("GET", f"{API_BASE}/x/web-interface/card", params={"mid": mid})
    finally:
        if own:
            c.close()
    card = dict(data or {}).get("card") or {}
    if not card.get("mid"):
        return None
    official = card.get("Official") or card.get("official_verify") or {}
    return {
        "mid": int(card["mid"]),
        "uname": str(card.get("name") or ""),
        "sign": str(card.get("sign") or ""),
        "face": str(card.get("face") or ""),
        "official_type": _official_type(official),
    }


def _account_mid(db: Session, client: BiliClient) -> int:
    """The logged-in mid: DedeUserID cookie first, nav as fallback (RESEARCH §1.1)."""
    from app.services.bilibili.cookies import load_cookies

    raw = str(load_cookies(db).get("DedeUserID") or "").strip()
    if raw.isdigit():
        return int(raw)
    nav = client.get_nav()
    mid = int(nav.get("mid") or 0)
    if mid <= 0:
        raise ValueError("cannot resolve the logged-in mid (no DedeUserID cookie, nav.mid missing)")
    return mid


def _following_row(row: dict) -> dict:
    return {
        "mid": int(row.get("mid") or 0),
        "uname": str(row.get("uname") or ""),
        "sign": str(row.get("sign") or ""),
        "face": str(row.get("face") or ""),
        "official_type": _official_type(row.get("official_verify")),
        "special": bool(row.get("special")),
        "followed_at": _epoch_ts(row.get("mtime")),
    }


def _history_row(row: dict) -> dict | None:
    history = dict(row.get("history") or {})
    bvid = str(history.get("bvid") or "")
    if not bvid:
        return None  # non-archive entries (live/article/pgc) carry no bvid (RESEARCH §6.1)
    author_mid = row.get("author_mid")
    return {
        "bvid": bvid,
        "title": str(row.get("title") or ""),
        "author_mid": int(author_mid) if author_mid else None,
        # upstream author fields (RESEARCH §6.1): previously discarded, which
        # is why the leaderboard could only fall back to "mid:xxx"
        "author_name": str(row.get("author_name") or "") or None,
        "author_face": str(row.get("author_face") or "") or None,
        # view_at is a second-precision epoch upstream (RESEARCH §6.1)
        "view_at": _epoch_ts(row.get("view_at")),
        "progress": int(row.get("progress") or 0),  # -1 means watched to the end
        "duration": int(row.get("duration") or 0),  # seconds; 0 when unknown
    }


def _official_type(verify: Any) -> int:
    value = (verify or {}).get("type")
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _archive_tname(arc: dict, tlist: dict[str, str] | None) -> str | None:
    """分区名 for one archive row: direct tname field, else the tlist index
    keyed by typeid, else the bundled zone table (upstream removed tname and
    tlist from arc/search responses — see video_zones.py)."""
    name = str(arc.get("tname") or "")
    if name:
        return name
    if tlist:
        mapped = tlist.get(str(arc.get("typeid") or ""))
        if mapped:
            return mapped
    return VIDEO_ZONES.get(str(arc.get("typeid") or "")) or None


def backfill_watched_video_details(
    db: Session,
    client: BiliClient | None = None,
    *,
    window_days: int = 14,
    max_videos: int = 120,
) -> dict[str, int]:
    """Bounded metadata backfill for recently WATCHED videos missing in the
    videos table (or still without 分区名): GET /x/web-interface/view per
    bvid, no wbi, throttled like every upstream call.

    The archive scan only caches the newest ≤10 uploads of the ≤40 UPs it
    visits, so most watched videos never enter the videos table and the
    weekly 内容分区 chart aggregates nothing. Fills up to ``max_videos`` per
    run, newest watch first; per-video failures are logged and skipped.
    Returns {"filled": <videos upserted>} for the guarded caller."""
    from app.models import Video, WatchHistory

    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
    watched = (
        db.query(WatchHistory.bvid, WatchHistory.up_mid, WatchHistory.view_at)
        .filter(WatchHistory.bvid.isnot(None), WatchHistory.bvid != "", WatchHistory.view_at >= cutoff)
        .order_by(WatchHistory.view_at.desc())
        .all()
    )
    seen: dict[str, int] = {}
    for bvid, up_mid, _view_at in watched:
        seen.setdefault(str(bvid), int(up_mid or 0))
    if not seen:
        return {"filled": 0}
    have_tname = {
        row.bvid
        for row in db.query(Video.bvid, Video.tname).filter(Video.bvid.in_(list(seen))).all()
        if row.tname
    }
    todo = [bvid for bvid in seen if bvid not in have_tname][:max_videos]
    if not todo:
        return {"filled": 0}

    own = client is None
    c = client or build_client(db)
    filled = 0
    try:
        for bvid in todo:
            try:
                info = c.get_video_info(bvid)
            except BiliError as exc:
                log.warning("video info fetch failed for %s: %s", bvid, exc)
                continue
            if not isinstance(info, dict) or not info.get("bvid"):
                continue
            owner = info.get("owner") if isinstance(info.get("owner"), dict) else {}
            title = str(info.get("title") or "")
            tname = str(info.get("tname") or "") or VIDEO_ZONES.get(str(info.get("tid") or "")) or None
            pubdate = _epoch_ts(info.get("pubdate"))
            duration = _seconds_to_length(info.get("duration"))
            up_mid = _as_int(owner.get("mid")) or seen.get(bvid) or 0
            row = db.query(Video).filter(Video.bvid == bvid).first()
            if row is None:
                db.add(
                    Video(
                        bvid=bvid,
                        up_mid=up_mid,
                        title=title,
                        tname=tname,
                        pubdate=pubdate,
                        duration=duration,
                    )
                )
            else:
                row.title = title or row.title
                row.tname = tname or row.tname
                row.pubdate = pubdate or row.pubdate
                row.duration = duration or row.duration
            filled += 1
        db.commit()
    finally:
        if own:
            c.close()
    return {"filled": filled}


def _seconds_to_length(value: Any) -> str | None:
    """Epoch-style integer seconds -> arc 'length' convention (MM:SS)."""
    try:
        total = int(value)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return f"{total // 60}:{total % 60:02d}"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _epoch_ts(value: Any) -> str | None:
    """Second-precision epoch -> canonical UTC 'YYYY-MM-DD HH:MM:SS' string."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).strftime(_TS_FORMAT)
    except (OverflowError, OSError, TypeError, ValueError):
        return None
