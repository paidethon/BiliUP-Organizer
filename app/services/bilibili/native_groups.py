from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models import NativeGroupMap
from app.services.bilibili.client import API_BASE
from app.services.bilibili.cookies import load_cookies
from app.services.bilibili.qrlogin import build_client
from app.util import utcnow

if TYPE_CHECKING:
    from app.services.bilibili.client import BiliClient

# Batch cap for tags/addUsers; upstream limit is undocumented, keep <= 50
# per RESEARCH §7.2.
_ADD_USERS_BATCH = 50
_TAG_USERS_PAGE = 50
_TAG_USERS_MAX_PAGES = 40  # hard cap: 2000 members per tag is far beyond real use


def list_tags(db: Session, client: BiliClient | None = None) -> list[dict]:
    """Bilibili native follow tags for the stored account:
    [{bili_tag_id, bili_tag_name}]. Refreshes the native_group_map cache."""
    own = client is None
    c = client or build_client(db)
    try:
        data = c._request("GET", f"{API_BASE}/x/relation/tags") or []
    finally:
        if own:
            c.close()
    tags = [
        {"bili_tag_id": int(tag.get("tagid") or 0), "bili_tag_name": str(tag.get("name") or "")}
        for tag in data
        if tag.get("tagid")
    ]

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
    """Create a native tag and return its id (csrf via bili_jct)."""
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
    return int((data or {}).get("tagid") or 0)


def add_users_to_tag(db: Session, tag_id: int, mids: list[int], client: BiliClient | None = None) -> int:
    """Add users to a native tag (batched, rate-limited). Returns added count."""
    own = client is None
    c = client or build_client(db)
    csrf = load_cookies(db).get("bili_jct", "")
    added = 0
    try:
        for start in range(0, len(mids), _ADD_USERS_BATCH):
            batch = [str(int(mid)) for mid in mids[start : start + _ADD_USERS_BATCH]]
            # POST tags/addUsers: fids comma-separated, cross-origin form with
            # csrf=bili_jct (RESEARCH §7); 22105 means "not followed" upstream.
            c._request(
                "POST",
                f"{API_BASE}/x/relation/tags/addUsers",
                data={"fids": ",".join(batch), "tagids": str(int(tag_id)), "csrf": csrf},
            )
            added += len(batch)
    finally:
        if own:
            c.close()
    return added


def list_tag_users(db: Session, tag_id: int, client: BiliClient | None = None) -> list[int]:
    """All member mids of a native tag, paginated (read-only; used for backups)."""
    own = client is None
    c = client or build_client(db)
    mids: list[int] = []
    try:
        for page in range(1, _TAG_USERS_MAX_PAGES + 1):
            data = c._request(
                "GET",
                f"{API_BASE}/x/relation/tag/users",
                params={"tagid": int(tag_id), "pn": page, "ps": _TAG_USERS_PAGE},
            )
            rows = list((data or {}).get("list") or [])
            for row in rows:
                mid = int(row.get("mid") or 0)
                if mid:
                    mids.append(mid)
            if len(rows) < _TAG_USERS_PAGE:
                break
    finally:
        if own:
            c.close()
    return mids


def delete_tag(db: Session, tag_id: int, client: BiliClient | None = None) -> None:
    """Delete a native tag; its members fall back to the upstream default tag."""
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


def move_users(
    db: Session,
    fids: list[int],
    before_tag_id: int,
    after_tag_id: int,
    client: BiliClient | None = None,
) -> None:
    """Move members between two native tags (batched)."""
    own = client is None
    c = client or build_client(db)
    csrf = load_cookies(db).get("bili_jct", "")
    try:
        for start in range(0, len(fids), _ADD_USERS_BATCH):
            batch = [str(int(mid)) for mid in fids[start : start + _ADD_USERS_BATCH]]
            c._request(
                "POST",
                f"{API_BASE}/x/relation/moveUsers",
                data={
                    "fids": ",".join(batch),
                    "before_tagid": str(int(before_tag_id)),
                    "after_tagid": str(int(after_tag_id)),
                    "csrf": csrf,
                },
            )
    finally:
        if own:
            c.close()
