"""Taxonomy helpers shared by the API and the AI classifier.

Dimensions (all independent):
- primary category  -> groups_local (the existing table; user-editable CRUD)
- content tags      -> tags / up_tags (many per UP)
- status labels     -> up_status_labels (explicit only; derived states like
  断更/从未观看 stay computed from up_users and are never stored)

Alias + normalization machinery keeps the classifier vocabulary stable so
科技/科技区/数码科技 resolve onto an existing category instead of spawning
near-duplicates.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models import (
    GroupAlias,
    GroupLocal,
    NativeGroupMap,
    Tag,
    UpStatusLabel,
    UpTag,
)
from app.schemas import STATUS_LABELS

_STRIP_SUFFIXES = ("区", "频道", "分类")


def normalize_name(name: str) -> str:
    """Canonical form used for alias/fuzzy matching: NFKC, casefold, drop
    spaces & punctuation, strip trailing generic suffixes like 区."""
    s = unicodedata.normalize("NFKC", name or "").strip().casefold()
    s = re.sub(r"[\s·・_\-—–/]+", "", s)
    s = re.sub(r"[.,，。;；:：!！?？'\"“”‘’()（）\[\]【】<>]", "", s)
    for suffix in _STRIP_SUFFIXES:
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            s = s[: -len(suffix)]
            break
    return s


def similar_names(a: str, b: str) -> bool:
    """Loose equality for near-duplicate category names (数码科技 ≈ 科技数码)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = sorted((na, nb), key=len)
    if short in long_:
        return len(short) >= 2
    # reordered compounds (科技数码 / 数码科技) share the same character multiset
    if sorted(na) == sorted(nb):
        return True
    ratio = SequenceMatcher(None, na, nb).ratio()
    return ratio >= (0.8 if len(na) <= 4 else 0.72)


# ---- tags ----


def ensure_tag(db: Session, name: str, color: str = "#64748b") -> Tag:
    clean = (name or "").strip()[:32]
    tag = db.query(Tag).filter(Tag.name == clean).first()
    if tag is None:
        tag = Tag(name=clean, color=color)
        db.add(tag)
        db.flush()
    return tag


def set_up_tags(
    db: Session,
    mid: int,
    tag_names: list[str],
    source: str = "manual",
    replace: bool = False,
) -> int:
    """Attach tags to an UP. replace=True swaps the whole set; otherwise merge."""
    names = [t.strip() for t in tag_names if t and t.strip()]
    if replace:
        db.query(UpTag).filter(UpTag.up_mid == mid).delete()
    added = 0
    for name in names:
        tag = ensure_tag(db, name)
        exists = db.query(UpTag).filter(UpTag.up_mid == mid, UpTag.tag_id == tag.id).first()
        if exists is None:
            db.add(UpTag(up_mid=mid, tag_id=tag.id, source=source))
            added += 1
    db.flush()
    return added


def tags_of(db: Session, mid: int) -> list[Tag]:
    rows = (
        db.query(Tag).join(UpTag, UpTag.tag_id == Tag.id).filter(UpTag.up_mid == mid).order_by(Tag.name).all()
    )
    return rows


def tags_of_many(db: Session, mids: list[int]) -> dict[int, list[Tag]]:
    """Batched tag lookup (avoids N+1 in list endpoints)."""
    if not mids:
        return {}
    rows = (
        db.query(UpTag.up_mid, Tag)
        .join(Tag, Tag.id == UpTag.tag_id)
        .filter(UpTag.up_mid.in_(mids))
        .order_by(Tag.name)
        .all()
    )
    out: dict[int, list[Tag]] = {}
    for mid, tag in rows:
        out.setdefault(mid, []).append(tag)
    return out


# ---- status labels ----


def valid_status(label: str) -> bool:
    return label in STATUS_LABELS


