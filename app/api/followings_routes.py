from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Query as OrmQuery

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.errors import bad_request, not_found
from app.models import (
    AiSuggestion,
    GroupLocal,
    GroupMember,
    Reminder,
    Tag,
    UpStatusLabel,
    UpTag,
    UpUser,
    Video,
)
from app.schemas import (
    STATUS_LABELS,
    BulkIn,
    BulkOut,
    StatusLabelCount,
    StatusLabelsOut,
    SuggestionOut,
    UpUserOut,
)
from app.services import memberships, taxonomy, undo
from app.util import utcnow

router = APIRouter(prefix="/followings", tags=["followings"])

_SORTABLE = {
    "name": UpUser.uname,
    "followed": UpUser.followed_at,
    "last_video": UpUser.last_video_at,
    "last_watched": UpUser.last_watched_at,
}

_MAX_BULK_MIDS = 10000

_BULK_ACTIONS = {
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
    "native_move",
    "unfollow",
    "add_tags",
    "remove_tags",
    "set_status",
    "clear_status",
}


def _flag_condition(db, flag: str):  # noqa: ANN001, ANN201
    now = datetime.now(UTC)
    if flag == "stale":
        cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        return or_(UpUser.last_video_at.is_(None), UpUser.last_video_at < cutoff)
    if flag == "unwatched":
        cutoff = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        return or_(UpUser.last_watched_at.is_(None), UpUser.last_watched_at < cutoff)
    if flag == "never":
        return UpUser.watched_count == 0
    if flag == "missing":
        return UpUser.missing.is_(True)
    if flag == "important":
        return (
            db.query(GroupMember.id)
            .join(GroupLocal, GroupLocal.id == GroupMember.group_id)
            .filter(GroupMember.up_mid == UpUser.mid, GroupLocal.is_important.is_(True))
            .exists()
        )
    raise bad_request(f"unknown flag: {flag}")


def _filtered(
    db,
    q: str | None,
    group_id: str | None,
    flag: str | None,
    status: str | None,
    tag_id: str | None,
    sort: str,
    order: str,
) -> OrmQuery:
    """Shared filter/sort builder for GET /followings and bulk-by-query."""
    query = db.query(UpUser)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(UpUser.uname.like(like), UpUser.sign.like(like)))
    if group_id is not None and group_id != "":
        if group_id == "none":
            has_any = db.query(GroupMember.id).filter(GroupMember.up_mid == UpUser.mid).exists()
            query = query.filter(~has_any)
        else:
            try:
                gid = int(group_id)
            except ValueError as exc:
                raise bad_request("group_id must be an integer or 'none'") from exc
            in_group = (
                db.query(GroupMember.id)
                .filter(GroupMember.up_mid == UpUser.mid, GroupMember.group_id == gid)
                .exists()
            )
            query = query.filter(in_group)
    if flag:
        query = query.filter(_flag_condition(db, flag))
    if status:
        if status not in STATUS_LABELS:
            raise bad_request(f"unknown status label: {status}")
        has_status = (
            db.query(UpStatusLabel.id)
            .filter(UpStatusLabel.up_mid == UpUser.mid, UpStatusLabel.label == status)
            .exists()
        )
        query = query.filter(has_status)
    if tag_id is not None and tag_id != "":
        try:
            tid = int(tag_id)
        except ValueError as exc:
            raise bad_request("tag_id must be an integer") from exc
        has_tag = db.query(UpTag.id).filter(UpTag.up_mid == UpUser.mid, UpTag.tag_id == tid).exists()
        query = query.filter(has_tag)
    if sort not in _SORTABLE:
        raise bad_request(f"unsupported sort: {sort}")
    if order not in ("asc", "desc"):
        raise bad_request(f"unsupported order: {order}")
    column = _SORTABLE[sort]
    column = column.desc() if order == "desc" else column.asc()
    return query.order_by(column.nulls_last(), UpUser.mid.asc())


def _assemble_items(db, rows: list[UpUser]) -> list[dict]:  # noqa: ANN001
    """Build list items with batched lookups (groups, tags, status labels)."""
    mids = [row.mid for row in rows]
    group_rows = (
        db.query(GroupMember.up_mid, GroupLocal)
        .join(GroupLocal, GroupLocal.id == GroupMember.group_id)
        .filter(GroupMember.up_mid.in_(mids))
        .order_by(GroupLocal.sort_order.asc(), GroupLocal.id.asc())
        .all()
        if mids
        else []
    )
    groups_by_mid: dict[int, list[GroupLocal]] = {}
    for mid, group in group_rows:
        groups_by_mid.setdefault(mid, []).append(group)
    tag_map = taxonomy.tags_of_many(db, mids)
    status_map = taxonomy.status_labels_of_many(db, mids)

    name_by_id = {g.id: g.name for groups in groups_by_mid.values() for g in groups}
    missing_primary = {row.group_id for row in rows if row.group_id and row.group_id not in name_by_id}
    if missing_primary:
        for g in db.query(GroupLocal).filter(GroupLocal.id.in_(missing_primary)).all():
            name_by_id[g.id] = g.name

    items = []
    for row in rows:
        item = UpUserOut.model_validate(row).model_dump()
        item["groups"] = [
            {"id": g.id, "name": g.name, "color": g.color} for g in groups_by_mid.get(row.mid, [])
        ]
        item["group_name"] = name_by_id.get(row.group_id) if row.group_id else None
        item["tags"] = [{"id": t.id, "name": t.name, "color": t.color} for t in tag_map.get(row.mid, [])]
        item["status_labels"] = status_map.get(row.mid, [])
        items.append(item)
    return items


