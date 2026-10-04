"""Revertible bulk-operation log.

A bulk action captures, per affected UP, the minimal "before" state needed to
revert exactly (membership set + primary group, tag-id set, status-label set,
or the single scalar/timestamp it overwrote). The payload only ever contains
mids, group ids, tag ids and label names — never credentials. Records live for
24h; list_active lazily flips expired ones so the undo list stays honest.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.errors import bad_request, not_found
from app.models import GroupLocal, GroupMember, Tag, UndoRecord, UpStatusLabel, UpTag, UpUser
from app.schemas import STATUS_LABELS, UndoRecordOut
from app.util import utcnow

_UNDO_WINDOW = timedelta(hours=24)

# Actions whose effect on local state can be reversed from the captured payload.
UNDOABLE_ACTIONS = {
    "set_group",
    "add_to_group",
    "remove_from_group",
    "replace_group",
    "clear_group",
    "mark_watched",
    "snooze",
    "unsnooze",
    "blacklist",
    "restore",
    "add_tags",
    "remove_tags",
    "set_status",
    "clear_status",
}

_GROUP_ACTIONS = {"set_group", "add_to_group", "remove_from_group", "replace_group", "clear_group"}
_TAG_ACTIONS = {"add_tags", "remove_tags"}
_STATUS_ACTIONS = {"set_status", "clear_status"}


def _expires_at() -> str:
    return (datetime.now(UTC) + _UNDO_WINDOW).strftime("%Y-%m-%d %H:%M:%S")


def _load_payload(raw: str | None) -> dict:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"changes": []}
    return payload if isinstance(payload, dict) else {"changes": []}


def record(db: Session, actor: str, action: str, summary: str, payload: dict) -> UndoRecord:
    """Persist an undo record in the caller's transaction (no commit here)."""
    rec = UndoRecord(
        actor=actor,
        action=action,
        summary=summary,
        payload_json=json.dumps(payload, ensure_ascii=False),
        expires_at=_expires_at(),
    )
    db.add(rec)
    db.flush()
    return rec


def capture_before(db: Session, action: str, mids: list[int]) -> list[dict]:
    """Batch-read the pre-change state of every mid for the dimensions the
    action is about to overwrite. Only relevant dimensions are captured."""
    if not mids or action not in UNDOABLE_ACTIONS:
        return []
    ups = db.query(UpUser).filter(UpUser.mid.in_(mids)).order_by(UpUser.mid.asc()).all()
    by_mid = {up.mid: up for up in ups}
    changes: list[dict] = [{"mid": up.mid} for up in ups]

    if action in _GROUP_ACTIONS:
        group_map: dict[int, list[int]] = {}
        for mid, gid in (
            db.query(GroupMember.up_mid, GroupMember.group_id).filter(GroupMember.up_mid.in_(mids)).all()
        ):
            group_map.setdefault(mid, []).append(gid)
    if action in _TAG_ACTIONS:
        tag_map: dict[int, list[int]] = {}
        for mid, tid in db.query(UpTag.up_mid, UpTag.tag_id).filter(UpTag.up_mid.in_(mids)).all():
            tag_map.setdefault(mid, []).append(tid)
    if action in _STATUS_ACTIONS:
        status_map: dict[int, list[str]] = {}
        for mid, label in (
            db.query(UpStatusLabel.up_mid, UpStatusLabel.label).filter(UpStatusLabel.up_mid.in_(mids)).all()
        ):
            status_map.setdefault(mid, []).append(label)

    for change in changes:
        up = by_mid[change["mid"]]
        mid = change["mid"]
        if action in _GROUP_ACTIONS:
            change["groups"] = sorted(group_map.get(mid, []))
            change["primary"] = up.group_id
        elif action in _TAG_ACTIONS:
            change["tags"] = sorted(tag_map.get(mid, []))
        elif action in _STATUS_ACTIONS:
            change["statuses"] = status_map.get(mid, [])
        elif action == "mark_watched":
            change["last_watched_at"] = up.last_watched_at
            change["watched_count"] = up.watched_count
        elif action in ("snooze", "unsnooze"):
            change["snoozed_until"] = up.snoozed_until
        elif action == "blacklist":
            change["blacklisted"] = up.blacklisted
        elif action == "restore":
            change["missing"] = up.missing
            change["last_seen_at"] = up.last_seen_at
    return changes


