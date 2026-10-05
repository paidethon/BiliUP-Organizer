"""Sync local groups to bilibili native follow tags — multi-group safe.

Local categories (groups_local + group_members, many-to-many) and native
tags are separate systems; native tags are a projection produced only by
explicit push operations. Every push supports ``dry_run=True`` which computes
the plan with remote READS only.

Relation algebra per UP (task §10):

  R = remote relations actually read back (per-UP tag ids)
  M = managed scope = native tag ids mapped to local groups
      (native_group_map.local_group_id IS NOT NULL)
  D = desired relations inside M = managed tags mapped from the UP's local
      groups

- ``append`` (default, non-destructive): target = R ∪ D. Adds missing managed
  relations, preserves everything else (unmanaged groups, 特别关注 -10,
  default tag). Idempotent: re-running after a full success writes nothing.
- ``replace`` (explicit, destructive within M only): target = (R − M) ∪ D.
  Removes the UP from managed tags it should not be in; unmanaged states are
  never touched. An UP whose target set is empty is moved to the default tag
  (upstream addUsers semantics: tagids=0).
- writes submit each UP's FULL target set in one addUsers call (addUsers is
  set-replacement upstream; per-tag single submissions would not compose).
  UPs sharing the exact same final target set may share a batch; different
  target sets never share one.
- every written UP is read back; one retry on mismatch, then the UP is
  reported as verify_failed. Risk control stops the run and keeps progress
  (convergence makes retries safe).
- UPs whose account upstream reports as cancelled (22013 账号已注销 — they
  stay in the following list but reject every relation mutation) are skipped
  per-UP: the plan excludes them from batches, and a batch write rejected for
  them falls back to one-by-one writes so the rest still converges. Skipped
  mids are reported in skipped_cancelled/skipped_cancelled_mids instead of
  failing the run.
- backup completes BEFORE any remote write; an incomplete backup read aborts
  destructive paths. SQLite rollback cannot undo remote writes — the backup
  file plus the restore plan are the recovery path.

The old "diff > 30% → silently rebuild everything" fallback is gone: rebuilds
are only ever the explicit, confirmed overwrite path. Full watch/following
syncs never push native groups.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import GroupLocal, GroupMember, NativeGroupMap, SyncRun, UpUser
from app.services.bilibili.cookies import load_cookies
from app.services.bilibili.errors import AccountCancelledError
from app.services.bilibili.native_groups import (
    DEFAULT_TAG_ID,
    create_tag,
    delete_tag,
    list_tag_users,
    list_tags,
    set_users_tags,
    user_tag_ids,
)
from app.services.bilibili.qrlogin import build_client
from app.util import utcnow

log = logging.getLogger(__name__)

_DRY_RUN_NOTE = "dry run：只读预览，不产生任何远端写操作或备份文件"
_WRITE_BATCH = 50


# --------------------------------------------------------------------- reads


def _managed_tag_map(db: Session) -> dict[int, int]:
    """local_group_id -> bili_tag_id for tags mapped to local groups."""
    return {
        int(row.local_group_id): int(row.bili_tag_id)
        for row in db.query(NativeGroupMap).all()
        if row.local_group_id is not None and row.bili_tag_id > 0
    }


def _desired_by_tag(db: Session, tag_of_group: dict[int, int]) -> dict[int, set[int]]:
    """bili_tag_id -> member mids, straight from the membership table."""
    rows = (
        db.query(GroupMember.group_id, GroupMember.up_mid)
        .join(UpUser, UpUser.mid == GroupMember.up_mid)
        .filter(UpUser.missing.is_(False))
        .all()
    )
    wanted: dict[int, set[int]] = {}
    for group_id, mid in rows:
        tag_id = tag_of_group.get(int(group_id))
        if tag_id:
            wanted.setdefault(tag_id, set()).add(int(mid))
    return wanted


def _read_remote_tag_members(db: Session, tag_ids: list[int], client) -> tuple[dict[int, set[int]], bool]:  # noqa: ANN001
    """Per-tag current membership; the bool is False when any tag's member
    list was truncated by the hard page cap (plans must surface that)."""
    current: dict[int, set[int]] = {}
    complete = True
    for tag_id in tag_ids:
        mids, tag_complete = list_tag_users(db, tag_id, client=client)
        current[tag_id] = set(mids)
        complete = complete and tag_complete
    return current, complete


def _compute_plan(db: Session, client, mode: str) -> dict:  # noqa: ANN001
    """Shared read-only planner for append/replace pushes."""
    list_tags(db, client=client)  # refreshes the native_group_map name cache
    managed = _managed_tag_map(db)
    groups = {int(g.id): g for g in db.query(GroupLocal).all()}
    tag_of_group = {gid: tid for gid, tid in managed.items() if gid in groups}
    unmapped_local_groups = sorted(groups[gid].name for gid in groups if gid not in tag_of_group)

    desired = _desired_by_tag(db, tag_of_group)
    current, tag_reads_complete = _read_remote_tag_members(db, sorted(tag_of_group.values()), client)

    to_add_by_tag = {tag: desired.get(tag, set()) - current.get(tag, set()) for tag in tag_of_group.values()}
    to_remove_by_tag = (
        {tag: current.get(tag, set()) - desired.get(tag, set()) for tag in tag_of_group.values()}
        if mode == "replace"
        else {tag: set() for tag in tag_of_group.values()}
    )
    affected: set[int] = set()
    for mids in list(to_add_by_tag.values()) + list(to_remove_by_tag.values()):
        affected |= mids

    # per-UP target sets; R is read only for UPs whose membership would change
    managed_scope = set(tag_of_group.values())
    targets: dict[int, set[int]] = {}
    skipped_cancelled: list[int] = []
    for mid in affected:
        try:
            remote = user_tag_ids(db, int(mid), client=client)
        except AccountCancelledError:
            skipped_cancelled.append(int(mid))  # upstream rejects any write too
            continue
        desired_tags = {tag for tag in tag_of_group.values() if mid in desired.get(tag, set())}
        if mode == "replace":
            targets[int(mid)] = (remote - managed_scope) | desired_tags
        else:
            targets[int(mid)] = remote | desired_tags
        targets[int(mid)].discard(DEFAULT_TAG_ID)  # default tag is implicit upstream

    # group UPs by identical target set so batches never mix different sets
    batches: dict[frozenset[int], list[int]] = {}
    for mid, target in targets.items():
        batches.setdefault(frozenset(target), []).append(mid)

    return {
        "mode": mode,
        "managed_tags": {
            groups[gid].name: tid for gid, tid in sorted(tag_of_group.items(), key=lambda kv: kv[1])
        },
        "unmapped_local_groups": unmapped_local_groups,
        "to_add": {str(tag): sorted(mids) for tag, mids in to_add_by_tag.items() if mids},
        "to_remove": {str(tag): sorted(mids) for tag, mids in to_remove_by_tag.items() if mids},
        "batches": [{"tagids": sorted(target), "mids": sorted(mids)} for target, mids in batches.items()],
        "planned_up_writes": len(targets),
        "skipped_cancelled": skipped_cancelled,
        "total_managed_memberships": sum(len(mids) for mids in desired.values()),
        "tag_reads_complete": tag_reads_complete,
        "unmanaged_note": (
            "未托管的原生分组与特别关注保持不变"
            if mode == "append"
            else "仅清除托管范围内多余关系；未托管分组与特别关注保持不变"
        ),
    }


def plan_push(db: Session, mode: str = "append") -> dict:
    """Read-only preview of a push (remote GETs only)."""
    if mode not in ("append", "replace"):
        raise ValueError(f"unknown push mode: {mode}")
    if not load_cookies(db):
        return {
            "mode": mode,
            "dry_run": True,
            "skipped": "not_logged_in",
            "notes": ["未登录 Bilibili，无法读取远端分组；请先在「B 站账号」登录后再预览"],
        }
    client = build_client(db)
    try:
        plan = _compute_plan(db, client, mode)
        plan["dry_run"] = True
        plan["notes"] = [_DRY_RUN_NOTE]
        return plan
    finally:
        client.close()


# -------------------------------------------------------------------- writes


def push(db: Session, mode: str = "append", dry_run: bool = False, run: SyncRun | None = None) -> dict:
    """Converge remote native groups to local memberships.

    ``append`` is the non-destructive default; ``replace`` additionally
    removes UPs from managed tags outside the desired set (backup + read-back
    still enforced). ``run`` receives incremental progress so the UI can poll
    processed counts."""
    if dry_run:
        return plan_push(db, mode)
    if mode not in ("append", "replace"):
        raise ValueError(f"unknown push mode: {mode}")
    if not load_cookies(db):
        return {"skipped": "not_logged_in"}

    client = build_client(db)
    try:
        # 1) complete backup BEFORE any write
        backup = backup_native_groups(db, client=client)
        if not backup.get("complete", False):
            return {
                "mode": mode,
                "aborted": "backup_incomplete",
                "backup": backup,
                "message": "备份读取不完整，已中止写入；请检查远端分组读取后重试",
            }

        _update_run(db, run, phase="plan")
        plan = _compute_plan(db, client, mode)

        # 2) create native tags for mapped local groups that have none yet
        created = 0
        managed = _managed_tag_map(db)
        unmapped = [g for g in db.query(GroupLocal).all() if int(g.id) not in managed]
        for group in unmapped:
            tag_id = create_tag(db, group.name, client=client)
            if tag_id:
                db.add(
                    NativeGroupMap(
                        bili_tag_id=tag_id,
                        bili_tag_name=group.name,
                        local_group_id=int(group.id),
                        synced_at=utcnow(),
                    )
                )
                created += 1
        if created:
            db.commit()
            plan = _compute_plan(db, client, mode)

        # 3) write batches (identical target sets only), then read back each UP
        written = verified = failed = 0
        skipped_cancelled = [int(mid) for mid in plan.get("skipped_cancelled", [])]
        verify_failed: list[int] = []
        batches = plan.get("batches", [])
        total_batches = len(batches)
        for index, batch in enumerate(batches):
            target_tagids = [tag for tag in batch["tagids"] if tag != DEFAULT_TAG_ID]
            if not target_tagids:
                # empty target: move to the upstream default tag (removes the
                # UP from managed custom groups under replace semantics)
                target_tagids = [DEFAULT_TAG_ID]
            for start in range(0, len(batch["mids"]), _WRITE_BATCH):
                chunk = batch["mids"][start : start + _WRITE_BATCH]
                written += _write_chunk_skipping_cancelled(
                    db, chunk, target_tagids, client, skipped_cancelled
                )
            _update_run(db, run, phase="write", batch=index + 1, total_batches=total_batches, written=written)
            # mids are unique per batch, so the cumulative set is exactly the
            # cancelled mids written for THIS batch
            cancelled_mids = set(skipped_cancelled)
            for mid in batch["mids"]:
                if int(mid) in cancelled_mids:
                    continue  # upstream rejects both the write and the read-back
                if _verify_user_tags(db, mid, target_tagids, client):
                    verified += 1
                else:
                    failed += 1
                    verify_failed.append(int(mid))

        # 4) bookkeeping: primary display tag + group-map freshness
        _update_primary_tags(db)
        by_name = {t["bili_tag_name"]: t["bili_tag_id"] for t in list_tags(db, client=client)}
        groups = {int(g.id): g for g in db.query(GroupLocal).all()}
        _sync_group_map(db, {gid: by_name[g.name] for gid, g in groups.items() if g.name in by_name})

        return {
            "mode": mode,
            "backup": backup,
            "created_tags": created,
            "written_ups": written,
            "verified_ups": verified,
            "failed_ups": failed,
            "verify_failed_mids": verify_failed,
            "skipped_cancelled": len(skipped_cancelled),
            "skipped_cancelled_mids": skipped_cancelled,
            "to_add": plan.get("to_add", {}),
            "to_remove": plan.get("to_remove", {}),
            "total_managed_memberships": plan.get("total_managed_memberships", 0),
        }
    finally:
        client.close()


def _write_chunk_skipping_cancelled(
    db: Session, chunk: list[int], target_tagids: list[int], client, cancelled_out: list[int]
) -> int:  # noqa: ANN001
    """Submit one addUsers chunk. When upstream rejects the whole batch because
    one mid's account is cancelled (22013), retry per-UP: the cancelled mids go
    to ``cancelled_out`` (never counted as written), the rest still converge.
    Non-cancelled batch errors propagate unchanged — only 22013 is skippable."""
    try:
        return set_users_tags(db, chunk, target_tagids, client=client)
    except AccountCancelledError:
        written = 0
        for mid in chunk:
            try:
                set_users_tags(db, [int(mid)], target_tagids, client=client)
                written += 1
            except AccountCancelledError:
                cancelled_out.append(int(mid))
        return written


def _verify_user_tags(db: Session, mid: int, expected_tagids: list[int], client) -> bool:  # noqa: ANN001
    """Read back the UP's relations; accept equality OR superset (upstream
    addUsers may keep unmanaged groups — preserving them is the contract).
    One retry before declaring the write failed."""
    expected = set(expected_tagids) - {DEFAULT_TAG_ID}
    remote = user_tag_ids(db, int(mid), client=client)
    if expected <= remote or (not expected and remote == set()):
        return True
    if not expected:
        set_users_tags(db, [mid], [DEFAULT_TAG_ID], client=client)
    else:
        set_users_tags(db, [mid], sorted(expected), client=client)
    remote = user_tag_ids(db, int(mid), client=client)
    return expected <= remote or (not expected and remote == set())


def _update_primary_tags(db: Session) -> None:
    """up_users.native_tag_id stays PRIMARY-group display bookkeeping only —
    never the source of truth for relations (that is group_members + the
    remote read-back)."""
    managed = _managed_tag_map(db)
    mid_by_id = {up.id: up.mid for up in db.query(UpUser.id, UpUser.mid).all()}
    id_by_mid = {mid: pk for pk, mid in mid_by_id.items()}
    rows = (
        db.query(GroupMember.up_mid, GroupMember.group_id)
        .join(UpUser, UpUser.mid == GroupMember.up_mid)
        .filter(UpUser.missing.is_(False))
        .all()
    )
    for mid, group_id in rows:
        tag_id = managed.get(int(group_id))
        pk = id_by_mid.get(int(mid))
        if pk is not None and tag_id:
            up = db.get(UpUser, pk)
            if up is not None:
                up.native_tag_id = tag_id
    db.commit()


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
    db.commit()


def _update_run(db: Session, run: SyncRun | None, **fields) -> None:
    """Best-effort progress update on the SyncRun row (UI polling); must
    never break the sync itself."""
    if run is None:
        return
    try:
        stats = json.loads(run.stats_json or "{}")
    except (TypeError, ValueError):
        stats = {}
    stats.update(fields)
    run.stats_json = json.dumps(stats, ensure_ascii=False)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        log.debug("run progress update failed", exc_info=True)
        db.rollback()


# ------------------------------------------------------------- legacy pushes


def push_overwrite(db: Session, dry_run: bool = False, run: SyncRun | None = None) -> dict:
    """Explicit destructive rebuild, managed scope ONLY.

    Backup -> delete the native tags MAPPED to local groups -> recreate them
    from the membership table (multi-group aware) -> fill members. Remote
    tags without a local mapping (and 特别关注/default) are NEVER deleted.
    The old behaviour of wiping every remote tag is gone."""
    if dry_run:
        return plan_overwrite(db)
    if not load_cookies(db):
        return {"skipped": "not_logged_in"}

    client = build_client(db)
    try:
        backup = backup_native_groups(db, client=client)
        if not backup.get("complete", False):
            return {
                "mode": "overwrite",
                "aborted": "backup_incomplete",
                "backup": backup,
                "message": "备份读取不完整，已中止写入；请检查远端分组读取后重试",
            }

        _update_run(db, run, phase="rebuild")
        managed = _managed_tag_map(db)
        groups = {int(g.id): g for g in db.query(GroupLocal).all()}
        deleted = 0
        for _local_id, tag_id in sorted(managed.items()):
            delete_tag(db, tag_id, client=client)
            deleted += 1

        created, placed = 0, 0
        new_map: dict[int, int] = {}
        for local_id in sorted(managed):
            group = groups.get(local_id)
            if group is None:
                continue
            tag_id = create_tag(db, group.name, client=client)
            if not tag_id:
                continue
            created += 1
            new_map[local_id] = tag_id
            db.add(
                NativeGroupMap(
                    bili_tag_id=tag_id,
                    bili_tag_name=group.name,
                    local_group_id=local_id,
                    synced_at=utcnow(),
                )
            )
        db.commit()

        desired = _desired_by_tag(db, new_map)
        skipped_cancelled: list[int] = []
        for tag_id, mids in desired.items():
            ordered = sorted(mids)
            for start in range(0, len(ordered), _WRITE_BATCH):
                _write_chunk_skipping_cancelled(
                    db, ordered[start : start + _WRITE_BATCH], [tag_id], client, skipped_cancelled
                )
            placed += len(ordered)
        placed -= len(skipped_cancelled)  # reported separately, never as placed

        _update_primary_tags(db)
        return {
            "mode": "overwrite",
            "scope": "managed_tags_only",
            "backup": backup,
            "deleted_tags": deleted,
            "created_tags": created,
            "placed": placed,
            "skipped_cancelled": len(skipped_cancelled),
            "skipped_cancelled_mids": skipped_cancelled,
        }
    finally:
        client.close()


def plan_overwrite(db: Session) -> dict:
    """Read-only preview of the managed-scope rebuild."""
    if not load_cookies(db):
        return {
            "mode": "overwrite",
            "dry_run": True,
            "skipped": "not_logged_in",
            "notes": ["未登录 Bilibili，无法读取远端分组；请先在「B 站账号」登录后再预览"],
        }
    client = build_client(db)
    try:
        tags = list_tags(db, client=client)
        managed = _managed_tag_map(db)
        groups = {int(g.id): g for g in db.query(GroupLocal).all()}
        desired = _desired_by_tag(db, managed)
        current, tag_reads_complete = _read_remote_tag_members(db, sorted(managed.values()), client)
        would_place = sum(
            len(desired.get(tag, set()) - current.get(tag, set()))
            + len(current.get(tag, set()) - desired.get(tag, set()))
            for tag in managed.values()
        )
        return {
            "mode": "overwrite",
            "dry_run": True,
            "scope": "managed_tags_only",
            "managed_tags": {groups[gid].name: tid for gid, tid in managed.items() if gid in groups},
            "protected_remote_tags": [
                t["bili_tag_name"]
                for t in tags
                if t["bili_tag_id"] > 0 and t["bili_tag_id"] not in managed.values()
            ],
            "would_place": would_place,
            "tag_reads_complete": tag_reads_complete,
            "notes": [_DRY_RUN_NOTE, "仅重建映射到本地分组的原生标签；未托管的远端分组不会被删除"],
        }
    finally:
        client.close()


def push_incremental(db: Session, dry_run: bool = False, run: SyncRun | None = None) -> dict:
    """Scheduled path: non-destructive append convergence, gated by
    sync.native_push_enabled (off by default). Never falls back to a full
    rebuild — that decision belongs to a human."""
    if dry_run:
        return plan_push(db, "append")
    from app.services.settings_store import get_section_raw

    if not bool(get_section_raw(db, "sync").get("native_push_enabled")):
        return {"skipped": "native_push_disabled"}
    return push(db, mode="append", run=run)


# ------------------------------------------------------------------- backup


def backup_native_groups(db: Session, client=None) -> dict:  # noqa: ANN001
    """Snapshot every remote tag + its members to JSON under DATA_DIR/backups.

    completeness=False when any tag's member read hit the hard page cap or
    failed — destructive callers must abort in that case (SQLite rollback
    cannot restore remote writes; this file is the recovery path)."""
    tags = list_tags(db, client=client)
    members: dict[str, list[int]] = {}
    complete = True
    for tag in tags:
        tag_id = tag["bili_tag_id"]
        try:
            mids, tag_complete = list_tag_users(db, tag_id, client=client)
        except Exception:  # noqa: BLE001 — a failed tag read must abort writes
            complete = False
            members[str(tag_id)] = []
            continue
        members[str(tag_id)] = mids
        if not tag_complete:
            complete = False

    snapshot = {
        "backed_up_at": utcnow(),
        "complete": complete,
        "tags": [
            {
                "bili_tag_id": t["bili_tag_id"],
                "bili_tag_name": t["bili_tag_name"],
                "count": t.get("count", 0),
            }
            for t in tags
        ],
        "members": members,
    }
    backups_dir = Path(get_settings().data_dir) / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[
        :12
    ]
    path = backups_dir / f"native_groups_{stamp}_{digest}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"path": str(path), "tags": len(tags), "complete": complete, "digest": digest}
