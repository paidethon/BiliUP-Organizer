"""HTML weekly report: build with Jinja2, store latest, and email it.

Thresholds mirror app/services/reminders.py so the report and the reminder
center always agree on what counts as stale / never watched / important but
unwatched.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import GroupLocal, GroupMember, Reminder, UpUser, Video, WatchHistory
from app.services.emailer import get_smtp_config, send_email
from app.services.settings_store import get_section_raw
from app.util import utcnow

log = logging.getLogger(__name__)

TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")
_LIST_LIMIT = 10

# watched seconds: prefer the real duration, fall back to progress (progress
# -1 means "watched to the end" but carries no length)
_WATCH_SECONDS = func.coalesce(
    func.nullif(WatchHistory.duration_seconds, 0),
    func.nullif(WatchHistory.progress, -1),
    0,
)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# UTC+8 wall clock for hour/weekday breakdowns (bilibili audiences are CN-based)
_CN_HOUR = func.substr(func.datetime(WatchHistory.view_at, "+8 hours"), 12, 2)
_CN_WEEKDAY = func.strftime("%w", func.datetime(WatchHistory.view_at, "+8 hours"))
# single-video length buckets, seconds
_DURATION_BUCKET = case(
    (WatchHistory.duration_seconds <= 300, "≤5分钟"),
    (WatchHistory.duration_seconds <= 900, "5-15分钟"),
    (WatchHistory.duration_seconds <= 1800, "15-30分钟"),
    (WatchHistory.duration_seconds <= 3600, "30-60分钟"),
    else_="60分钟以上",
)
# watch completion ratio: progress=-1 means finished; bounded by duration
_COMPLETION_RATIO = case(
    (WatchHistory.progress == -1, 1.0),
    (
        WatchHistory.duration_seconds > 0,
        func.min(WatchHistory.progress, WatchHistory.duration_seconds) * 1.0 / WatchHistory.duration_seconds,
    ),
    else_=None,
)
_COMPLETION_BUCKET = case(
    (_COMPLETION_RATIO < 0.25, "0-25%"),
    (_COMPLETION_RATIO < 0.5, "25-50%"),
    (_COMPLETION_RATIO < 0.75, "50-75%"),
    (_COMPLETION_RATIO < 1.0, "75-99%"),
    else_="看完",
)


def build_stats(db: Session, days: int = 7) -> dict:
    """Aggregate watch data for the dashboard/report charts via SQL sums.

    Everything the frontend renders comes from here — no row scans in Python.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = _fmt(now - timedelta(days=days))
    scoped = db.query(WatchHistory).filter(WatchHistory.view_at >= cutoff)

    views = scoped.count()
    watch_seconds = int(scoped.with_entities(func.coalesce(func.sum(_WATCH_SECONDS), 0)).scalar() or 0)

    daily_rows = (
        scoped.with_entities(
            func.substr(WatchHistory.view_at, 1, 10).label("day"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
        )
        .group_by("day")
        .order_by("day")
        .all()
    )
    daily = [
        {"date": str(day), "views": int(views), "seconds": int(seconds)} for day, views, seconds in daily_rows
    ]

    group_rows = (
        scoped.join(UpUser, UpUser.mid == WatchHistory.up_mid)
        .join(GroupMember, GroupMember.up_mid == WatchHistory.up_mid, isouter=True)
        .join(GroupLocal, GroupLocal.id == GroupMember.group_id, isouter=True)
        .with_entities(
            func.coalesce(GroupLocal.name, "未分组").label("name"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
        )
        .group_by("name")
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    by_group = [
        {"name": str(name), "views": int(views), "seconds": int(seconds)}
        for name, views, seconds in group_rows
    ]

    up_rows = (
        scoped.join(UpUser, UpUser.mid == WatchHistory.up_mid)
        .with_entities(
            UpUser.uname.label("uname"),
            func.count().label("views"),
            func.coalesce(func.sum(_WATCH_SECONDS), 0).label("seconds"),
        )
        .group_by(UpUser.mid, "uname")
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    top_ups = [
        {"uname": str(uname), "views": int(views), "seconds": int(seconds)}
        for uname, views, seconds in up_rows
    ]

    # ---- chart data for the report page (10 additional aggregations) ----

    hourly = [0] * 24
    for hour, count in scoped.with_entities(_CN_HOUR, func.count()).group_by(_CN_HOUR).all():
        if hour is not None and str(hour).isdigit():
            hourly[int(hour)] = int(count)

    weekday_names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    weekday_rows = dict(scoped.with_entities(_CN_WEEKDAY, func.count()).group_by(_CN_WEEKDAY).all())
    weekday = [
        {"label": weekday_names[int(index)], "value": int(weekday_rows.get(index, 0))}
        for index in ["1", "2", "3", "4", "5", "6", "0"]  # 周一..周日
    ]

    duration_labels = ["≤5分钟", "5-15分钟", "15-30分钟", "30-60分钟", "60分钟以上"]
    duration_rows = dict(
        scoped.filter(WatchHistory.duration_seconds > 0)
        .with_entities(_DURATION_BUCKET, func.count())
        .group_by(_DURATION_BUCKET)
        .all()
    )
    duration_buckets = [
        {"label": label, "value": int(duration_rows.get(label, 0))} for label in duration_labels
    ]

    completion_labels = ["0-25%", "25-50%", "50-75%", "75-99%", "看完"]
    completion_rows = dict(
        scoped.filter((WatchHistory.progress == -1) | (WatchHistory.duration_seconds > 0))
        .with_entities(_COMPLETION_BUCKET, func.count())
        .group_by(_COMPLETION_BUCKET)
        .all()
    )
    completion_buckets = [
        {"label": label, "value": int(completion_rows.get(label, 0))} for label in completion_labels
    ]

    tname_rows = (
        scoped.join(Video, Video.bvid == WatchHistory.bvid)
        .filter(Video.tname.isnot(None), Video.tname != "")
        .with_entities(Video.tname.label("name"), func.count().label("views"))
        .group_by("name")
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    tname_top = [{"name": str(name), "views": int(views)} for name, views in tname_rows]

    cutoff_30 = _fmt(now - timedelta(days=30))
    daily_30_rows = (
        db.query(WatchHistory)
        .filter(WatchHistory.view_at >= cutoff_30)
        .with_entities(
            func.substr(WatchHistory.view_at, 1, 10).label("day"),
            func.count().label("views"),
        )
        .group_by("day")
        .order_by("day")
        .all()
    )
    daily_30 = [{"date": str(day), "views": int(views)} for day, views in daily_30_rows]
    running = 0
    cumulative = []
    for point in daily_30:
        running += point["views"]
        cumulative.append({**point, "total": running})

    follow_rows = (
        db.query(func.substr(UpUser.followed_at, 1, 7).label("month"), func.count())
        .filter(UpUser.followed_at.isnot(None))
        .group_by("month")
        .order_by("month")
        .limit(12)
        .all()
    )
    follow_trend = [{"month": str(month), "count": int(count)} for month, count in follow_rows]

    top5_views = sum(u["views"] for u in top_ups[:5])
    top5_share = round(top5_views / views, 3) if views else 0.0

    cutoff_never = _fmt(now - timedelta(days=30))
    recent_follows = (
        db.query(UpUser).filter(UpUser.followed_at.isnot(None), UpUser.followed_at < cutoff_never).count()
    )
    never_watched = (
        db.query(UpUser)
        .filter(UpUser.followed_at.isnot(None), UpUser.followed_at < cutoff_never, UpUser.watched_count == 0)
        .count()
    )
    never_watched_ratio = round(never_watched / recent_follows, 3) if recent_follows else 0.0

    group_completion_rows = (
        scoped.join(UpUser, UpUser.mid == WatchHistory.up_mid)
        .join(GroupMember, GroupMember.up_mid == WatchHistory.up_mid)
        .join(GroupLocal, GroupLocal.id == GroupMember.group_id)
        .filter((WatchHistory.progress == -1) | (WatchHistory.duration_seconds > 0))
        .with_entities(GroupLocal.name.label("name"), func.avg(_COMPLETION_RATIO).label("avg_ratio"))
        .group_by("name")
        .order_by(func.avg(_COMPLETION_RATIO).desc())
        .limit(8)
        .all()
    )
    group_completion = [
        {"name": str(name), "ratio": round(float(avg_ratio or 0), 3)}
        for name, avg_ratio in group_completion_rows
    ]

    return {
        "days": days,
        "generated_at": utcnow(),
        "total_ups": db.query(UpUser).filter(UpUser.missing.is_(False)).count(),
        "groups": db.query(GroupLocal).count(),
        "new_videos": db.query(Video).filter(Video.pubdate.isnot(None), Video.pubdate >= cutoff).count(),
        "views": views,
        "watch_seconds": watch_seconds,
        "avg_video_seconds": int(watch_seconds / views) if views else 0,
        "daily": daily,
        "by_group": by_group,
        "top_ups": top_ups,
        # chart extensions
        "hourly": hourly,
        "weekday": weekday,
        "duration_buckets": duration_buckets,
        "completion_buckets": completion_buckets,
        "tname_top": tname_top,
        "daily_30": daily_30,
        "cumulative": cumulative,
        "follow_trend": follow_trend,
        "top5_share": top5_share,
        "never_watched_ratio": never_watched_ratio,
        "group_completion": group_completion,
    }


def _human_duration(seconds: int) -> str:
    minutes, sec = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分钟"
    if minutes:
        return f"{minutes} 分钟"
    return f"{sec} 秒"


def _days_since(ts: str | None, now: datetime) -> int:
    if not ts:
        return 0
    try:
        then = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0
    return max((now - then).days, 0)


def _active_ups(db: Session, now_str: str) -> list[UpUser]:
    """UPs eligible for reminder-style evaluation (skip missing/blacklisted/snoozed)."""
    result: list[UpUser] = []
    for up in db.query(UpUser).all():
        if up.missing or up.blacklisted:
            continue
        if up.snoozed_until is not None and up.snoozed_until > now_str:
            continue
        result.append(up)
    return result


def build_report(db: Session) -> str:
    """Render app/templates/weekly_report.html.j2 (Jinja2) and return the HTML.

    Context: generated_at, totals (ups, groups, videos/7d, views/7d), up-to-10
    entries each for stale / never_watched / important_unwatched, and the count
    of open reminders. Inline CSS only (email-safe), zh-CN copy. Persisting the
    result via api.weekly_routes.store_report is the caller's job.
    """
    prefs = get_section_raw(db, "reminders")
    stale_days = int(prefs.get("stale_days") or 30)
    never_days = int(prefs.get("never_watched_days") or 30)

    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC, matches stored stamps
    now_str = utcnow()
    cutoff_stale = _fmt(now - timedelta(days=stale_days))
    cutoff_never = _fmt(now - timedelta(days=never_days))

    total_ups = db.query(UpUser).count()
    group_count = db.query(GroupLocal).count()
    stats = build_stats(db)

    important_groups = {g.id for g in db.query(GroupLocal).filter(GroupLocal.is_important.is_(True)).all()}

    stale: list[dict] = []
    never_watched: list[dict] = []
    important_unwatched: list[dict] = []
    for up in _active_ups(db, now_str):
        if up.last_video_at is None or up.last_video_at < cutoff_stale:
            stale.append(
                {
                    "mid": up.mid,
                    "uname": up.uname,
                    "last_video_at": up.last_video_at,
                    "days": _days_since(up.last_video_at, now),
                }
            )
        if up.followed_at is not None and up.followed_at < cutoff_never and (up.watched_count or 0) == 0:
            never_watched.append(
                {
                    "mid": up.mid,
                    "uname": up.uname,
                    "followed_at": up.followed_at,
                    "days": _days_since(up.followed_at, now),
                }
            )
        if (
            up.group_id is not None
            and up.group_id in important_groups
            and up.last_video_at is not None
            and (up.last_watched_at is None or up.last_video_at > up.last_watched_at)
        ):
            important_unwatched.append(
                {
                    "mid": up.mid,
                    "uname": up.uname,
                    "title": up.last_video_title or "无标题",
                    "last_video_at": up.last_video_at,
                }
            )

    # oldest known last-video first; UPs that never posted (NULL) go last since
    # they have no "stopped updating" date and are covered by never_watched
    stale.sort(key=lambda item: item["last_video_at"] or "9999")
    never_watched.sort(key=lambda item: item["followed_at"])
    important_unwatched.sort(key=lambda item: item["last_video_at"], reverse=True)

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    return env.get_template("weekly_report.html.j2").render(
        generated_at=now_str,
        total_ups=total_ups,
        groups=group_count,
        new_videos=stats["new_videos"],
        watched=stats["views"],
        watch_duration=_human_duration(stats["watch_seconds"]),
        daily=stats["daily"],
        by_group=stats["by_group"],
        top_ups=stats["top_ups"],
        stale=stale[:_LIST_LIMIT],
        never_watched=never_watched[:_LIST_LIMIT],
        important_unwatched=important_unwatched[:_LIST_LIMIT],
        open_reminders=db.query(Reminder).filter(Reminder.status == "open").count(),
    )


def build_ai_report(db: Session) -> dict:
    """AI-narrated weekly report with a deterministic machine fallback.

    Sends only the aggregate stats (no titles/PII beyond counts) through the
    configured OpenAI-compatible endpoint; on any failure returns the template
    report with fallback=True so the feature degrades instead of breaking.
    """
    stats = build_stats(db)
    try:
        from app.services.ai_classifier import _ai_config, _chat

        cfg = _ai_config(db)
    except Exception:  # noqa: BLE001 - unconfigured AI is the normal fallback path
        return {
            "ok": True,
            "fallback": True,
            "html": build_report(db),
            "message": "AI 未配置，已生成机器统计版周报",
        }

    compact = {
        "days": stats["days"],
        "views": stats["views"],
        "watch_minutes": stats["watch_seconds"] // 60,
        "avg_video_minutes": stats["avg_video_seconds"] // 60,
        "new_videos": stats["new_videos"],
        "daily": stats["daily"],
        "by_group": stats["by_group"],
        "top_ups": stats["top_ups"],
        "total_ups": stats["total_ups"],
    }
    system = (
        "你是B站观看数据分析师。根据JSON统计写一份中文周报分析，"
        "输出简洁的HTML片段（只用<section><h3><p><ul><li><strong>标签，禁止style/script），"
        "包含：总体观看习惯、分组偏好、最常看的UP、给用户的2-3条具体建议。"
    )
    try:
        content = _chat(
            cfg["base_url"], cfg["api_key"], cfg["model"], json.dumps(compact, ensure_ascii=False), system
        )
    except Exception as exc:  # noqa: BLE001 - any upstream problem falls back
        log.warning("ai weekly report failed, using machine report: %s", exc)
        return {
            "ok": True,
            "fallback": True,
            "html": build_report(db),
            "message": f"AI 生成失败，已回退机器版：{exc}",
        }

    html = (
        "<html><head><meta charset='utf-8'></head>"
        '<body style="margin:0;padding:16px;background:#f4f5f7;'
        "font-family:'PingFang SC','Microsoft YaHei',sans-serif;color:#27272a;\">"
        "<div style='max-width:640px;margin:0 auto;background:#fff;border-radius:10px;padding:20px 24px;'>"
        f"<p style='color:#71717a;font-size:12px;margin:0 0 12px;'>AI 分析 · 基于近 {stats['days']} 天数据 · "
        f"观看 {_human_duration(stats['watch_seconds'])}</p>{content}</div></body></html>"
    )
    return {"ok": True, "fallback": False, "html": html, "message": "AI 分析已生成"}


def send_weekly(db: Session) -> dict:
    """Build + email the weekly report and store it as the latest one.

    Returns {"ok", "message"}; ok=False when the weekly report is disabled in
    the reminders settings, when SMTP is not configured, or when sending fails
    (ApiError is swallowed into a result so scheduler/API callers always get a
    plain dict). On success the HTML is stored via
    app.api.weekly_routes.store_report under key "weekly_report:latest".
    """
    prefs = get_section_raw(db, "reminders")
    if not prefs.get("weekly_report_enabled", True):
        return {"ok": False, "message": "周报发送已在设置中关闭"}

    cfg = get_smtp_config(db)
    if not str(cfg.get("host") or "").strip() or not str(cfg.get("to_addr") or "").strip():
        return {"ok": False, "message": "SMTP 未配置，无法发送周报"}

    from app.api.weekly_routes import store_report

    html = build_report(db)
    subject = f"[BiliUP Organizer] 周报 {utcnow()[:10]}"
    try:
        send_email(db, subject, html)
    except Exception as exc:  # noqa: BLE001 - report the failure, never crash the job
        message = getattr(exc, "message", None) or str(exc)
        return {"ok": False, "message": f"周报发送失败：{message}"}
    store_report(db, html)
    return {"ok": True, "message": "周报已生成并发送", "generated_at": utcnow()}
