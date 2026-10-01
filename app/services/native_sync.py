"""Sync local groups to bilibili native follow tags.

Local categories (groups_local) and native tags are separate systems: local
groups are unlimited and are the source of truth; native tags are a projection
produced only by explicit push operations. Every push supports ``dry_run=True``
which computes the plan with remote READS only — no tag create/delete, no
member writes, no backup file.

Two strategies, chosen by the caller:

- ``push_overwrite``  — the manual「立即同步」path: snapshot the current native
  tags (backup JSON under DATA_DIR/backups/), delete every native tag, then
  recreate one tag per local group and fill it with the group's members.
- ``push_incremental`` — the scheduled path: diff local assignments against the
  last pushed state (up_users.native_tag_id + native_group_map) and only
  create missing tags, move changed members and add new ones. When the diff is
  too large (see DIFF_RATIO_OVERWRITE) it falls back to the overwrite path,
  which is cheaper and more consistent than hundreds of moves. The scheduled
  path additionally requires the ``sync.native_push_enabled`` setting (off by
  default); AI classification never touches native tags by itself.

All upstream endpoints are the same throttled, csrf-signed ones used
everywhere else (see RESEARCH §7); a single client is shared per run.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import GroupLocal, GroupMember, NativeGroupMap, UpUser
from app.services.bilibili.cookies import load_cookies
from app.services.bilibili.native_groups import (
    add_users_to_tag,
    create_tag,
    delete_tag,
    list_tag_users,
    list_tags,
    move_users,
)
from app.services.bilibili.qrlogin import build_client
from app.util import utcnow

log = logging.getLogger(__name__)

DIFF_RATIO_OVERWRITE = 0.3  # >30% of assigned UPs changed -> rebuild instead of moving
_ADD_USERS_BATCH = 50

_DRY_RUN_NOTE = "dry run：只读预览，不产生任何远端写操作或备份文件"


def _local_member_sets(db: Session) -> tuple[dict[int, set[int]], int]:
    """(group_id -> member mids, skipped non-missing UP count without any group)."""
    rows = (
        db.query(GroupMember.group_id, GroupMember.up_mid)
        .join(UpUser, UpUser.mid == GroupMember.up_mid)
        .filter(UpUser.missing.is_(False))
        .all()
    )
    by_group: dict[int, set[int]] = {}
    for group_id, mid in rows:
        by_group.setdefault(group_id, set()).add(mid)
    assigned = {mid for mids in by_group.values() for mid in mids}
    total = db.query(UpUser).filter(UpUser.missing.is_(False)).count()
    return by_group, max(total - len(assigned), 0)


def plan_overwrite(db: Session) -> dict:
    """Read-only preview of push_overwrite (remote GETs only)."""
    if not load_cookies(db):
        return {
            "mode": "overwrite",
            "dry_run": True,
            "would_create_tags": [],
            "would_delete_tags": [],
            "would_move": 0,
            "skipped": "not_logged_in",
            "conflicts": [],
            "notes": ["未登录 Bilibili，无法读取远端分组；请先在「B 站账号」登录后再预览"],
        }
    c = build_client(db)
    try:
        remote = [t for t in list_tags(db, client=c) if t["bili_tag_id"]]
        remote_names = {t["bili_tag_name"] for t in remote}
        groups = db.query(GroupLocal).order_by(GroupLocal.sort_order).all()
        local_names = {g.name for g in groups}
        by_group, skipped = _local_member_sets(db)

        conflicts: list[str] = []
        would_move = 0
        for group in groups:
            tag = next((t for t in remote if t["bili_tag_name"] == group.name), None)
            if tag is None:
                continue
            desired = by_group.get(group.id, set())
            current = set(list_tag_users(db, tag["bili_tag_id"], client=c))
            diff = len(desired ^ current)
            if diff:
                union = len(desired | current)
                if union and diff / union > 0.5:
                    conflicts.append(group.name)
                would_move += diff
        return {
            "mode": "overwrite",
            "dry_run": True,
            "would_create_tags": sorted(local_names - remote_names),
            "would_delete_tags": sorted(remote_names - local_names),
            "would_move": would_move,
            "skipped": skipped,
            "conflicts": conflicts,
            "notes": [_DRY_RUN_NOTE],
        }
    finally:
        c.close()


def plan_incremental(db: Session) -> dict:
    """Read-only preview of push_incremental (remote GETs only)."""
    if not load_cookies(db):
        return {
            "mode": "incremental",
            "dry_run": True,
            "would_create_tags": [],
            "would_delete_tags": [],
            "would_move": 0,
            "skipped": "not_logged_in",
            "conflicts": [],
            "notes": ["未登录 Bilibili，无法读取远端分组；请先在「B 站账号」登录后再预览"],
        }
    c = build_client(db)
    try:
        tags = list_tags(db, client=c)
        by_name = {t["bili_tag_name"]: t["bili_tag_id"] for t in tags if t["bili_tag_id"]}
        groups = db.query(GroupLocal).order_by(GroupLocal.sort_order).all()
        by_group, skipped = _local_member_sets(db)

        would_create = [g.name for g in groups if g.name not in by_name]
        would_move = 0
        for group in groups:
            tag_id = by_name.get(group.name)
            if not tag_id:
                continue
            desired = by_group.get(group.id, set())
            current = set(list_tag_users(db, tag_id, client=c))
            would_move += len(desired - current) + len(current - desired)
        return {
            "mode": "incremental",
            "dry_run": True,
            "would_create_tags": would_create,
            "would_delete_tags": [],
            "would_move": would_move,
            "skipped": skipped,
            "conflicts": [],
            "notes": [_DRY_RUN_NOTE],
        }
    finally:
        c.close()


def push_overwrite(db: Session, dry_run: bool = False) -> dict:
    """Backup, wipe native tags, recreate from local groups. Manual path.

    dry_run=True returns plan_overwrite() without any remote write.
    """
    if dry_run:
        return plan_overwrite(db)
    if not load_cookies(db):
        return {"skipped": "not_logged_in"}
    c = build_client(db)
    try:
        backup = backup_native_groups(db, client=c)
        deleted = 0
        for tag in list_tags(db, client=c):
            if tag["bili_tag_id"]:
                delete_tag(db, tag["bili_tag_id"], client=c)
                deleted += 1
        created, placed = _rebuild_tags_from_local(db, client=c)
    finally:
        c.close()
    return {
        "mode": "overwrite",
        "backup": backup,
        "deleted_tags": deleted,
        "created_tags": created,
        "placed": placed,
    }


def push_incremental(db: Session, dry_run: bool = False) -> dict:
    """Diff native tag members against local memberships (multi-group aware).

    Reads the actual member list of every tag mapped to a local group (GET,
    throttled), adds missing members, and moves removed members to the tag of
    their primary group (or the default tag). Falls back to a full overwrite
    when the diff exceeds DIFF_RATIO_OVERWRITE. dry_run=True returns
    plan_incremental() without any remote write.
    """
    if dry_run:
        return plan_incremental(db)
    if not load_cookies(db):
        return {"skipped": "not_logged_in"}
    c = build_client(db)
    try:
        tags = list_tags(db, client=c)
        by_name = {tag["bili_tag_name"]: tag["bili_tag_id"] for tag in tags}
        group_rows = db.query(GroupLocal).order_by(GroupLocal.sort_order).all()

        tag_of_group: dict[int, int] = {}
        missing_groups: list[GroupLocal] = []
        for group in group_rows:
            tag_id = by_name.get(group.name)
            if tag_id:
                tag_of_group[group.id] = tag_id
            else:
                missing_groups.append(group)
        for group in missing_groups:
            tag_id = create_tag(db, group.name, client=c)
            if tag_id:
                tag_of_group[group.id] = tag_id

        # desired members per tag, straight from the membership table
        membership_rows = (
            db.query(GroupMember.group_id, GroupMember.up_mid)
            .join(UpUser, UpUser.mid == GroupMember.up_mid)
            .filter(UpUser.missing.is_(False))
            .all()
        )
        wanted: dict[int, set[int]] = {}
        for group_id, mid in membership_rows:
            tag_id = tag_of_group.get(group_id)
            if tag_id:
                wanted.setdefault(tag_id, set()).add(mid)
        total_memberships = len(membership_rows)

        tag_of_primary: dict[int, int] = {}
        for up in db.query(UpUser).filter(UpUser.group_id.isnot(None)).all():
            tag_id = tag_of_group.get(up.group_id)  # type: ignore[arg-type]
            if tag_id:
                tag_of_primary[up.mid] = tag_id
                up.native_tag_id = tag_id

        changes = 0
        added = 0
        moved = 0
        for _group_id, tag_id in tag_of_group.items():
            current = set(list_tag_users(db, tag_id, client=c))
            desired = wanted.get(tag_id, set())
            to_add = sorted(desired - current)
            to_remove = sorted(current - desired)
            changes += len(to_add) + len(to_remove)
            for start in range(0, len(to_add), _ADD_USERS_BATCH):
                added += add_users_to_tag(db, tag_id, to_add[start : start + _ADD_USERS_BATCH], client=c)
            for mid in to_remove:
                after = tag_of_primary.get(mid, 0)  # 0 = upstream default tag
                if after and after != tag_id:
                    move_users(db, [mid], tag_id, after, client=c)
                    moved += 1

        if total_memberships and changes / total_memberships > DIFF_RATIO_OVERWRITE:
            backup = backup_native_groups(db, client=c)
            for tag in list_tags(db, client=c):
                if tag["bili_tag_id"]:
                    delete_tag(db, tag["bili_tag_id"], client=c)
            created, placed = _rebuild_tags_from_local(db, client=c)
            return {
                "mode": "overwrite_fallback",
                "reason": "diff_too_large",
                "diff_ratio": round(changes / total_memberships, 3),
                "backup": backup,
                "created_tags": created,
                "placed": placed,
            }

        _sync_group_map(db, tag_of_group)
        db.commit()
        return {
            "mode": "incremental",
            "diff_ratio": round(changes / total_memberships, 3) if total_memberships else 0.0,
            "created_tags": len(missing_groups),
            "moved": moved,
            "added": added,
        }
    finally:
        c.close()


def backup_native_groups(db: Session, client=None) -> dict:  # noqa: ANN001
    """Snapshot tags + members to a JSON file under DATA_DIR/backups/."""
    tags = list_tags(db, client=client)
    snapshot = {
        "backed_up_at": utcnow(),
        "tags": [{"bili_tag_id": t["bili_tag_id"], "bili_tag_name": t["bili_tag_name"]} for t in tags],
        "members": {},
    }
    for tag in tags:
        snapshot["members"][str(tag["bili_tag_id"])] = list_tag_users(db, tag["bili_tag_id"], client=client)

    backups_dir = Path(get_settings().data_dir) / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = backups_dir / f"native_groups_{stamp}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"path": str(path), "tags": len(tags)}


def _rebuild_tags_from_local(db: Session, client) -> tuple[int, int]:  # noqa: ANN001
    """Create one tag per local group and place its members; returns (tags, placed)."""
    wanted: dict[int, int] = {}
    placed = 0
    for group in db.query(GroupLocal).order_by(GroupLocal.sort_order).all():
        tag_id = create_tag(db, group.name, client=client)
        if not tag_id:
            continue
        wanted[group.id] = tag_id  # type: ignore[arg-type]
        mids = [
            up.mid
            for up in db.query(UpUser).filter(UpUser.group_id == group.id, UpUser.missing.is_(False)).all()
        ]
        placed += add_users_to_tag(db, tag_id, mids, client=client)
        for up in db.query(UpUser).filter(UpUser.group_id == group.id).all():
            up.native_tag_id = tag_id
    db.query(NativeGroupMap).delete()
    for local_id, tag_id in wanted.items():
        group = db.get(GroupLocal, local_id)
        db.add(
            NativeGroupMap(
                bili_tag_id=tag_id,
                bili_tag_name=group.name if group else f"tag-{tag_id}",
                local_group_id=local_id,
                synced_at=utcnow(),
            )
        )
    db.commit()
    return len(wanted), placed


def _sync_group_map(db: Session, wanted: dict[int, int]) -> None:
    rows = {row.bili_tag_id: row for row in db.query(NativeGroupMap).all()}
    for local_id, tag_id in wanted.items():
        row = rows.get(tag_id)
        if row is None:
            group = db.get(GroupLocal, local_id)
            db.add(
                NativeGroupMap(
                    bili_tag_id=tag_id,
                    bili_tag_name=group.name if group else f"tag-{tag_id}",
                    local_group_id=local_id,
                    synced_at=utcnow(),
                )
            )
        else:
            row.local_group_id = local_id
            row.synced_at = utcnow()
