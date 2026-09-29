from __future__ import annotations

import secrets

from fastapi import APIRouter

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.errors import not_found
from app.models import FeedToken, GroupLocal
from app.schemas import FeedIn, FeedOut

router = APIRouter(prefix="/feeds", tags=["feeds"])


def _out(db, row: FeedToken) -> FeedOut:  # noqa: ANN001
    group_name = None
    if row.group_id:
        group = db.get(GroupLocal, row.group_id)
        group_name = group.name if group else None
    return FeedOut(
        id=row.id,
        name=row.name,
        token=row.token,
        group_id=row.group_id,
        group_name=group_name,
        max_items=row.max_items,
        created_at=row.created_at,
    )


@router.get("", response_model=list[FeedOut])
def list_feeds(admin: CurrentAdmin, db: DbSession) -> list[FeedOut]:
    rows = db.query(FeedToken).order_by(FeedToken.id.asc()).all()
    return [_out(db, r) for r in rows]


@router.post("", response_model=FeedOut)
def create_feed(payload: FeedIn, admin: CurrentAdmin, db: DbSession) -> FeedOut:
    if payload.group_id is not None and db.get(GroupLocal, payload.group_id) is None:
        raise not_found(f"group {payload.group_id} not found")
    row = FeedToken(
        name=payload.name,
        token=secrets.token_urlsafe(24),
        group_id=payload.group_id,
        max_items=max(1, min(payload.max_items, 200)),
    )
    db.add(row)
    db.commit()
    log_action(
        db, admin.username, "feeds.create", entity_type="feed", entity_id=row.id, detail={"name": row.name}
    )
    return _out(db, row)


@router.delete("/{feed_id}")
def delete_feed(feed_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    row = db.get(FeedToken, feed_id)
    if row is None:
        raise not_found(f"feed {feed_id} not found")
    db.delete(row)
    db.commit()
    log_action(db, admin.username, "feeds.delete", entity_type="feed", entity_id=feed_id)
    return {"ok": True}


def public_feed_response(token: str, base_url: str, db) -> "tuple[str, str]":  # noqa: ANN001, UP037
    """Return (xml, content_type); raises not_found for unknown tokens."""
    from fastapi import Response

    from app.services.feeds import render_feed_for_token

    row = db.query(FeedToken).filter(FeedToken.token == token).first()
    if row is None:
        raise not_found("unknown feed token")
    xml = render_feed_for_token(db, row, base_url)
    return Response(content=xml, media_type="application/atom+xml")
