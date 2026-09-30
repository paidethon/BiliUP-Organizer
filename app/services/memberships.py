"""UP ↔ group membership helpers (many-to-many on top of group_members).

up_users.group_id remains the PRIMARY group; these helpers keep it consistent
with the membership set. Every "UP appears in category" semantic elsewhere
(filters, counts, stats, scoping) goes through this module.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import GroupLocal, GroupMember, UpUser


def group_ids_of(db: Session, mid: int) -> list[int]:
    rows = (
        db.query(GroupMember.group_id)
        .join(GroupLocal, GroupLocal.id == GroupMember.group_id)
        .filter(GroupMember.up_mid == mid)
        .order_by(GroupLocal.sort_order.asc(), GroupLocal.id.asc())
        .all()
    )
    return [row[0] for row in rows]


def groups_of(db: Session, mid: int) -> list[GroupLocal]:
    ids = group_ids_of(db, mid)
    if not ids:
        return []
    rows = db.query(GroupLocal).filter(GroupLocal.id.in_(ids)).all()
    order = {gid: i for i, gid in enumerate(ids)}
    return sorted(rows, key=lambda g: order.get(g.id, 999))


def member_mids(db: Session, group_ids: set[int]) -> set[int]:
    if not group_ids:
        return set()
    rows = db.query(GroupMember.up_mid).filter(GroupMember.group_id.in_(group_ids)).all()
    return {row[0] for row in rows}


def has_membership(db: Session, mid: int, group_id: int) -> bool:
    return (
        db.query(GroupMember.id).filter(GroupMember.up_mid == mid, GroupMember.group_id == group_id).first()
        is not None
    )


def add_membership(db: Session, up: UpUser, group_id: int) -> bool:
    """Add one membership; True when newly added. Keeps primary unchanged."""
    if has_membership(db, up.mid, group_id):
        return False
    db.add(GroupMember(up_mid=up.mid, group_id=group_id))
    if up.group_id is None:
        up.group_id = group_id  # first membership becomes primary
    return True


def remove_membership(db: Session, up: UpUser, group_id: int) -> bool:
    """Drop one membership; True when removed. Re-points primary when needed."""
    row = db.query(GroupMember).filter(GroupMember.up_mid == up.mid, GroupMember.group_id == group_id).first()
    if row is None:
        return False
    db.delete(row)
    if up.group_id == group_id:
        remaining = group_ids_of(db, up.mid)
        up.group_id = remaining[0] if remaining else None
    return True


def clear_memberships(db: Session, up: UpUser) -> int:
    count = db.query(GroupMember).filter(GroupMember.up_mid == up.mid).delete()
    up.group_id = None
    return count
