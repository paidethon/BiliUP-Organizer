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
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GroupLocal, Reminder, UpUser, Video, WatchHistory
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
        .join(GroupLocal, GroupLocal.id == UpUser.group_id, isouter=True)
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
