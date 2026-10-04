"""Bilibili native follow-group (关注分组) adapter — verified contract.

Endpoints cross-checked against the community API documentation mirror
(docs/user/relation.md) and validated against the production account:

- GET  /x/relation/tags            -> data: [{tagid, name, count, tip}]
                                       (includes tagid 0 默认分组 and -10 特别关注;
                                        neither may be dropped by truthiness filters)
- GET  /x/relation/tag             -> data: [ {mid, uname, face, ...} ]  PLAIN ARRAY
                                       params: tagid, pn, ps  (0=默认, -10=特别关注, -20=所有)
- GET  /x/relation/tag/user        -> data: {"<tagid>": "<name>", ...} per-target-UP groups
                                       (default-group membership is omitted upstream)
- POST /x/relation/tag/create      -> data: {tagid}
- POST /x/relation/tag/del         (members fall back to the default tag)
- POST /x/relation/tags/addUsers   {fids, tagids, csrf} — SETS the target UPs'
                                       custom-group membership to the given tagids;
                                       removal happens by submitting 0 (default tag).
                                       Submit the FULL desired set per UP, never one
                                       tag at a time (later calls would not compose
                                       predictably).
- POST /x/relation/tags/copyUsers  {fids, tagids, csrf} — copy users into groups
- POST /x/relation/tags/moveUsers  {fids, beforeTagids, afterTagids, csrf}

Response shapes are validated defensively: a documented-array endpoint that
returns an object (or vice versa) raises UpstreamContractError instead of an
AttributeError surfacing as HTTP 500. Empty data means "empty", never "error".
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.models import NativeGroupMap
from app.services.bilibili.client import API_BASE
from app.services.bilibili.cookies import load_cookies
from app.services.bilibili.errors import UpstreamContractError
from app.services.bilibili.qrlogin import build_client
from app.util import utcnow

if TYPE_CHECKING:
    from app.services.bilibili.client import BiliClient

_ADD_USERS_BATCH = 50
_TAG_USERS_PAGE = 50
_TAG_USERS_MAX_PAGES = 40  # hard cap: 2000 members per tag is far beyond real use

# tagids that are upstream-managed states, never deletable self-built groups
DEFAULT_TAG_ID = 0
SPECIAL_TAG_ID = -10
ALL_TAG_ID = -20


def list_tags(db: Session, client: BiliClient | None = None) -> list[dict]:
    """Bilibili native follow tags for the stored account:
    [{bili_tag_id, bili_tag_name, count}]. Refreshes the native_group_map
    cache. Keeps tagid 0 (默认分组) and negative ids (特别关注) — callers
    decide what is writable; the reader must not silently drop them."""
    own = client is None
    c = client or build_client(db)
    try:
        data = c._request("GET", f"{API_BASE}/x/relation/tags")
    finally:
        if own:
            c.close()
    if data is None:
        data = []
    if not isinstance(data, list):
        raise UpstreamContractError("/x/relation/tags: expected data to be a list")
    tags: list[dict] = []
    for tag in data:
        if not isinstance(tag, dict):
            continue
        raw_id = tag.get("tagid")
        try:
            tag_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        tags.append(
            {
                "bili_tag_id": tag_id,
                "bili_tag_name": str(tag.get("name") or ""),
                "count": _as_int(tag.get("count"), 0),
            }
        )

    now = utcnow()
    existing = {row.bili_tag_id: row for row in db.query(NativeGroupMap).all()}
    for tag in tags:
        row = existing.get(tag["bili_tag_id"])
        if row is None:
            db.add(
                NativeGroupMap(
                    bili_tag_id=tag["bili_tag_id"],
                    bili_tag_name=tag["bili_tag_name"],
                    synced_at=now,
                )
            )
        else:
            row.bili_tag_name = tag["bili_tag_name"]
            row.synced_at = now
    db.commit()
    return tags


def create_tag(db: Session, name: str, client: BiliClient | None = None) -> int:
    """Create a native tag and return its id (0 means the create failed)."""
    own = client is None
    c = client or build_client(db)
    try:
        data = c._request(
            "POST",
            f"{API_BASE}/x/relation/tag/create",
            data={"tag": name, "csrf": load_cookies(db).get("bili_jct", "")},
        )
    finally:
        if own:
            c.close()
    if not isinstance(data, dict):
        return 0
    return _as_int(data.get("tagid"), 0)


def delete_tag(db: Session, tag_id: int, client: BiliClient | None = None) -> None:
    """Delete a native tag; its members fall back to the upstream default tag.
    Only self-built (positive-id) tags may be deleted through this helper."""
    if tag_id <= 0:
        raise ValueError(f"refusing to delete non-custom tag {tag_id}")
    own = client is None
    c = client or build_client(db)
    try:
        c._request(
            "POST",
            f"{API_BASE}/x/relation/tag/del",
            data={"tagid": str(int(tag_id)), "csrf": load_cookies(db).get("bili_jct", "")},
        )
    finally:
        if own:
            c.close()


def list_tag_users(db: Session, tag_id: int, client: BiliClient | None = None) -> tuple[list[int], bool]:
    """All member mids of a native tag, paginated (read-only; backups/plans).

    Correct path is GET /x/relation/tag (the previous /x/relation/tag/users
    returned HTTP 404 and blew up push-overwrite in production). Returns
    (mids, complete): complete=False when the hard page cap stopped reading
    before a short page did — callers must surface partial reads, never
    treat them as the full membership.
    """
    own = client is None
    c = client or build_client(db)
    mids: list[int] = []
    complete = False
    try:
        for page in range(1, _TAG_USERS_MAX_PAGES + 1):
            data = c._request(
                "GET",
                f"{API_BASE}/x/relation/tag",
                params={"tagid": int(tag_id), "pn": page, "ps": _TAG_USERS_PAGE},
            )
            rows = _member_rows(data)
            for row in rows:
                mid = _as_int(row.get("mid"), 0)
                if mid:
                    mids.append(mid)
            if len(rows) < _TAG_USERS_PAGE:
                complete = True
                break
        else:
            complete = False
    finally:
        if own:
            c.close()
    return mids, complete


def _member_rows(data: Any) -> list[dict]:
    """Normalize the tag-members payload: documented contract is a plain
    array; tolerate {"list": [...]} but reject anything else explicitly."""
    if data is None:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return [row for row in data["list"] if isinstance(row, dict)]
    raise UpstreamContractError("/x/relation/tag: expected data to be a member array")


def user_tag_ids(db: Session, mid: int, client: BiliClient | None = None) -> set[int]:
    """Tag ids the given followed UP currently belongs to (read-back).

    GET /x/relation/tag/user?fid=<mid> -> {"-10": "特别关注", "194111": "…"};
    the default tag (0) is omitted by upstream when the UP sits only there.
    Tolerates both str and int keys."""
    own = client is None
    c = client or build_client(db)
    try:
        data = c._request("GET", f"{API_BASE}/x/relation/tag/user", params={"fid": int(mid)})
    finally:
        if own:
            c.close()
    if data is None:
        return set()
    if not isinstance(data, dict):
        raise UpstreamContractError("/x/relation/tag/user: expected data to be an object")
    ids: set[int] = set()
    for key in data.keys():
        try:
            ids.add(int(key))
        except (TypeError, ValueError):
            continue
    return ids


def set_users_tags(db: Session, mids: list[int], tag_ids: list[int], client: BiliClient | None = None) -> int:
    """Submit the FULL desired custom-group set for each UP via addUsers.

    addUsers replaces the UPs' custom-group membership with the given tagids
    (removal = submitting 0 / default tag). One call per batch carries the
    complete target set so unmanaged groups survive when callers include
    them; per-UP batches are never merged across different target sets.
    Returns the number of UPs submitted."""
    own = client is None
    c = client or build_client(db)
    csrf = load_cookies(db).get("bili_jct", "")
    submitted = 0
    try:
        for start in range(0, len(mids), _ADD_USERS_BATCH):
            batch = mids[start : start + _ADD_USERS_BATCH]
            c._request(
                "POST",
                f"{API_BASE}/x/relation/tags/addUsers",
                data={
                    "fids": ",".join(str(int(mid)) for mid in batch),
                    "tagids": ",".join(str(int(tag)) for tag in tag_ids),
                    "csrf": csrf,
                },
            )
            submitted += len(batch)
    finally:
        if own:
            c.close()
    return submitted


def add_users_to_tag(db: Session, tag_id: int, mids: list[int], client: BiliClient | None = None) -> int:
    """Backwards-compatible wrapper: ensure these UPs are in tag_id.
    Implemented as a read-back-free addUsers with the single tag — only used
    for pure additive pushes where the UP's other groups are irrelevant
    (copyUsers semantics). Prefer set_users_tags for convergence."""
    if not mids:
        return 0
    own = client is None
    c = client or build_client(db)
    csrf = load_cookies(db).get("bili_jct", "")
    submitted = 0
    try:
        for start in range(0, len(mids), _ADD_USERS_BATCH):
            batch = mids[start : start + _ADD_USERS_BATCH]
            c._request(
                "POST",
                f"{API_BASE}/x/relation/tags/addUsers",
                data={
                    "fids": ",".join(str(int(mid)) for mid in batch),
                    "tagids": str(int(tag_id)),
                    "csrf": csrf,
                },
            )
            submitted += len(batch)
    finally:
        if own:
            c.close()
    return submitted


def move_users(
    db: Session,
    fids: list[int],
    before_tag_id: int,
    after_tag_id: int,
    client: BiliClient | None = None,
) -> None:
    """Move members between native tags via /x/relation/tags/moveUsers with
    the documented beforeTagids/afterTagids fields (the previous
    /x/relation/moveUsers + before_tagid spelling 404'd)."""
    own = client is None
    c = client or build_client(db)
    csrf = load_cookies(db).get("bili_jct", "")
    try:
        for start in range(0, len(fids), _ADD_USERS_BATCH):
            batch = fids[start : start + _ADD_USERS_BATCH]
            c._request(
                "POST",
                f"{API_BASE}/x/relation/tags/moveUsers",
                data={
                    "fids": ",".join(str(int(mid)) for mid in batch),
                    "beforeTagids": str(int(before_tag_id)),
                    "afterTagids": str(int(after_tag_id)),
                    "csrf": csrf,
                },
            )
    finally:
        if own:
            c.close()


def fetch_user_profiles(db: Session, mids: list[int], client: BiliClient | None = None) -> int:
    """Bounded userinfo lookups (GET /x/web-interface/card) for the nickname
    backfill queue; caches into up_profiles via app.services.up_profiles."""
    from app.services.up_profiles import upsert_profile

    own = client is None
    c = client or build_client(db)
    fetched = 0
    try:
        for mid in mids:
            data = c._request(
                "GET",
                f"{API_BASE}/x/web-interface/card",
                params={"mid": int(mid), "photo": "false"},
            )
            if not isinstance(data, dict):
                continue
            card = data.get("card") if isinstance(data.get("card"), dict) else data
            upsert_profile(
                db,
                int(mid),
                str(card.get("name") or "") or None,
                str(card.get("face") or "") or None,
                "userinfo",
            )
            _mark_attempt(db, int(mid))
            fetched += 1
            time.sleep(0.0)  # pacing is handled by the client's throttle
        db.commit()
    finally:
        if own:
            c.close()
    return fetched


def _mark_attempt(db: Session, mid: int) -> None:
    from app.models import UpProfile

    row = db.get(UpProfile, mid)
    if row is None:
        row = UpProfile(mid=mid)
        db.add(row)
    row.last_attempt_at = utcnow()
    row.attempts = (row.attempts or 0) + 1


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