def undo(db: Session, record_id: int, actor: str) -> dict:  # noqa: ARG001
    """Revert one record. Only still-active, unexpired records are reversible."""
    rec = db.get(UndoRecord, record_id)
    if rec is None:
        raise not_found(f"undo record {record_id} not found")
    if rec.status != "active":
        raise bad_request(f"undo record {record_id} is {rec.status}, not active")
    if rec.expires_at <= utcnow():
        rec.status = "expired"
        db.commit()
        raise bad_request(f"undo record {record_id} has expired")

    payload = _load_payload(rec.payload_json)
    if rec.action != "group_merge" and rec.action not in UNDOABLE_ACTIONS:
        raise bad_request(f"unknown undo action: {rec.action}")
    restored = _revert(db, rec.action, payload)
    if restored == 0:
        raise bad_request("nothing to restore (state already matches)")
    rec.status = "undone"
    db.commit()
    return {"restored": restored}


def _revert(db: Session, action: str, payload: dict) -> int:
    if action == "group_merge":
        snapshot = payload.get("snapshot")
        if not snapshot:
            return 0
        from app.services import taxonomy

        taxonomy.restore_merged_group(db, snapshot)
        return 1

    changes = payload.get("changes", [])
    if not changes:
        return 0
    mids = [c["mid"] for c in changes if isinstance(c, dict) and c.get("mid") is not None]
    ups = {up.mid: up for up in db.query(UpUser).filter(UpUser.mid.in_(mids)).all()} if mids else {}

    valid_group_ids: set[int] = set()
    if action in _GROUP_ACTIONS:
        valid_group_ids = {row[0] for row in db.query(GroupLocal.id).all()}
    valid_tag_ids: set[int] = set()
    if action in _TAG_ACTIONS:
        valid_tag_ids = {row[0] for row in db.query(Tag.id).all()}

    restored = 0
    for change in changes:
        if not isinstance(change, dict):
            continue
        mid = change.get("mid")
        up = ups.get(mid)
        if action in _GROUP_ACTIONS:
            if up is None:
                continue
            db.query(GroupMember).filter(GroupMember.up_mid == mid).delete(synchronize_session=False)
            for gid in change.get("groups", []):
                if gid in valid_group_ids:
                    db.add(GroupMember(up_mid=mid, group_id=gid))
            primary = change.get("primary")
            up.group_id = primary if primary in valid_group_ids else None
        elif action in _TAG_ACTIONS:
            if up is None:
                continue
            db.query(UpTag).filter(UpTag.up_mid == mid).delete(synchronize_session=False)
            for tid in change.get("tags", []):
                if tid in valid_tag_ids:
                    db.add(UpTag(up_mid=mid, tag_id=tid, source="manual"))
        elif action in _STATUS_ACTIONS:
            if up is None:
                continue
            db.query(UpStatusLabel).filter(UpStatusLabel.up_mid == mid).delete(synchronize_session=False)
            for label in change.get("statuses", []):
                if label in STATUS_LABELS:
                    db.add(UpStatusLabel(up_mid=mid, label=label, source="manual"))
        elif action == "mark_watched":
            if up is None:
                continue
            up.last_watched_at = change.get("last_watched_at")
            up.watched_count = int(change.get("watched_count") or 0)
        elif action in ("snooze", "unsnooze"):
            if up is None:
                continue
            up.snoozed_until = change.get("snoozed_until")
        elif action == "blacklist":
            if up is None:
                continue
            up.blacklisted = bool(change.get("blacklisted"))
        elif action == "restore":
            if up is None:
                continue
            up.missing = bool(change.get("missing"))
            up.last_seen_at = change.get("last_seen_at")
        else:
            continue
        restored += 1
    db.flush()
    return restored


def list_active(db: Session, limit: int = 20) -> list[UndoRecord]:
    """Newest-first active records; expired ones are lazily flipped."""
    expired = (
        db.query(UndoRecord).filter(UndoRecord.status == "active", UndoRecord.expires_at <= utcnow()).all()
    )
    if expired:
        for rec in expired:
            rec.status = "expired"
        db.commit()
    return (
        db.query(UndoRecord)
        .filter(UndoRecord.status == "active")
        .order_by(UndoRecord.id.desc())
        .limit(limit)
        .all()
    )


def to_out(rec: UndoRecord) -> UndoRecordOut:
    payload = _load_payload(rec.payload_json)
    return UndoRecordOut(
        id=rec.id,
        action=rec.action,
        summary=rec.summary,
        status=rec.status,
        created_at=rec.created_at,
        expires_at=rec.expires_at,
        item_count=len(payload.get("changes", [])),
    )