def set_status_labels(
    db: Session,
    mid: int,
    labels: list[str],
    source: str = "manual",
    replace: bool = False,
) -> int:
    """Attach explicit status labels. Unknown labels are rejected here, not
    silently stored."""
    if replace:
        db.query(UpStatusLabel).filter(UpStatusLabel.up_mid == mid).delete()
    added = 0
    for label in labels:
        if not valid_status(label):
            raise ValueError(f"unknown status label: {label}")
        exists = (
            db.query(UpStatusLabel).filter(UpStatusLabel.up_mid == mid, UpStatusLabel.label == label).first()
        )
        if exists is None:
            db.add(UpStatusLabel(up_mid=mid, label=label, source=source))
            added += 1
    db.flush()
    return added


def clear_status_labels(db: Session, mid: int, labels: list[str] | None = None) -> int:
    q = db.query(UpStatusLabel).filter(UpStatusLabel.up_mid == mid)
    if labels:
        q = q.filter(UpStatusLabel.label.in_(labels))
    count = q.delete(synchronize_session=False)
    db.flush()
    return count


def status_labels_of(db: Session, mid: int) -> list[str]:
    rows = db.query(UpStatusLabel.label).filter(UpStatusLabel.up_mid == mid).all()
    return [r[0] for r in rows]


def status_labels_of_many(db: Session, mids: list[int]) -> dict[int, list[str]]:
    if not mids:
        return {}
    rows = db.query(UpStatusLabel.up_mid, UpStatusLabel.label).filter(UpStatusLabel.up_mid.in_(mids)).all()
    out: dict[int, list[str]] = {}
    for mid, label in rows:
        out.setdefault(mid, []).append(label)
    return out


# ---- categories (groups_local) with alias resolution ----


def _register_alias(db: Session, group_id: int, alias: str, source: str) -> None:
    clean = (alias or "").strip()[:64]
    if not clean:
        return
    exists = db.query(GroupAlias).filter(GroupAlias.alias == clean).first()
    if exists is None:
        db.add(GroupAlias(group_id=group_id, alias=clean, source=source))
        db.flush()


def resolve_group(db: Session, name: str) -> GroupLocal | None:
    """Find an existing category by exact name, alias, or fuzzy similarity.
    Auto-registers a hit alias so the next occurrence matches exactly."""
    clean = (name or "").strip()[:64]
    if not clean:
        return None
    group = db.query(GroupLocal).filter(GroupLocal.name == clean).first()
    if group is not None:
        return group
    alias = db.query(GroupAlias).filter(GroupAlias.alias == clean).first()
    if alias is not None:
        return db.get(GroupLocal, alias.group_id)
    for group in db.query(GroupLocal).all():
        if similar_names(clean, group.name):
            _register_alias(db, group.id, clean, source="auto")
            return group
    for alias in db.query(GroupAlias).all():
        if similar_names(clean, alias.alias):
            _register_alias(db, alias.group_id, clean, source="auto")
            return db.get(GroupLocal, alias.group_id)
    return None


def ensure_group(db: Session, name: str, allow_create: bool = True) -> tuple[GroupLocal | None, bool]:
    """Resolve or (optionally) create a category. Local categories are NOT
    bounded by bilibili's 20-native-tag limit — creation is policy, not cap."""
    resolved = resolve_group(db, name)
    if resolved is not None:
        return resolved, False
    if not allow_create:
        return None, False
    clean = (name or "").strip()[:64]
    if not clean:
        return None, False
    group = GroupLocal(name=clean)
    db.add(group)
    db.flush()
    return group, True


def aliases_of(db: Session, group_id: int) -> list[str]:
    rows = db.query(GroupAlias.alias).filter(GroupAlias.group_id == group_id).all()
    return [r[0] for r in rows]


def aliases_of_many(db: Session, group_ids: list[int]) -> dict[int, list[str]]:
    if not group_ids:
        return {}
    rows = db.query(GroupAlias.group_id, GroupAlias.alias).filter(GroupAlias.group_id.in_(group_ids)).all()
    out: dict[int, list[str]] = {}
    for group_id, alias in rows:
        out.setdefault(group_id, []).append(alias)
    return out


