from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.api.deps import CurrentAdmin, DbSession
from app.models import UpUser, WatchHistory

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/summary")
def history_summary(admin: CurrentAdmin, db: DbSession) -> dict:
    now = datetime.now(UTC)
    cutoff30 = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    total = db.query(func.count()).select_from(WatchHistory).scalar() or 0
    entries_30d = (
        db.query(func.count()).select_from(WatchHistory).filter(WatchHistory.view_at >= cutoff30).scalar()
        or 0
    )
    distinct = db.query(func.count(func.distinct(WatchHistory.up_mid))).scalar() or 0

    top_rows = (
        db.query(WatchHistory.up_mid, func.count().label("views"))
        .filter(WatchHistory.up_mid.isnot(None))
        .group_by(WatchHistory.up_mid)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    names = {u.mid: u.uname for u in db.query(UpUser).filter(UpUser.mid.in_([r[0] for r in top_rows]))}
    top_watched = [
        {"mid": mid, "uname": names.get(mid, f"mid:{mid}"), "views": views} for mid, views in top_rows
    ]

    daily_rows = (
        db.query(func.substr(WatchHistory.view_at, 1, 10).label("day"), func.count().label("views"))
        .filter(WatchHistory.view_at >= cutoff30)
        .group_by("day")
        .order_by("day")
        .all()
    )
    counts_by_day = {day: views for day, views in daily_rows}
    daily_counts = []
    for offset in range(29, -1, -1):
        day = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        daily_counts.append({"day": day, "views": counts_by_day.get(day, 0)})

    backlog = db.query(UpUser).filter(UpUser.watched_count == 0, UpUser.missing.is_(False)).count()
    return {
        "total_entries": total,
        "entries_30d": entries_30d,
        "distinct_ups_watched": distinct,
        "top_watched": top_watched,
        "daily_counts": daily_counts,
        "never_watched_count": backlog,
    }


@router.get("")
def list_history(
    admin: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
) -> dict:
    query = db.query(WatchHistory).order_by(WatchHistory.view_at.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    up_names = {u.mid: u.uname for u in db.query(UpUser)}
    return {
        "items": [
            {
                "bvid": r.bvid,
                "up_mid": r.up_mid,
                "up_uname": up_names.get(r.up_mid) if r.up_mid else None,
                "title": r.title,
                "view_at": r.view_at,
                "progress": r.progress,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
