"""Sync local groups to bilibili native follow tags.

Two strategies, chosen by the caller:

- ``push_overwrite``  — the manual「立即同步」path: snapshot the current native
  tags (backup JSON under DATA_DIR/backups/), delete every native tag, then
  recreate one tag per local group and fill it with the group's members.
- ``push_incremental`` — the scheduled path: diff local assignments against the
  last pushed state (up_users.native_tag_id + native_group_map) and only
  create missing tags, move changed members and add new ones. When the diff is
  too large (see DIFF_RATIO_OVERWRITE) it falls back to the overwrite path,
  which is cheaper and more consistent than hundreds of moves.

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
from app.models import GroupLocal, NativeGroupMap, UpUser
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


def push_overwrite(db: Session) -> dict:
    """Backup, wipe native tags, recreate from local groups. Manual path."""
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


def push_incremental(db: Session) -> dict:
    """Diff-based native sync; falls back to overwrite on a large diff."""
    if not load_cookies(db):
        return {"skipped": "not_logged_in"}
    c = build_client(db)
    try:
        tags = list_tags(db, client=c)
        by_name = {tag["bili_tag_name"]: tag["bili_tag_id"] for tag in tags}
        group_rows = db.query(GroupLocal).order_by(GroupLocal.sort_order).all()

        wanted: dict[int, int] = {}  # local_group_id -> bili_tag_id
        missing_groups: list[GroupLocal] = []
        for group in group_rows:
            tag_id = by_name.get(group.name)
            if tag_id:
                wanted[group.id] = tag_id
            else:
                missing_groups.append(group)

        for group in missing_groups:
            tag_id = create_tag(db, group.name, client=c)
            if tag_id:
                wanted[group.id] = tag_id

        assigned = db.query(UpUser).filter(UpUser.group_id.isnot(None), UpUser.missing.is_(False)).all()
        changes: list[tuple[UpUser, int]] = []
        for up in assigned:
            tag_id = wanted.get(up.group_id)  # type: ignore[arg-type]
            if tag_id is not None and up.native_tag_id != tag_id:
                changes.append((up, tag_id))

        moved = 0
        if assigned and len(changes) / len(assigned) > DIFF_RATIO_OVERWRITE:
            backup = backup_native_groups(db, client=c)
            for tag in list_tags(db, client=c):
                if tag["bili_tag_id"]:
                    delete_tag(db, tag["bili_tag_id"], client=c)
            created, placed = _rebuild_tags_from_local(db, client=c)
            return {
                "mode": "overwrite_fallback",
                "reason": "diff_too_large",
                "diff_ratio": round(len(changes) / len(assigned), 3),
                "backup": backup,
                "created_tags": created,
                "placed": placed,
            }

        # move known-tag members, add unknown ones; bookkeeping afterwards
        pairs: dict[tuple[int, int], list[int]] = {}
        fresh: dict[int, list[int]] = {}
        for up, tag_id in changes:
            if up.native_tag_id:
                pairs.setdefault((up.native_tag_id, tag_id), []).append(up.mid)
            else:
                fresh.setdefault(tag_id, []).append(up.mid)
            up.native_tag_id = tag_id
        moved = 0
        for (before_tag, after_tag), mids in pairs.items():
            for start in range(0, len(mids), _ADD_USERS_BATCH):
                batch = mids[start : start + _ADD_USERS_BATCH]
                move_users(db, batch, before_tag, after_tag, client=c)
                moved += len(batch)
        added = 0
        for tag_id, mids in fresh.items():
            added += add_users_to_tag(db, tag_id, mids, client=c)

        _sync_group_map(db, wanted)
        db.commit()
        return {
            "mode": "incremental",
            "diff_ratio": round(len(changes) / len(assigned), 3) if assigned else 0.0,
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
