"""UP display-name resolution and profile cache.

Resolution priority for showing "who" (highest wins):
1. fresh cached profile   (up_profiles, followings/userinfo source)
2. followed UP data       (up_users.uname)
3. history author snapshot(watch_authors, name seen at sync time)

Rules enforced here:
- an empty/None upstream value NEVER overwrites a valid cached name
- numeric/mid placeholders are never cached as if they were real names
- batch resolution only — chart rendering must not trigger per-row requests
- bounded, negative-cached upstream lookups (top UPs first); lookup failures
  never take a page down, and unresolvable UPs surface as "昵称暂不可用"
  while keeping UID + space link in secondary info.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import UpProfile, UpUser, WatchAuthor
from app.util import utcnow

log = logging.getLogger(__name__)

_LOOKUP_BACKOFF_DAYS = 7
_LOOKUP_MAX_ATTEMPTS = 3


@dataclass
class ResolvedName:
    mid: int
    name: str | None
    source: str | None  # profile | followed | snapshot | None
    face: str | None = None

    @property
    def known(self) -> bool:
        return bool(self.name)


def resolve_names(db: Session, mids: list[int]) -> dict[int, ResolvedName]:
    """Batch-resolve display names for mids (pure DB, zero upstream calls)."""
    wanted = {int(m) for m in mids if m is not None}
    if not wanted:
        return {}
    result: dict[int, ResolvedName] = {mid: ResolvedName(mid, None, None, None) for mid in wanted}

    for up in db.query(UpUser).filter(UpUser.mid.in_(wanted)).all():
        if up.uname:
            result[up.mid] = ResolvedName(up.mid, up.uname, "followed", up.face or None)

    profiles = db.query(UpProfile).filter(UpProfile.mid.in_(wanted)).all()
    # profile cache wins over followed data only when fresher info exists;
    # both are trustworthy, followed data is updated every sync, so profiles
    # from history/userinfo only fill gaps or supply avatars.
    for profile in profiles:
        current = result.get(profile.mid)
        if profile.uname and (current is None or not current.name):
            result[profile.mid] = ResolvedName(profile.mid, profile.uname, "profile", profile.face or None)
        elif profile.uname and current is not None and not current.face and profile.face:
            current.face = profile.face

    # newest author snapshot per mid (max history_id), last resort
    latest = (
        db.query(WatchAuthor.author_mid, func.max(WatchAuthor.history_id))
        .filter(WatchAuthor.author_mid.in_(wanted))
        .group_by(WatchAuthor.author_mid)
        .subquery()
    )
    snapshots = (
        db.query(WatchAuthor)
        .join(
            latest,
            (WatchAuthor.author_mid == latest.c.author_mid) & (WatchAuthor.history_id == latest.c[1]),
        )
        .all()
    )
    for snap in snapshots:
        if snap.author_mid is None:
            continue
        current = result.get(snap.author_mid)
        if current is not None and not current.name and snap.author_name:
            result[snap.author_mid] = ResolvedName(
                snap.author_mid, snap.author_name, "snapshot", snap.author_face
            )
    return result


def resolve_name(db: Session, mid: int | None) -> ResolvedName | None:
    if mid is None:
        return None
    return resolve_names(db, [mid]).get(int(mid))


def upsert_profile(
    db: Session,
    mid: int,
    uname: str | None,
    face: str | None,
    source: str,
) -> None:
    """Insert/update a profile cache row; empty values never erase data and
    placeholder-ish names (mid:123, 数字占位) are rejected."""
    if mid is None:
        return
    clean_name = _clean_name(uname, mid)
    row = db.get(UpProfile, int(mid))
    if row is None:
        db.add(
            UpProfile(
                mid=int(mid),
                uname=clean_name,
                face=str(face) if face else None,
                source=source,
                updated_at=utcnow(),
            )
        )
        return
    if clean_name:
        row.uname = clean_name
        row.source = source
    if face and not row.face:
        row.face = str(face)
    row.updated_at = utcnow()


def _clean_name(uname: str | None, mid: int) -> str | None:
    if not uname:
        return None
    text = str(uname).strip()
    if not text or text.startswith("mid:") or text == str(mid):
        return None
    return text


def backfill_missing_profiles(db: Session, max_ups: int = 20) -> dict:
    """Bounded userinfo lookups for the most-watched UPs still missing names.

    Priority order = watch frequency (Top UPs first); negative cache skips
    mids attempted recently or too many times. Returns a summary dict; risk
    control or auth errors propagate to the caller (who flags the account).
    """
    from app.services.bilibili.cookies import load_cookies

    if not load_cookies(db):
        return {"skipped": "not_logged_in", "looked_up": 0}

    known_profile = {int(m) for (m,) in db.query(UpProfile.mid).filter(UpProfile.uname.isnot(None)).all()}
    known_followed = {int(m) for (m,) in db.query(UpUser.mid).filter(UpUser.uname.isnot(None)).all()}
    attempts = {int(m): (n or 0) for m, n in db.query(UpProfile.mid, UpProfile.attempts).all()}
    cutoff_days_ago = _ts_days_ago(_LOOKUP_BACKOFF_DAYS)

    candidates: list[tuple[int, int]] = (
        db.query(WatchAuthor.author_mid, func.count(WatchAuthor.history_id))
        .filter(WatchAuthor.author_mid.isnot(None))
        .group_by(WatchAuthor.author_mid)
        .order_by(func.count(WatchAuthor.history_id).desc())
        .all()
    )
    queue: list[int] = []
    for mid, _count in candidates:
        mid = int(mid)
        if mid in known_profile or mid in known_followed:
            continue
        if attempts.get(mid, 0) >= _LOOKUP_MAX_ATTEMPTS:
            continue
        row = db.get(UpProfile, mid)
        if row is not None and row.last_attempt_at and row.last_attempt_at > cutoff_days_ago:
            continue
        queue.append(mid)
        if len(queue) >= max_ups:
            break

    if not queue:
        return {"looked_up": 0, "remaining": 0}

    from app.services.bilibili.native_groups import fetch_user_profiles

    fetched = fetch_user_profiles(db, queue)
    remaining = max(len(candidates) - len(known_profile) - len(known_followed) - len(queue), 0)
    return {"looked_up": fetched, "remaining": remaining}


def _ts_days_ago(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    stamp = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def snapshot_authors(
    db: Session,
    history_id: int,
    author_mid: int | None,
    uname: str | None,
    face: str | None,
) -> None:
    """Persist the author seen at sync time for one history row + cache it."""
    from app.models import WatchAuthor as _WA

    clean = _clean_name(uname, author_mid or 0)
    if author_mid is None and not clean:
        return
    existing = db.get(_WA, history_id)
    if existing is None:
        db.add(
            _WA(
                history_id=history_id,
                author_mid=author_mid,
                author_name=clean,
                author_face=str(face) if face else None,
            )
        )
    else:
        if clean:
            existing.author_name = clean
        if face:
            existing.author_face = str(face)
    if author_mid is not None:
        upsert_profile(db, int(author_mid), clean, str(face) if face else None, "history")
