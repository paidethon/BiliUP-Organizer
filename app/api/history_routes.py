"""Watch-history API: filters, name resolution and coverage metadata.

All timestamps leaving this router are ISO 8601 with an explicit +08:00
offset (Asia/Shanghai wall clock) — the client never guesses an offset.
Leaderboard names resolve through the shared profile pipeline
(up_profiles cache -> up_users -> history author snapshot); unresolvable UPs
render as "昵称暂不可用" with their UID kept in secondary info.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, or_

from app.api.deps import CurrentAdmin, DbSession
from app.models import GroupMember, UpUser, WatchHistory
from app.services.settings_store import get_section_raw
from app.services.up_profiles import resolve_names
from app.timeutil import SHANGHAI, shanghai_iso, utcnow_naive

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/summary")
def history_summary(
    admin: CurrentAdmin,
    db: DbSession,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    group_id: int | None = Query(default=None),
    up_mid: int | None = Query(default=None),
    limit: int = Query(default=10, le=50),
) -> dict:
    """Totals + Top UP ranking for a Shanghai range (default: last 30 days).
    Counts are saved-record counts within synced coverage; the payload states
    the coverage explicitly instead of implying lifetime completeness."""
    from app.services.stats import range_stats
    from app.timeutil import parse_date

    today = datetime.now(UTC).astimezone(SHANGHAI).date()
    if start and end:
        start_day, end_day = parse_date(start), parse_date(end)
        if start_day is None or end_day is None or end_day <= start_day:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="invalid range")
    else:
        end_day = today
        start_day = today - timedelta(days=30)

    stats = range_stats(db, start_day, end_day, extras=False, top_ups_limit=limit)
    top_watched = _resolve_top(db, db_query_top(db, start_day, end_day, group_id, up_mid, limit))

    backlog = db.query(UpUser).filter(UpUser.watched_count == 0, UpUser.missing.is_(False)).count()
    sync_cfg = get_section_raw(db, "sync")
    return {
        "total_entries": db.query(func.count()).select_from(WatchHistory).scalar() or 0,
        "entries_30d": stats["views"],
        "distinct_ups_watched": stats["distinct_ups"],
        "distinct_videos": stats["distinct_videos"],
        "watch_seconds_est": stats["watch_seconds_est"],
        "samples": stats["samples"],
        "top_watched": top_watched,
        "daily_counts": [
            {"day": d["date"], "views": d["views"], "covered": d["covered"]} for d in stats["daily"]
        ],
        "never_watched_count": backlog,
        "coverage": stats["coverage"],
        "history_max_pages": sync_cfg.get("history_max_pages"),
        "period": stats["period"],
    }


def db_query_top(
    db,  # noqa: ANN001
    start_day,  # noqa: ANN001
    end_day,  # noqa: ANN001
    group_id: int | None,
    up_mid: int | None,
    limit: int,
):
    from app.timeutil import date_range_utc

    start_utc, end_utc = date_range_utc(start_day, end_day)
    query = db.query(
        WatchHistory.up_mid.label("mid"),
        func.count().label("views"),
    ).filter(
        WatchHistory.view_at >= start_utc,
        WatchHistory.view_at < end_utc,
        WatchHistory.up_mid.isnot(None),
    )
    if up_mid is not None:
        query = query.filter(WatchHistory.up_mid == up_mid)
    if group_id is not None:
        query = query.join(GroupMember, GroupMember.up_mid == WatchHistory.up_mid).filter(
            GroupMember.group_id == group_id
        )
    return query.group_by(WatchHistory.up_mid).order_by(func.count().desc()).limit(limit).all()


def _resolve_top(db, rows) -> list[dict]:  # noqa: ANN001
    mids = [int(r.mid) for r in rows]
    names = resolve_names(db, mids)
    return [
        {
            "mid": int(r.mid),
            "uname": names.get(int(r.mid)).name if names.get(int(r.mid)) else None,
            "name_source": names.get(int(r.mid)).source if names.get(int(r.mid)) else None,
            "views": int(r.views),
        }
        for r in rows
    ]


@router.get("")
def list_history(
    admin: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
    q: str | None = Query(default=None),
    up_mid: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    hour: int | None = Query(default=None, ge=0, le=23),
) -> dict:
    """Filtered history list (server-side pagination). All filters are real
    SQL predicates — the frontend buttons map to actual query conditions."""
    from app.timeutil import date_range_utc, parse_date

    query = db.query(WatchHistory)

    if start or end:
        start_day = parse_date(start) or (datetime.now(UTC).date() - timedelta(days=30))
        end_day = parse_date(end) or datetime.now(UTC).date()
        if end_day <= start_day:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="end must be after start")
        start_utc, end_utc = date_range_utc(start_day, end_day)
        query = query.filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
    if hour is not None:
        # Shanghai wall-clock hour bucket (same bucketing as stats charts)
        sh_hour = func.substr(func.datetime(WatchHistory.view_at, "+8 hours"), 12, 2)
        query = query.filter(sh_hour == f"{hour:02d}")
    if up_mid is not None:
        query = query.filter(WatchHistory.up_mid == up_mid)
    if group_id is not None:
        query = query.join(GroupMember, GroupMember.up_mid == WatchHistory.up_mid).filter(
            GroupMember.group_id == group_id
        )
    if q:
        like = f"%{q.strip()}%"
        name_match = or_(UpUser.uname.like(like), UpUser.sign.like(like))
        mids = [int(mid) for (mid,) in db.query(UpUser.mid).filter(name_match).all()]
        conditions = [WatchHistory.title.like(like), WatchHistory.bvid.like(like)]
        if mids:
            conditions.append(WatchHistory.up_mid.in_(mids))

        query = query.filter(or_(*conditions))

    total = query.count()
    rows = query.order_by(WatchHistory.view_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    mids = {r.up_mid for r in rows if r.up_mid is not None}
    names = resolve_names(db, list(mids))
    return {
        "items": [
            {
                "bvid": r.bvid,
                "up_mid": r.up_mid,
                "up_uname": names.get(r.up_mid).name if (r.up_mid and names.get(r.up_mid)) else None,
                "title": r.title,
                "view_at": r.view_at,
                "view_at_shanghai": shanghai_iso(r.view_at),
                "progress": r.progress,
                "duration_seconds": r.duration_seconds,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "now": utcnow_naive(),
    }
