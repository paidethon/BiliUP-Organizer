"""Shared watch-statistics service — the single source of statistical truth.

Every surface (history page, weekly page, archive snapshots, exports, AI
digests) renders from ``range_stats``; nothing re-implements date handling or
group attribution.

Metric definitions (metrics_version is embedded in every payload and frozen
into weekly report archives):

- 观看记录数 (views): saved, deduplicated watch records in range — NOT exact
  play counts (rewatches in one record, seeks and speeds are unknowable).
- 去重视频数 / 去重 UP 数: distinct bvid / distinct up_mid in range.
- 观看时长 (watch_seconds_est): estimated from the record's progress, never
  the full video length. Categories:
    * point sample  — progress >= 0 and duration > 0: min(progress, duration)
    * finished      — progress == -1 and duration > 0: duration
    * bound sample  — progress > 0 and no usable duration: progress (lower
      bound; counted in the estimate, excluded from averages)
    * unknown       — everything else (incl. duration-only rows): contributes
      nothing and is reported separately. Never faked as 0 / finished / mean.
- Averages divide by valid samples only.
- "该范围内未发现观看记录" is scoped to synced coverage; it is never a claim
  about the user's lifetime watching.
- Day/hour/weekday buckets use the Asia/Shanghai wall clock via SQL
  datetime(view_at, '+8 hours'); ranges are half-open [start 00:00, end 00:00)
  in Shanghai, converted to naive-UTC bounds for querying.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, case, func, not_, or_
from sqlalchemy.orm import Session

from app.models import GroupLocal, GroupMember, UpUser, Video, WatchHistory
from app.services.up_profiles import resolve_names
from app.timeutil import (
    METRICS_VERSION,
    TZ_NAME,
    date_range_utc,
    format_date,
    parse_utc,
    shanghai_date,
    utcnow_naive,
)
from app.timeutil import (
    SHANGHAI as _SHANGHAI_TZ,
)

# --- estimation SQL ---------------------------------------------------------

_DURATION_OK = WatchHistory.duration_seconds > 0
# NULL-safe "no usable duration": SQL `NOT (NULL > 0)` is NULL (three-valued
# logic), so the negation must test the column directly instead.
_NO_DURATION = or_(WatchHistory.duration_seconds.is_(None), not_(_DURATION_OK))
_PROGRESS = WatchHistory.progress

# min(progress, duration) as a SQL scalar expression (SQLite scalar min with
# two args); NULL-safe because the branch conditions already guarantee values.
_WATCH_SECONDS = case(
    (and_(_PROGRESS == -1, _DURATION_OK), WatchHistory.duration_seconds),
    (and_(_PROGRESS >= 0, _DURATION_OK), func.min(_PROGRESS, WatchHistory.duration_seconds)),
    (and_(_PROGRESS > 0, _NO_DURATION), _PROGRESS),
    else_=None,
)

# completion ratio: 0..1 bounded; NULL when unknowable
_CLIPPED_PROGRESS = func.min(_PROGRESS, WatchHistory.duration_seconds)
_COMPLETION_RATIO = case(
    (and_(_PROGRESS == -1, _DURATION_OK), 1.0),
    (
        and_(_PROGRESS >= 0, _DURATION_OK),
        _CLIPPED_PROGRESS * 1.0 / WatchHistory.duration_seconds,
    ),
    else_=None,
)

_DURATION_BUCKET = case(
    (WatchHistory.duration_seconds <= 300, "≤5分钟"),
    (WatchHistory.duration_seconds <= 900, "5-15分钟"),
    (WatchHistory.duration_seconds <= 1800, "15-30分钟"),
    (WatchHistory.duration_seconds <= 3600, "30-60分钟"),
    else_="60分钟以上",
)

_COMPLETION_BUCKET = case(
    (_COMPLETION_RATIO < 0.25, "0-25%"),
    (_COMPLETION_RATIO < 0.5, "25-50%"),
    (_COMPLETION_RATIO < 0.75, "50-75%"),
    (_COMPLETION_RATIO < 1.0, "75-99%"),
    else_="看完",
)

# Shanghai wall-clock buckets inside SQL (view_at is naive UTC)
_SH_DT = func.datetime(WatchHistory.view_at, "+8 hours")
_SH_DAY = func.substr(_SH_DT, 1, 10)
_SH_HOUR = func.substr(_SH_DT, 12, 2)
_SH_WEEKDAY = func.strftime("%w", _SH_DT)  # 0=Sunday..6=Saturday

_WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_WEEKDAY_SQL_ORDER = ["1", "2", "3", "4", "5", "6", "0"]  # Monday..Sunday


def range_stats(
    db: Session,
    start: date,
    end: date,
    *,
    include_prev: bool = False,
    extras: bool = True,
    top_ups_limit: int = 8,
    now: datetime | None = None,
) -> dict:
    """Aggregate all watch statistics for the Shanghai half-open range
    [start 00:00, end 00:00). ``extras=False`` keeps only the core numbers
    for light surfaces (history page). ``include_prev`` adds the previous
    equal-length period for comparison charts (C2/C4)."""
    now = now or datetime.now(UTC)
    start_utc, end_utc = date_range_utc(start, end)
    scoped = db.query(WatchHistory).filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)

    views = scoped.count()
    watch_seconds_est = int(scoped.with_entities(func.coalesce(func.sum(_WATCH_SECONDS), 0)).scalar() or 0)
    distinct_videos = scoped.with_entities(func.count(func.distinct(WatchHistory.bvid))).scalar() or 0
    distinct_ups = scoped.with_entities(func.count(func.distinct(WatchHistory.up_mid))).scalar() or 0

    valid_samples = scoped.filter(
        or_(and_(_PROGRESS >= 0, _DURATION_OK), and_(_PROGRESS == -1, _DURATION_OK))
    ).count()
    bound_samples = scoped.filter(and_(_PROGRESS > 0, _NO_DURATION)).count()
    unknown_samples = max(views - valid_samples - bound_samples, 0)

    payload: dict = {
        "metrics_version": METRICS_VERSION,
        "timezone": TZ_NAME,
        "period": {
            "start": format_date(start),
            "end_exclusive": format_date(end),
            "is_complete": end <= now.astimezone(_SHANGHAI_TZ).date(),
            "generated_at": utcnow_naive(),
        },
        "views": views,
        "watch_seconds_est": watch_seconds_est,
        "avg_watch_seconds": int(watch_seconds_est / valid_samples) if valid_samples else None,
        "samples": {
            "valid": valid_samples,
            "bound": bound_samples,
            "unknown": unknown_samples,
        },
        "distinct_videos": distinct_videos,
        "distinct_ups": distinct_ups,
        "daily": _daily_series(db, start, end, now, start_utc, end_utc),
        "hourly": _hourly(db, start_utc, end_utc),
        "weekday": _weekday(db, start_utc, end_utc),
    }

    if extras:
        payload["duration_buckets"] = _duration_buckets(db, start_utc, end_utc)
        payload["completion_buckets"] = _completion_buckets(db, start_utc, end_utc)
        payload["tname_top"], payload["tname_coverage"] = _tname_top(db, start_utc, end_utc)
        payload["by_group"], payload["by_group_primary"] = _by_group(db, start_utc, end_utc)
        top_ups, top5_share = _top_ups(db, start_utc, end_utc, top_ups_limit)
        payload["top_ups"] = top_ups
        payload["top5_share"] = top5_share
        payload["new_videos"] = (
            db.query(Video)
            .filter(Video.pubdate.isnot(None), Video.pubdate >= start_utc, Video.pubdate < end_utc)
            .count()
        )
        payload["heatmap"] = _heatmap(db, start, end, start_utc, end_utc, now)
        payload["group_coverage"] = _group_coverage(db, start_utc, end_utc)
        payload["video_coverage"] = _video_coverage(db, start_utc, end_utc)
        payload["explore_return"] = _explore_return(db, start, end, start_utc, end_utc, now)

    if include_prev:
        span = end - start
        prev_start, prev_end = start - span, start
        prev_utc_start, prev_utc_end = date_range_utc(prev_start, prev_end)
        prev_scoped = db.query(WatchHistory).filter(
            WatchHistory.view_at >= prev_utc_start, WatchHistory.view_at < prev_utc_end
        )
        prev = {
            "period": {
                "start": format_date(prev_start),
                "end_exclusive": format_date(prev_end),
            },
            "views": prev_scoped.count(),
            "distinct_videos": prev_scoped.with_entities(
                func.count(func.distinct(WatchHistory.bvid))
            ).scalar()
            or 0,
            "distinct_ups": prev_scoped.with_entities(func.count(func.distinct(WatchHistory.up_mid))).scalar()
            or 0,
            "daily": _daily_series(db, prev_start, prev_end, now, prev_utc_start, prev_utc_end),
        }
        payload["previous"] = prev
        if extras:
            payload["up_delta"] = _up_delta(db, start_utc, end_utc, prev_utc_start, prev_utc_end)

    payload["coverage"] = _coverage(db, now)
    return payload


def _sh_tz_now(now: datetime) -> date:
    return now.astimezone(_SHANGHAI_TZ).date()


def _daily_series(
    db: Session,
    start: date,
    end: date,
    now: datetime,
    start_utc: str,
    end_utc: str,
) -> list[dict]:
    """One entry per Shanghai calendar day in [start, end), Monday-first for
    weeks. Days that have fully passed are zero-filled (confirmed no records
    within synced coverage); days not yet over (or beyond the observation
    cutoff) report ``views: None`` — never a fake zero."""
    rows = (
        db.query(
            _SH_DAY.label("day"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
        )
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .group_by("day")
        .all()
    )
    by_day = {str(day): (int(views), int(seconds)) for day, views, seconds in rows}
    today = _sh_tz_now(now)
    series = []
    day = start
    while day < end:
        day_str = format_date(day)
        if day <= today:
            views, seconds = by_day.get(day_str, (0, 0))
            series.append({"date": day_str, "views": views, "seconds": seconds, "covered": True})
        else:
            series.append({"date": day_str, "views": None, "seconds": None, "covered": False})
        day += timedelta(days=1)
    return series


def _hourly(db: Session, start_utc: str, end_utc: str) -> list[int]:
    hourly = [0] * 24
    for hour, count in (
        db.query(_SH_HOUR, func.count())
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .group_by(_SH_HOUR)
        .all()
    ):
        if hour is not None and str(hour).isdigit():
            hourly[int(hour)] = int(count)
    return hourly


def _weekday(db: Session, start_utc: str, end_utc: str) -> list[dict]:
    rows = dict(
        db.query(_SH_WEEKDAY, func.count())
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .group_by(_SH_WEEKDAY)
        .all()
    )
    return [
        {"label": _WEEKDAY_LABELS[i], "value": int(rows.get(sql_idx, 0))}
        for i, sql_idx in enumerate(_WEEKDAY_SQL_ORDER)
    ]


def _heatmap(db: Session, start: date, end: date, start_utc: str, end_utc: str, now: datetime) -> dict:
    """C1: weekday (Mon..Sun rows) x hour (00..23 cols) grid, Shanghai wall
    clock, record counts + estimated seconds per cell."""
    rows = (
        db.query(
            _SH_WEEKDAY.label("wd"),
            _SH_HOUR.label("hour"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
        )
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .group_by("wd", "hour")
        .all()
    )
    counts = {(str(wd), int(hour)): (int(v), int(s)) for wd, hour, v, s in rows}
    today = _sh_tz_now(now)
    days = []
    day = start
    while day < end:
        sql_idx = _WEEKDAY_SQL_ORDER[day.weekday()]
        past = day <= today
        hours = []
        for hour in range(24):
            views, seconds = counts.get((sql_idx, hour), (0, 0))
            # multi-week ranges aggregate by weekday; single weeks are per-date.
            hours.append({"views": views if past else None, "seconds": seconds if past else None})
        days.append(
            {
                "date": format_date(day),
                "weekday": day.weekday(),
                "hours": hours,
            }
        )
        day += timedelta(days=1)
    return {"hours": 24, "days": days}


def _duration_buckets(db: Session, start_utc: str, end_utc: str) -> list[dict]:
    labels = ["≤5分钟", "5-15分钟", "15-30分钟", "30-60分钟", "60分钟以上"]
    rows = dict(
        db.query(_DURATION_BUCKET, func.count())
        .filter(
            WatchHistory.view_at >= start_utc,
            WatchHistory.view_at < end_utc,
            WatchHistory.duration_seconds > 0,
        )
        .group_by(_DURATION_BUCKET)
        .all()
    )
    matched = sum(int(rows.get(label, 0)) for label in labels)
    total = (
        db.query(func.count())
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .scalar()
        or 0
    )
    return {
        "buckets": [{"label": label, "value": int(rows.get(label, 0))} for label in labels],
        "unknown": max(total - matched, 0),
    }


def _completion_buckets(db: Session, start_utc: str, end_utc: str) -> list[dict]:
    labels = ["0-25%", "25-50%", "50-75%", "75-99%", "看完"]
    rows = dict(
        db.query(_COMPLETION_BUCKET, func.count())
        .filter(
            WatchHistory.view_at >= start_utc,
            WatchHistory.view_at < end_utc,
            or_(and_(_PROGRESS == -1, _DURATION_OK), and_(_PROGRESS >= 0, _DURATION_OK)),
        )
        .group_by(_COMPLETION_BUCKET)
        .all()
    )
    matched = sum(int(rows.get(label, 0)) for label in labels)
    total = (
        db.query(func.count())
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .scalar()
        or 0
    )
    return {
        "buckets": [{"label": label, "value": int(rows.get(label, 0))} for label in labels],
        "unknown": max(total - matched, 0),
    }


def _tname_top(db: Session, start_utc: str, end_utc: str, limit: int = 8) -> tuple[list[dict], dict]:
    """内容分区 TOP with an explicit coverage note: rows whose video metadata
    is missing cannot be attributed and are reported as unmatched views."""
    total = (
        db.query(func.count())
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .scalar()
        or 0
    )
    rows = (
        db.query(WatchHistory)
        .join(Video, Video.bvid == WatchHistory.bvid)
        .filter(
            WatchHistory.view_at >= start_utc,
            WatchHistory.view_at < end_utc,
            Video.tname.isnot(None),
            Video.tname != "",
        )
        .with_entities(Video.tname.label("name"), func.count().label("views"))
        .group_by("name")
        .order_by(func.count().desc())
        .limit(limit)
        .all()
    )
    matched = sum(int(views) for _, views in rows)
    return (
        [{"name": str(name), "views": int(views)} for name, views in rows],
        {"matched": matched, "total": total},
    )


def _by_group(db: Session, start_utc: str, end_utc: str, limit: int = 8) -> tuple[list[dict], list[dict]]:
    """分组偏好, two calibers (multi-group membership is non-exclusive):

    - ``by_group``: every group the UP belongs to counts the record (non-
      exclusive; group sums exceed the total). Rendered with an overlap note.
    - ``by_group_primary``: attributed to the UP's primary group only
      (up_users.group_id; sums equal the total). Used for share charts.
    """
    non_exclusive = (
        db.query(WatchHistory)
        .join(GroupMember, GroupMember.up_mid == WatchHistory.up_mid, isouter=True)
        .join(GroupLocal, GroupLocal.id == GroupMember.group_id, isouter=True)
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .with_entities(
            func.coalesce(GroupLocal.name, "未分组").label("name"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
            func.count(func.distinct(WatchHistory.up_mid)).label("ups"),
        )
        .group_by("name")
        .order_by(func.count().desc())
        .limit(limit)
        .all()
    )
    primary = (
        db.query(WatchHistory)
        .join(UpUser, UpUser.mid == WatchHistory.up_mid, isouter=True)
        .join(GroupLocal, GroupLocal.id == UpUser.group_id, isouter=True)
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .with_entities(
            func.coalesce(GroupLocal.name, "未分组").label("name"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
        )
        .group_by("name")
        .order_by(func.count().desc())
        .limit(limit)
        .all()
    )
    return (
        [{"name": str(n), "views": int(v), "seconds": int(s), "ups": int(u)} for n, v, s, u in non_exclusive],
        [{"name": str(n), "views": int(v), "seconds": int(s)} for n, v, s in primary],
    )


def _top_ups(db: Session, start_utc: str, end_utc: str, limit: int) -> tuple[list[dict], float]:
    rows = (
        db.query(
            WatchHistory.up_mid.label("mid"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
        )
        .filter(
            WatchHistory.view_at >= start_utc,
            WatchHistory.view_at < end_utc,
            WatchHistory.up_mid.isnot(None),
        )
        .group_by("mid")
        .order_by(func.count().desc())
        .limit(limit)
        .all()
    )
    total = (
        db.query(func.count())
        .filter(
            WatchHistory.view_at >= start_utc,
            WatchHistory.view_at < end_utc,
            WatchHistory.up_mid.isnot(None),
        )
        .scalar()
        or 0
    )
    mids = [int(r.mid) for r in rows]
    names = resolve_names(db, mids) if mids else {}
    top_ups = [
        {
            "mid": int(r.mid),
            "uname": names.get(int(r.mid)).name if names.get(int(r.mid)) else None,
            "name_source": names.get(int(r.mid)).source if names.get(int(r.mid)) else None,
            "views": int(r.views),
            "seconds": int(r.seconds),
        }
        for r in rows
    ]
    top5 = sum(u["views"] for u in top_ups[:5])
    return top_ups, round(top5 / total, 3) if total else 0.0


def _group_member_sets(db: Session) -> tuple[dict[int, set[int]], dict[int, int], set[int]]:
    """(group_id -> member mids, group_id -> name, mids in NO group)."""
    membership: dict[int, set[int]] = {}
    for group_id, mid in db.query(GroupMember.group_id, GroupMember.up_mid).all():
        membership.setdefault(int(group_id), set()).add(int(mid))
    names = {int(g.id): g.name for g in db.query(GroupLocal).all()}
    all_ups = {int(mid) for (mid,) in db.query(UpUser.mid).filter(UpUser.missing.is_(False)).all()}
    ungrouped = all_ups - {mid for mids in membership.values() for mid in mids}
    return membership, names, ungrouped


def _group_coverage(db: Session, start_utc: str, end_utc: str) -> list[dict]:
    """C3: per group, UPs with watch records in range / UPs in the group.
    Groups are independent (one UP can appear in several groups; ratios must
    never be summed). Uses the CURRENT member set — archived reports freeze
    the set used at generation time inside their own snapshot."""
    watched_mids = {
        int(mid)
        for (mid,) in db.query(func.distinct(WatchHistory.up_mid))
        .filter(
            WatchHistory.view_at >= start_utc,
            WatchHistory.view_at < end_utc,
            WatchHistory.up_mid.isnot(None),
        )
        .all()
    }
    membership, names, ungrouped = _group_member_sets(db)
    result = []
    groups = sorted(membership.keys(), key=lambda gid: names.get(gid, ""))
    for group_id in groups:
        members = membership[group_id]
        covered = members & watched_mids
        result.append(
            {
                "group_id": group_id,
                "name": names.get(group_id, f"组 {group_id}"),
                "total": len(members),
                "covered": len(covered),
                "ratio": round(len(covered) / len(members), 3) if members else 0.0,
                "uncovered_sample": sorted(members - covered)[:50],
            }
        )
    if ungrouped:
        covered = ungrouped & watched_mids
        result.append(
            {
                "group_id": None,
                "name": "未分组",
                "total": len(ungrouped),
                "covered": len(covered),
                "ratio": round(len(covered) / len(ungrouped), 3) if ungrouped else 0.0,
                "uncovered_sample": sorted(ungrouped - covered)[:50],
            }
        )
    return result


def _video_coverage(db: Session, start_utc: str, end_utc: str, limit_groups: int = 12) -> list[dict]:
    """C5: 已同步投稿观看覆盖 — per group, distinct synced videos (videos
    table) of the group's UPs split into "watch records found in range" vs
    "no watch record found in range". Scoped to synced uploads only; missing
    video metadata means the upload was never fetched and is reported as
    coverage limitation, never as zero uploads."""
    watched_bvids = {
        str(bvid)
        for (bvid,) in db.query(func.distinct(WatchHistory.bvid))
        .filter(WatchHistory.view_at >= start_utc, WatchHistory.view_at < end_utc)
        .all()
    }
    membership, names, ungrouped = _group_member_sets(db)
    video_rows = db.query(Video.up_mid, Video.bvid).filter(Video.up_mid.isnot(None)).all()
    videos_by_group: dict[int | None, set[str]] = {}
    for up_mid, bvid in video_rows:
        key_groups = [gid for gid, mids in membership.items() if up_mid in mids]
        for gid in key_groups or [None]:
            is_member = (gid is not None and up_mid in membership.get(gid, set())) or (
                gid is None and up_mid in ungrouped
            )
            if is_member:
                videos_by_group.setdefault(gid, set()).add(str(bvid))
    result = []
    grouped_ids = sorted((g for g in videos_by_group if g is not None), key=lambda g: names.get(g, ""))
    ordered = list(grouped_ids)
    if None in videos_by_group:
        ordered.append(None)
    for gid in ordered[:limit_groups]:
        bvids = videos_by_group[gid]
        watched = bvids & watched_bvids
        result.append(
            {
                "group_id": gid,
                "name": names.get(gid, "未分组") if gid is not None else "未分组",
                "synced_videos": len(bvids),
                "watched_videos": len(watched),
                "unwatched_videos": len(bvids) - len(watched),
                "ratio": round(len(watched) / len(bvids), 3) if bvids else 0.0,
                "unwatched_sample": sorted(bvids - watched)[:50],
            }
        )
    return result


def _up_delta(
    db: Session,
    cur_start: str,
    cur_end: str,
    prev_start: str,
    prev_end: str,
    limit: int = 10,
) -> dict:
    """C4: per-UP record counts for this vs the previous comparable period,
    aggregated by mid (names resolved afterwards). Includes UPs with history
    who are not followed. Incomplete current period is flagged by the caller
    via period.is_complete."""

    def _counts(start: str, end: str) -> dict[int, int]:
        rows = (
            db.query(WatchHistory.up_mid, func.count())
            .filter(
                WatchHistory.view_at >= start,
                WatchHistory.view_at < end,
                WatchHistory.up_mid.isnot(None),
            )
            .group_by(WatchHistory.up_mid)
            .all()
        )
        return {int(mid): int(count) for mid, count in rows}

    cur, prev = _counts(cur_start, cur_end), _counts(prev_start, prev_end)
    all_mids = set(cur) | set(prev)
    names = resolve_names(db, sorted(all_mids)) if all_mids else {}
    items = []
    for mid in all_mids:
        c, p = cur.get(mid, 0), prev.get(mid, 0)
        if c == 0 and p == 0:
            continue
        change = "new" if p == 0 and c > 0 else ("up" if c > p else ("down" if c < p else "flat"))
        resolved = names.get(mid)
        items.append(
            {
                "mid": mid,
                "uname": resolved.name if resolved else None,
                "name_source": resolved.source if resolved else None,
                "current": c,
                "previous": p,
                "delta": c - p,
                "change": change,
            }
        )
    items.sort(key=lambda i: (-abs(i["delta"]), -i["current"]))
    risers = [i for i in items if i["delta"] > 0][:limit]
    fallers = sorted([i for i in items if i["delta"] < 0], key=lambda i: i["delta"])[:limit]
    return {"risers": risers, "fallers": fallers}


def _explore_return(
    db: Session, start: date, end: date, start_utc: str, end_utc: str, now: datetime
) -> list[dict]:
    """C6: per day, UPs first appearing in the LOCAL SAVED history on that
    day vs UPs already present in saved history before that day appearing
    again. Baseline is every record saved before the day — never a lifetime
    "first watch" claim. Daily categories are mutually exclusive and sum to
    the day's distinct UPs; weekly distinct UPs is NOT the daily sum. Future
    suppression uses the injected observation clock, like every other series."""
    first_seen: dict[int, str] = {}
    for mid, min_view in (
        db.query(WatchHistory.up_mid, func.min(WatchHistory.view_at))
        .filter(WatchHistory.up_mid.isnot(None))
        .group_by(WatchHistory.up_mid)
        .all()
    ):
        first_seen[int(mid)] = str(min_view)
    first_seen_day = {mid: shanghai_date(stamp) for mid, stamp in first_seen.items()}

    rows = (
        db.query(_SH_DAY.label("day"), WatchHistory.up_mid)
        .filter(
            WatchHistory.view_at >= start_utc,
            WatchHistory.view_at < end_utc,
            WatchHistory.up_mid.isnot(None),
        )
        .group_by("day", WatchHistory.up_mid)
        .all()
    )
    active_by_day: dict[str, set[int]] = {}
    for day, mid in rows:
        active_by_day.setdefault(str(day), set()).add(int(mid))

    today = _sh_tz_now(now)
    series = []
    day = start
    while day < end:
        day_str = format_date(day)
        if day > today:
            series.append({"date": day_str, "new_ups": None, "returning_ups": None, "covered": False})
        else:
            actives = active_by_day.get(day_str, set())
            new_ups = {mid for mid in actives if first_seen_day.get(mid) == day}
            series.append(
                {
                    "date": day_str,
                    "new_ups": len(new_ups),
                    "returning_ups": len(actives) - len(new_ups),
                    "covered": True,
                }
            )
        day += timedelta(days=1)
    return series


def _coverage(db: Session, now: datetime) -> dict:
    """Data coverage status: which settings bounded the last history sync and
    when it ran. Distinguishes 'confirmed no records in synced coverage' from
    'not synced / truncated / sync failed'."""
    from app.models import SyncRun
    from app.services.settings_store import get_section_raw

    last_sync = (
        db.query(SyncRun)
        .filter(SyncRun.kind.in_(["watch_history", "full"]), SyncRun.status == "success")
        .order_by(SyncRun.id.desc())
        .first()
    )
    truncated = False
    if last_sync and last_sync.stats_json:
        try:
            stats = __import__("json").loads(last_sync.stats_json)
            truncated = bool(stats.get("history_truncated"))
        except (TypeError, ValueError):
            truncated = False
    sync_cfg = get_section_raw(db, "sync")
    return {
        "timezone": TZ_NAME,
        "last_history_sync_at": last_sync.started_at if last_sync else None,
        "last_history_sync_status": last_sync.status if last_sync else None,
        "history_max_pages": sync_cfg.get("history_max_pages"),
        "history_window_days": sync_cfg.get("history_window_days"),
        "history_truncated": truncated,
        "observation_cutoff": utcnow_naive(),
        "observation_cutoff_iso": parse_utc(utcnow_naive()).astimezone(_SHANGHAI_TZ).isoformat(),
        "note": (
            "统计仅覆盖已同步的观看历史；未同步、分页截断或接口失败期间的数据不计入"
            if truncated or last_sync is None
            else "统计仅覆盖已同步的观看历史范围"
        ),
    }