@router.get("")
def list_followings(
    admin: CurrentAdmin,
    db: DbSession,
    q: str | None = None,
    group_id: str | None = None,
    flag: str | None = None,
    status: str | None = None,
    tag_id: str | None = None,
    sort: str = "followed",
    order: str = "desc",
    all: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
) -> dict:
    query = _filtered(db, q, group_id, flag, status, tag_id, sort, order)
    total = query.count()
    if all:
        rows = query.all()
        page_no, size = 1, total
    else:
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
        page_no, size = page, page_size
    return {"items": _assemble_items(db, rows), "total": total, "page": page_no, "page_size": size}


@router.get("/statuses", response_model=StatusLabelsOut)
def status_label_counts(admin: CurrentAdmin, db: DbSession) -> StatusLabelsOut:
    rows = (
        db.query(UpStatusLabel.label, func.count(UpStatusLabel.id))
        .group_by(UpStatusLabel.label)
        .order_by(UpStatusLabel.label.asc())
        .all()
    )
    return StatusLabelsOut(labels=[StatusLabelCount(label=label, count=count) for label, count in rows])


@router.get("/undo")
def list_undo_records(admin: CurrentAdmin, db: DbSession) -> dict:
    return {"items": [undo.to_out(rec).model_dump() for rec in undo.list_active(db)]}