def similar_group_clusters(db: Session) -> list[list[GroupLocal]]:
    """Groups whose names are near-duplicates, for the merge tool."""
    groups = db.query(GroupLocal).order_by(GroupLocal.id).all()
    clusters: list[list[GroupLocal]] = []
    assigned: set[int] = set()
    for i, a in enumerate(groups):
        if a.id in assigned:
            continue
        cluster = [a]
        assigned.add(a.id)
        for b in groups[i + 1 :]:
            if b.id not in assigned and similar_names(a.name, b.name):
                cluster.append(b)
                assigned.add(b.id)
        if len(cluster) > 1:
            clusters.append(cluster)
    return clusters


def merge_groups(db: Session, source_id: int, target_id: int) -> dict:
    """Fold source category into target: memberships, primary pointers,
    aliases and native-tag mappings move; source row is deleted. Returns an
    undo snapshot (no remote writes — native map rows only re-point locally)."""
    from app.models import GroupMember, UpUser

    source = db.get(GroupLocal, source_id)
    target = db.get(GroupLocal, target_id)
    if source is None or target is None:
        raise ValueError("source or target group missing")
    if source.id == target.id:
        raise ValueError("cannot merge a group into itself")

    snapshot = {
        "target_id": target.id,
        "source_group": {
            "id": source.id,
            "name": source.name,
            "color": source.color,
            "sort_order": source.sort_order,
            "is_important": source.is_important,
            "description": source.description,
        },
        "aliases": [
            {"alias": a.alias, "source": a.source}
            for a in db.query(GroupAlias).filter(GroupAlias.group_id == source.id).all()
        ],
        "native_map_ids": [
            row.id
            for row in db.query(NativeGroupMap).filter(NativeGroupMap.local_group_id == source.id).all()
        ],
        "primary_mids": [row[0] for row in db.query(UpUser.mid).filter(UpUser.group_id == source.id).all()],
        "member_mids": [
            row[0] for row in db.query(GroupMember.up_mid).filter(GroupMember.group_id == source.id).all()
        ],
    }

    moved_members = 0
    for mid in snapshot["member_mids"]:
        exists = (
            db.query(GroupMember).filter(GroupMember.up_mid == mid, GroupMember.group_id == target.id).first()
        )
        if exists is None:
            db.add(GroupMember(up_mid=mid, group_id=target.id))
        moved_members += 1
    db.query(UpUser).filter(UpUser.group_id == source.id).update({"group_id": target.id})
    for alias in db.query(GroupAlias).filter(GroupAlias.group_id == source.id).all():
        alias.group_id = target.id
    _register_alias(db, target.id, source.name, source="auto")
    db.query(NativeGroupMap).filter(NativeGroupMap.local_group_id == source.id).update(
        {"local_group_id": target.id}
    )
    db.query(GroupMember).filter(GroupMember.group_id == source.id).delete(synchronize_session=False)
    db.delete(source)
    db.flush()
    return snapshot


def restore_merged_group(db: Session, snapshot: dict) -> None:
    """Undo for merge_groups: recreate the source group and its relations."""
    from app.models import GroupMember, UpUser

    src = snapshot["source_group"]
    existing = db.query(GroupLocal).filter(GroupLocal.name == src["name"]).first()
    if existing is not None:
        return  # user re-created it; do not duplicate
    group = GroupLocal(
        name=src["name"],
        color=src["color"],
        sort_order=src["sort_order"],
        is_important=src["is_important"],
        description=src["description"],
    )
    db.add(group)
    db.flush()
    for mid in snapshot["member_mids"]:
        exists = (
            db.query(GroupMember).filter(GroupMember.up_mid == mid, GroupMember.group_id == group.id).first()
        )
        if exists is None:
            db.add(GroupMember(up_mid=mid, group_id=group.id))
    # UPs whose primary was the merged-away group AND still points at the
    # target get their primary restored to the recreated group
    target_id = snapshot.get("target_id")
    for mid in snapshot["primary_mids"]:
        up = db.query(UpUser).filter(UpUser.mid == mid).first()
        if up is not None and up.group_id == target_id:
            up.group_id = group.id
    for alias in snapshot["aliases"]:
        _register_alias(db, group.id, alias["alias"], source=alias["source"])
    db.query(NativeGroupMap).filter(NativeGroupMap.id.in_(snapshot["native_map_ids"])).update(
        {"local_group_id": group.id}, synchronize_session=False
    )
    db.flush()
