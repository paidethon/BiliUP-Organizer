from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.errors import bad_request, not_found
from app.models import GroupLocal, UpUser
from app.schemas import GroupIn, GroupOut, GroupPatchIn

router = APIRouter(prefix="/groups", tags=["groups"])


def _out(db, group: GroupLocal) -> GroupOut:  # noqa: ANN001
    count = db.query(UpUser).filter(UpUser.group_id == group.id).count()
    data = GroupOut.model_validate(group).model_dump()
    data["up_count"] = count
    return GroupOut(**data)


@router.get("", response_model=list[GroupOut])
def list_groups(admin: CurrentAdmin, db: DbSession) -> list[GroupOut]:
    rows = db.query(GroupLocal).order_by(GroupLocal.sort_order.asc(), GroupLocal.id.asc()).all()
    return [_out(db, g) for g in rows]


@router.post("", response_model=GroupOut)
def create_group(payload: GroupIn, admin: CurrentAdmin, db: DbSession) -> GroupOut:
    if db.query(GroupLocal).filter(GroupLocal.name == payload.name).first():
        raise bad_request(f"group name already exists: {payload.name}")
    group = GroupLocal(**payload.model_dump())
    db.add(group)
    db.commit()
    log_action(
        db,
        admin.username,
        "groups.create",
        entity_type="group",
        entity_id=group.id,
        detail={"name": group.name},
    )
    return _out(db, group)


@router.patch("/{group_id}", response_model=GroupOut)
def update_group(group_id: int, payload: GroupPatchIn, admin: CurrentAdmin, db: DbSession) -> GroupOut:
    group = db.get(GroupLocal, group_id)
    if group is None:
        raise not_found(f"group {group_id} not found")
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        existing = db.query(GroupLocal).filter(GroupLocal.name == updates["name"]).first()
        if existing and existing.id != group_id:
            raise bad_request(f"group name already exists: {updates['name']}")
    for key, value in updates.items():
        setattr(group, key, value)
    db.commit()
    log_action(db, admin.username, "groups.update", entity_type="group", entity_id=group_id, detail=updates)
    return _out(db, group)


@router.delete("/{group_id}")
def delete_group(group_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    group = db.get(GroupLocal, group_id)
    if group is None:
        raise not_found(f"group {group_id} not found")
    name = group.name
    db.query(UpUser).filter(UpUser.group_id == group_id).update({"group_id": None})
    db.delete(group)
    db.commit()
    log_action(
        db, admin.username, "groups.delete", entity_type="group", entity_id=group_id, detail={"name": name}
    )
    return {"ok": True}
