from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.errors import bad_request, not_found
from app.models import GroupAlias, GroupLocal, GroupMember, UpUser
from app.schemas import (
    AliasIn,
    GroupIn,
    GroupMergeIn,
    GroupOut,
    GroupPatchIn,
    SimilarGroupCluster,
    SimilarGroupsOut,
)
from app.services import memberships, taxonomy, undo

router = APIRouter(prefix="/groups", tags=["groups"])


def _out(db, group: GroupLocal, aliases: list[str] | None = None) -> GroupOut:  # noqa: ANN001
    count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
    data = GroupOut.model_validate(group).model_dump()
    data["up_count"] = count
    data["aliases"] = taxonomy.aliases_of(db, group.id) if aliases is None else aliases
    return GroupOut(**data)


@router.get("", response_model=list[GroupOut])
def list_groups(admin: CurrentAdmin, db: DbSession) -> list[GroupOut]:
    rows = db.query(GroupLocal).order_by(GroupLocal.sort_order.asc(), GroupLocal.id.asc()).all()
    counts = dict(
        db.query(GroupMember.group_id, func.count(GroupMember.id)).group_by(GroupMember.group_id).all()
    )
    aliases = taxonomy.aliases_of_many(db, [g.id for g in rows])
    out = []
    for g in rows:
        data = GroupOut.model_validate(g).model_dump()
        data["up_count"] = counts.get(g.id, 0)
        data["aliases"] = aliases.get(g.id, [])
        out.append(GroupOut(**data))
    return out


@router.get("/similar", response_model=SimilarGroupsOut)
def similar_groups(admin: CurrentAdmin, db: DbSession) -> SimilarGroupsOut:
    return SimilarGroupsOut(
        clusters=[
            SimilarGroupCluster(ids=[g.id for g in cluster], names=[g.name for g in cluster])
            for cluster in taxonomy.similar_group_clusters(db)
        ]
    )


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


@router.post("/{group_id}/merge")
def merge_group(group_id: int, payload: GroupMergeIn, admin: CurrentAdmin, db: DbSession) -> dict:
    group = db.get(GroupLocal, group_id)
    if group is None:
        raise not_found(f"group {group_id} not found")
    if payload.into_id == group_id:
        raise bad_request("cannot merge a group into itself")
    target = db.get(GroupLocal, payload.into_id)
    if target is None:
        raise not_found(f"group {payload.into_id} not found")
    snapshot = taxonomy.merge_groups(db, group_id, payload.into_id)
    moved = len(snapshot.get("member_mids", []))
    record = undo.record(
        db,
        admin.username,
        "group_merge",
        f"合并分组 {group.name} → {target.name}",
        {"changes": [], "snapshot": snapshot, "target_id": payload.into_id},
    )
    db.commit()
    log_action(
        db,
        admin.username,
        "groups.merge",
        entity_type="group",
        entity_id=group_id,
        detail={"into_id": payload.into_id, "moved": moved, "undo_id": record.id},
    )
    return {"ok": True, "moved": moved}


@router.post("/{group_id}/aliases")
def add_alias(group_id: int, payload: AliasIn, admin: CurrentAdmin, db: DbSession) -> dict:
    group = db.get(GroupLocal, group_id)
    if group is None:
        raise not_found(f"group {group_id} not found")
    clean = payload.alias.strip()[:64]
    if not clean:
        raise bad_request("alias is empty")
    if db.query(GroupAlias).filter(GroupAlias.alias == clean).first() is None:
        db.add(GroupAlias(group_id=group_id, alias=clean, source="manual"))
        db.commit()
        log_action(
            db,
            admin.username,
            "groups.alias_add",
            entity_type="group",
            entity_id=group_id,
            detail={"alias": clean},
        )
    return {"ok": True, "aliases": taxonomy.aliases_of(db, group_id)}


@router.delete("/{group_id}/aliases/{alias}")
def remove_alias(group_id: int, alias: str, admin: CurrentAdmin, db: DbSession) -> dict:
    group = db.get(GroupLocal, group_id)
    if group is None:
        raise not_found(f"group {group_id} not found")
    row = db.query(GroupAlias).filter(GroupAlias.group_id == group_id, GroupAlias.alias == alias).first()
    if row is None:
        raise not_found(f"alias {alias} not found on group {group_id}")
    db.delete(row)
    db.commit()
    log_action(
        db,
        admin.username,
        "groups.alias_remove",
        entity_type="group",
        entity_id=group_id,
        detail={"alias": alias},
    )
    return {"ok": True}


@router.delete("/{group_id}")
def delete_group(group_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    group = db.get(GroupLocal, group_id)
    if group is None:
        raise not_found(f"group {group_id} not found")
    name = group.name
    affected = db.query(UpUser).filter(UpUser.group_id == group_id).all()
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete()
    db.flush()
    for up in affected:
        remaining = memberships.group_ids_of(db, up.mid)
        up.group_id = remaining[0] if remaining else None
    db.delete(group)
    db.commit()
    log_action(
        db, admin.username, "groups.delete", entity_type="group", entity_id=group_id, detail={"name": name}
    )
    return {"ok": True}
