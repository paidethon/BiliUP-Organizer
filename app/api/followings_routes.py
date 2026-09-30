from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import false, or_

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.errors import bad_request, not_found
from app.models import AiSuggestion, GroupLocal, GroupMember, Reminder, UpUser, Video
from app.schemas import BulkIn, SuggestionOut, UpUserOut
from app.services import memberships
from app.util import utcnow

router = APIRouter(prefix="/followings", tags=["followings"])

_SORTABLE = {
    "name": UpUser.uname,
    "followed": UpUser.followed_at,
    "last_video": UpUser.last_video_at,
    "last_watched": UpUser.last_watched_at,
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
        important_ids = [row.id for row in db.query(GroupLocal.id).filter(GroupLocal.is_important.is_(True))]
        if not important_ids:
            return false()
        return UpUser.mid.in_(memberships.member_mids(db, set(important_ids)))
    raise bad_request(f"unknown flag: {flag}")


def _group_payload(db, up: UpUser) -> list[dict]:  # noqa: ANN001
    return [{"id": g.id, "name": g.name, "color": g.color} for g in memberships.groups_of(db, up.mid)]


def _group_name(db, group_id: int | None) -> str | None:  # noqa: ANN001
    if group_id is None:
        return None
    group = db.get(GroupLocal, group_id)
    return group.name if group else None


@router.get("")
def list_followings(
    admin: CurrentAdmin,
    db: DbSession,
    q: str | None = None,
    group_id: str | None = None,
    flag: str | None = None,
    sort: str = "followed",
    order: str = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
) -> dict:
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
    if sort not in _SORTABLE:
        raise bad_request(f"unsupported sort: {sort}")
    column = _SORTABLE[sort]
    column = column.desc() if order == "desc" else column.asc()
    query = query.order_by(column.nulls_last(), UpUser.mid.asc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for row in rows:
        item = UpUserOut.model_validate(row).model_dump()
        item["group_name"] = _group_name(db, row.group_id)
        item["groups"] = _group_payload(db, row)
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


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
    up_out = UpUserOut.model_validate(up).model_dump()
    up_out["group_name"] = _group_name(db, up.group_id)
    up_out["groups"] = _group_payload(db, up)
    return {
        "up": up_out,
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


_BULK_ACTIONS = {
    "set_group",
    "add_to_group",
    "remove_from_group",
    "clear_group",
    "mark_watched",
    "snooze",
    "unsnooze",
    "blacklist",
    "restore",
    "native_move",
    "unfollow",
}


@router.post("/bulk")
def bulk_action(payload: BulkIn, admin: CurrentAdmin, db: DbSession) -> dict:
    if payload.action not in _BULK_ACTIONS:
        raise bad_request(f"unknown action: {payload.action}")
    ups = db.query(UpUser).filter(UpUser.mid.in_(payload.mids)).all()
    if not ups:
        raise not_found("no matching up users")
    now = datetime.now(UTC)
    params = payload.params
    changed = 0

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
    elif payload.action in ("native_move", "unfollow"):
        changed = _external_bulk(db, payload.action, params, ups)

    db.commit()
    log_action(
        db,
        admin.username,
        f"followings.bulk_{payload.action}",
        detail={"count": changed, "mids": payload.mids[:50]},
    )
    return {"ok": True, "changed": changed}


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