@router.post("/undo/{record_id}")
def execute_undo_record(record_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    result = undo.undo(db, record_id, admin.username)
    log_action(
        db,
        admin.username,
        "undo.execute",
        detail={"record_id": record_id, "restored": result["restored"]},
    )
    return {"ok": True, "restored": result["restored"]}


@router.post("/bulk", response_model=BulkOut)
def bulk_action(payload: BulkIn, admin: CurrentAdmin, db: DbSession) -> BulkOut:
    if payload.action not in _BULK_ACTIONS:
        raise bad_request(f"unknown action: {payload.action}")
    if payload.query is not None:
        # whole-result mode: resolve every matching mid, minus exclusions
        rows = _filtered(
            db,
            payload.query.q,
            payload.query.group_id,
            payload.query.flag,
            payload.query.status,
            payload.query.tag_id,
            payload.query.sort,
            payload.query.order,
        ).all()
        mids = [row.mid for row in rows]
        if payload.exclude_mids:
            exclude = set(payload.exclude_mids)
            mids = [mid for mid in mids if mid not in exclude]
    elif payload.mids is not None:
        if len(payload.mids) > _MAX_BULK_MIDS:
            raise bad_request(f"mids limited to {_MAX_BULK_MIDS} per batch")
        mids = list(payload.mids)
    else:
        raise bad_request("mids or query is required")

    ups = db.query(UpUser).filter(UpUser.mid.in_(mids)).all() if mids else []
    if not ups:
        # an empty selection is a no-op, not an error — report it plainly
        return BulkOut(ok=True, changed=0, undo_id=None)
    now = datetime.now(UTC)
    params = payload.params
    changed = 0

    # capture the pre-change state before any mutation touches the rows
    before_changes: list[dict] = []
    if payload.action in undo.UNDOABLE_ACTIONS:
        before_changes = undo.capture_before(db, payload.action, [up.mid for up in ups])

    def _target_group() -> GroupLocal | None:
        gid = params.get("group_id")
        return db.get(GroupLocal, int(gid)) if gid is not None else None

    if payload.action in ("set_group", "add_to_group"):
        group = _target_group()
        if group is None:
            raise bad_request("params.group_id must reference an existing group")
        for up in ups:
            if payload.action == "set_group":
                up.group_id = group.id  # primary
            if memberships.add_membership(db, up, group.id) or payload.action == "set_group":
                changed += 1
    elif payload.action == "replace_group":
        # explicit REPLACE: clear every membership, then make the target the
        # sole (primary) group. Distinct from add_to_group (append) so a bulk
        # edit can never silently wipe the UP's other groups.
        group = _target_group()
        if group is None:
            raise bad_request("params.group_id must reference an existing group")
        for up in ups:
            memberships.clear_memberships(db, up)
            up.group_id = group.id
            memberships.add_membership(db, up, group.id)
            changed += 1
    elif payload.action == "remove_from_group":
        group = _target_group()
        if group is None:
            raise bad_request("params.group_id must reference an existing group")
        for up in ups:
            if memberships.remove_membership(db, up, group.id):
                changed += 1
    elif payload.action == "clear_group":
        for up in ups:
            memberships.clear_memberships(db, up)
            changed += 1
    elif payload.action == "mark_watched":
        for up in ups:
            up.last_watched_at = utcnow()
            up.watched_count = (up.watched_count or 0) + 1
            changed += 1
    elif payload.action == "snooze":
        days = int(params.get("days", 7))
        until = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        for up in ups:
            up.snoozed_until = until
            changed += 1
    elif payload.action == "unsnooze":
        for up in ups:
            up.snoozed_until = None
            changed += 1
    elif payload.action == "blacklist":
        value = bool(params.get("value", True))
        for up in ups:
            up.blacklisted = value
            changed += 1
    elif payload.action == "restore":
        for up in ups:
            up.missing = False
            up.last_seen_at = utcnow()
            changed += 1
    elif payload.action == "add_tags":
        names = [str(t) for t in params.get("tags", []) if str(t).strip()]
        for up in ups:
            if taxonomy.set_up_tags(db, up.mid, names, source="manual") > 0:
                changed += 1
    elif payload.action == "remove_tags":
        names = [str(t) for t in params.get("tags", []) if str(t).strip()]
        tag_ids = [row[0] for row in db.query(Tag.id).filter(Tag.name.in_(names)).all()] if names else []
        for up in ups:
            deleted = 0
            if tag_ids:
                deleted = (
                    db.query(UpTag)
                    .filter(UpTag.up_mid == up.mid, UpTag.tag_id.in_(tag_ids))
                    .delete(synchronize_session=False)
                )
            if deleted:
                changed += 1
    elif payload.action == "set_status":
        labels = [str(label) for label in params.get("labels", [])]
        for label in labels:
            if label not in STATUS_LABELS:
                raise bad_request(f"unknown status label: {label}")
        for up in ups:
            if taxonomy.set_status_labels(db, up.mid, labels, source="manual") > 0:
                changed += 1
    elif payload.action == "clear_status":
        labels = [str(label) for label in params.get("labels", [])]
        for up in ups:
            if taxonomy.clear_status_labels(db, up.mid, labels or None) > 0:
                changed += 1
    elif payload.action in ("native_move", "unfollow"):
        changed = _external_bulk(db, payload.action, params, ups)

    undo_id: int | None = None
    if payload.action in undo.UNDOABLE_ACTIONS:
        record = undo.record(
            db,
            admin.username,
            payload.action,
            f"{payload.action}: {changed} UPs",
            {"changes": before_changes},
        )
        undo_id = record.id

    db.commit()
    log_action(
        db,
        admin.username,
        f"followings.bulk_{payload.action}",
        detail={"count": changed, "mids": mids[:50], "undo_id": undo_id},
    )
    return BulkOut(ok=True, changed=changed, undo_id=undo_id)


def _external_bulk(db, action: str, params: dict, ups: list[UpUser]) -> int:  # noqa: ANN001
    """Actions that touch Bilibili upstream; demo mode short-circuits locally."""
    mids = [up.mid for up in ups]
    if get_settings().demo_mode:
        if action == "unfollow":
            if not params.get("confirm"):
                raise bad_request("unfollow requires params.confirm = true")
            for up in ups:
                up.missing = True
        return len(ups)
    from app.services.bilibili.native_groups import add_users_to_tag
    from app.services.bilibili.unfollow import unfollow_users

    if action == "native_move":
        tag_id = int(params.get("tag_id", 0))
        if not tag_id:
            raise bad_request("params.tag_id is required")
        return add_users_to_tag(db, tag_id, mids)
    if action == "unfollow":
        if not params.get("confirm"):
            raise bad_request("unfollow requires params.confirm = true")
        unfollow_users(db, mids)
        for up in ups:
            up.missing = True
        return len(ups)
    raise bad_request(f"unknown external action: {action}")


@router.get("/{mid}")
def following_detail(mid: int, admin: CurrentAdmin, db: DbSession) -> dict:
    up = db.query(UpUser).filter(UpUser.mid == mid).first()
    if up is None:
        raise not_found(f"up {mid} not found")
    videos = db.query(Video).filter(Video.up_mid == mid).order_by(Video.pubdate.desc()).limit(10).all()
    suggestions = (
        db.query(AiSuggestion)
        .filter(AiSuggestion.up_mid == mid)
        .order_by(AiSuggestion.id.desc())
        .limit(5)
        .all()
    )
    reminders = db.query(Reminder).filter(Reminder.entity_id == str(mid), Reminder.status == "open").all()
    return {
        "up": _assemble_items(db, [up])[0],
        "videos": [
            {"bvid": v.bvid, "title": v.title, "pubdate": v.pubdate, "cover": v.cover, "duration": v.duration}
            for v in videos
        ],
        "suggestions": [
            SuggestionOut.model_validate(s).model_dump(exclude={"up_uname"}) for s in suggestions
        ],
        "reminders": [
            {"id": r.id, "rule_key": r.rule_key, "title": r.title, "body": r.body, "severity": r.severity}
            for r in reminders
        ],
    }
