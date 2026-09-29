"""HTML weekly report: build with Jinja2, store latest, and email it.

Thresholds mirror app/services/reminders.py so the report and the reminder
center always agree on what counts as stale / never watched / important but
unwatched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.models import GroupLocal, Reminder, UpUser, Video, WatchHistory
from app.services.emailer import get_smtp_config, send_email
from app.services.settings_store import get_section_raw
from app.util import utcnow

TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")
_LIST_LIMIT = 10


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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
    cutoff_week = _fmt(now - timedelta(days=7))
    cutoff_stale = _fmt(now - timedelta(days=stale_days))
    cutoff_never = _fmt(now - timedelta(days=never_days))

    total_ups = db.query(UpUser).count()
    group_count = db.query(GroupLocal).count()
    new_videos = db.query(Video).filter(Video.pubdate.isnot(None), Video.pubdate >= cutoff_week).count()
    watched = db.query(WatchHistory).filter(WatchHistory.view_at >= cutoff_week).count()

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
        new_videos=new_videos,
        watched=watched,
        stale=stale[:_LIST_LIMIT],
        never_watched=never_watched[:_LIST_LIMIT],
        important_unwatched=important_unwatched[:_LIST_LIMIT],
        open_reminders=db.query(Reminder).filter(Reminder.status == "open").count(),
    )


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
