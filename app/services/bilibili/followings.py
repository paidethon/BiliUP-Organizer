from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.services.bilibili.client import API_BASE, HISTORY_PAGE_SIZE
from app.services.bilibili.errors import BiliError
from app.services.bilibili.qrlogin import build_client

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
) -> list[dict]:
    """Recent watch history, newest first.

    Returns dicts with: bvid, title, author_mid(int|None), view_at(ISO),
    progress, duration(seconds, 0 when unknown). When window_days is given,
    pagination stops once entries fall out of that window (whichever of the
    window edge or max_pages comes first), so day-based stats cover the whole
    period instead of just the fetched pages.
    """
    own = client is None
    c = client or build_client(db)
    try:
        entries: list[dict] = []
        oldest_allowed: str | None = None
        if window_days is not None:
            edge = datetime.now(UTC) - timedelta(days=max(1, int(window_days)))
            oldest_allowed = edge.strftime(_TS_FORMAT)
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
        return entries
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
                vlist = c.get_user_archives(mid, page=1, page_size=min(per_up, _ARCHIVE_FETCH_PAGE_CAP))[
                    "vlist"
                ]
            except BiliError as exc:
                log.warning("archives fetch failed for mid %s: %s", mid, exc)
                continue
            _store_archives(db, mid, vlist[:per_up])
            refreshed += 1
    finally:
        if own:
            c.close()
    db.commit()
    return refreshed


def _store_archives(db: Session, mid: int, vlist: list[dict]) -> None:
    """Upsert archive rows into videos and refresh the UP's last-video fields."""
    from app.models import UpUser, Video

    existing = {row.bvid: row for row in db.query(Video).filter(Video.up_mid == mid).all()}
    latest = vlist[0] if vlist else None
    for arc in vlist:
        bvid = str(arc.get("bvid") or "")
        if not bvid:
            continue
        title = str(arc.get("title") or "")
        tname = str(arc.get("tname") or "") or None
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


def _epoch_ts(value: Any) -> str | None:
    """Second-precision epoch -> canonical UTC 'YYYY-MM-DD HH:MM:SS' string."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).strftime(_TS_FORMAT)
    except (OverflowError, OSError, TypeError, ValueError):
        return None
