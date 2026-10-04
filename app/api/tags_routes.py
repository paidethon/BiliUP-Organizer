"""Content-tag CRUD (tags / up_tags taxonomy dimension)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.errors import bad_request, not_found
from app.models import Tag, UpTag
from app.schemas import TagIn, TagOut, TagPatchIn

router = APIRouter(prefix="/tags", tags=["tags"])


def _up_counts(db) -> dict[int, int]:  # noqa: ANN001
    rows = db.query(UpTag.tag_id, func.count(UpTag.id)).group_by(UpTag.tag_id).all()
    return {tag_id: count for tag_id, count in rows}


def _out(db, tag: Tag) -> TagOut:  # noqa: ANN001
    return TagOut(id=tag.id, name=tag.name, color=tag.color, up_count=_up_counts(db).get(tag.id, 0))


@router.get("", response_model=list[TagOut])
def list_tags(admin: CurrentAdmin, db: DbSession) -> list[TagOut]:
    counts = _up_counts(db)
    rows = db.query(Tag).order_by(Tag.name.asc(), Tag.id.asc()).all()
    return [TagOut(id=t.id, name=t.name, color=t.color, up_count=counts.get(t.id, 0)) for t in rows]


@router.post("", response_model=TagOut)
def create_tag(payload: TagIn, admin: CurrentAdmin, db: DbSession) -> TagOut:
    name = payload.name.strip()
    if not name:
        raise bad_request("tag name is empty")
    if db.query(Tag).filter(Tag.name == name).first():
        raise bad_request(f"tag already exists: {name}")
    tag = Tag(name=name, color=payload.color)
    db.add(tag)
    db.commit()
    log_action(db, admin.username, "tags.create", entity_type="tag", entity_id=tag.id, detail={"name": name})
    return _out(db, tag)


@router.patch("/{tag_id}", response_model=TagOut)
def update_tag(tag_id: int, payload: TagPatchIn, admin: CurrentAdmin, db: DbSession) -> TagOut:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise not_found(f"tag {tag_id} not found")
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        name = (updates["name"] or "").strip()
        if not name:
            raise bad_request("tag name is empty")
        existing = db.query(Tag).filter(Tag.name == name).first()
        if existing and existing.id != tag_id:
            raise bad_request(f"tag already exists: {name}")
        updates["name"] = name
    for key, value in updates.items():
        setattr(tag, key, value)
    db.commit()
    log_action(db, admin.username, "tags.update", entity_type="tag", entity_id=tag_id, detail=updates)
    return _out(db, tag)


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise not_found(f"tag {tag_id} not found")
    name = tag.name
    db.query(UpTag).filter(UpTag.tag_id == tag_id).delete()
    db.delete(tag)
    db.commit()
    log_action(db, admin.username, "tags.delete", entity_type="tag", entity_id=tag_id, detail={"name": name})
    return {"ok": True}
