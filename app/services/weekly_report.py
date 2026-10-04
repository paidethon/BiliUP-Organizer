"""Weekly report service — natural-week archive with revisions.

Week = Monday..Sunday in Asia/Shanghai, half-open
[Mon 00:00, next Mon 00:00). Every report is a frozen snapshot: stats JSON +
offline-readable HTML generated from ONE observation cutoff. Page rendering,
AI interpretation, email and exports all reuse the same snapshot — nothing
recomputes numbers from "today" for an archived week.

- 预览 (save=False): compute from the range, never persist.
- 生成并保存: creates an explicit new revision; earlier revisions stay
  readable. No SMTP/AI dependency whatsoever.
- 幂等: the scheduler skips generating a revision whose content hash equals
  the latest one for the same week (manual regenerations always create one).
- legacy: the old "weekly_report:latest" app_settings row is migrated by
  m0006 into an is_legacy archive with its original HTML and timestamp; a
  rolling-7-days snapshot is never restated as an exact natural week.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
from datetime import UTC, date, datetime, timedelta

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.models import GroupLocal, GroupMember, Reminder, UpUser, WeeklyReport
from app.services import stats as stats_service
from app.services.emailer import get_smtp_config, send_email
from app.services.settings_store import get_section_raw
from app.timeutil import (
    METRICS_VERSION,
    TZ_NAME,
    date_range_utc,
    format_date,
    shanghai_iso,
    shanghai_today,
    utcnow_naive,
    week_bounds,
)
from app.timeutil import (
    week_start as monday_of,
)

log = logging.getLogger(__name__)

TEMPLATE_DIR = str(pathlib.Path(__file__).resolve().parent.parent / "templates")
_LIST_LIMIT = 10
_HUMAN_MIN = 60
_HUMAN_HOUR = 3600


# --------------------------------------------------------------- generation


def resolve_week(day: date | None = None) -> tuple[date, date, bool]:
    """(week_start_monday, week_end_exclusive, is_complete) for the week
    containing ``day`` (Shanghai calendar)."""
    today = shanghai_today()
    target = day or today
    start, end = week_bounds(target)
    return start, end, end <= today


def build_week_snapshot(db: Session, week_start: date, now: datetime | None = None) -> dict:
    """Compute the full stats payload + reminder lists for one natural week.
    The snapshot embeds the member sets used (C3) so later group edits can
    never silently rewrite an archived report."""
    start, end = week_bounds(week_start)
    payload = stats_service.range_stats(
        db,
        start,
        end,
        include_prev=True,
        extras=True,
        now=now or datetime.now(UTC),
    )
    payload["lists"] = _reminder_lists(db, now or datetime.now(UTC))
    payload["metrics_note"] = (
        "观看时长为按记录进度估算（有效进度与对应时长折算），非精确实际播放时长；"
        "统计范围仅覆盖已同步的观看历史。"
    )
    return payload


def generate_report(
    db: Session,
    week_start: date,
    *,
    save: bool,
    actor: str = "system",
    force_revision: bool = False,
) -> WeeklyReport | dict:
    """Render + optionally persist one natural-week report as a new revision.

    Future weeks are refused (no fabricated reports). Incomplete weeks are
    allowed and carry is_complete=False so the UI can label them. Identical
    content (same fingerprint) does NOT create a duplicate revision — the
    explicit「重新生成」path passes force_revision=True to publish a new
    revision even when the numbers did not change."""
    start, end, _complete = resolve_week(week_start)  # works for any day of the week
    today = shanghai_today()
    if start > today:
        return {"ok": False, "message": "所选周尚未开始，不能生成未来报告"}

    snapshot = build_week_snapshot(db, start)
    html = render_report_html(db, snapshot, start, end)
    generated_at = utcnow_naive()
    content_hash = _content_hash(snapshot, start, end)

    if not save:
        return WeeklyReport(
            scope="default",
            period_start=format_date(start),
            period_end_exclusive=format_date(end),
            timezone=TZ_NAME,
            metrics_version=METRICS_VERSION,
            revision=1,
            is_legacy=False,
            status="archived",
            generated_at=generated_at,
            data_cutoff=min(_end_to_utc(end), generated_at),
            coverage_json=json.dumps(snapshot.get("coverage", {}), ensure_ascii=False),
            stats_json=json.dumps(snapshot, ensure_ascii=False),
            html=html,
            content_hash=content_hash,
        )

    latest = _latest_revision(db, start)
    if latest is not None and latest.content_hash == content_hash and not force_revision:
        return latest  # idempotent: identical content, no duplicate revision

    report = WeeklyReport(
        scope="default",
        period_start=format_date(start),
        period_end_exclusive=format_date(end),
        timezone=TZ_NAME,
        metrics_version=METRICS_VERSION,
        revision=(latest.revision + 1) if latest else 1,
        is_legacy=False,
        status="archived",
        generated_at=generated_at,
        data_cutoff=min(_end_to_utc(end), generated_at),
        coverage_json=json.dumps(snapshot.get("coverage", {}), ensure_ascii=False),
        stats_json=json.dumps(snapshot, ensure_ascii=False),
        html=html,
        content_hash=content_hash,
    )
    db.add(report)
    db.commit()
    log.info("stored weekly report rev=%s week=%s actor=%s", report.revision, report.period_start, actor)
    return report


def _latest_revision(db: Session, week_start: date) -> WeeklyReport | None:
    return (
        db.query(WeeklyReport)
        .filter(
            WeeklyReport.scope == "default",
            WeeklyReport.period_start == format_date(week_start),
        )
        .order_by(WeeklyReport.revision.desc())
        .first()
    )


def _content_hash(snapshot: dict, start: date, end: date) -> str:
    basis = {
        "period": [format_date(start), format_date(end)],
        "metrics_version": snapshot.get("metrics_version"),
        "views": snapshot.get("views"),
        "watch_seconds_est": snapshot.get("watch_seconds_est"),
        "distinct_videos": snapshot.get("distinct_videos"),
        "distinct_ups": snapshot.get("distinct_ups"),
        "generated_day": shanghai_today().isoformat(),
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _end_to_utc(end: date) -> str:
    return date_range_utc(end, end)[0]


# ------------------------------------------------------------ auto (scheduler)


def generate_last_complete_week(db: Session) -> WeeklyReport | dict:
    """Scheduled job target: last COMPLETE natural week, idempotent."""
    today = shanghai_today()
    last_complete = monday_of(today) - timedelta(days=7)
    return generate_report(db, last_complete, save=True, actor="scheduler")


# ------------------------------------------------------------------ queries


def latest_report(db: Session) -> WeeklyReport | None:
    """Newest non-legacy archived report (for the old GET endpoint)."""
    return (
        db.query(WeeklyReport)
        .filter(WeeklyReport.is_legacy.is_(False))
        .order_by(WeeklyReport.id.desc())
        .first()
    )


def legacy_report(db: Session) -> WeeklyReport | None:
    return db.query(WeeklyReport).filter(WeeklyReport.is_legacy.is_(True)).first()


def list_archives(db: Session, limit: int = 104) -> list[dict]:
    rows = (
        db.query(WeeklyReport)
        .order_by(WeeklyReport.period_start.desc().nulls_last(), WeeklyReport.revision.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "scope": r.scope,
            "period_start": r.period_start,
            "period_end_exclusive": r.period_end_exclusive,
            "timezone": r.timezone,
            "metrics_version": r.metrics_version,
            "revision": r.revision,
            "is_legacy": bool(r.is_legacy),
            "status": r.status,
            "generated_at": r.generated_at,
            "generated_at_shanghai": shanghai_iso(r.generated_at),
            "data_cutoff": r.data_cutoff,
            "send_status": r.send_status,
            "sent_at": r.sent_at,
            "sent_to": r.sent_to,
            "views": _snapshot_views(r),
            "content_hash": r.content_hash,
        }
        for r in rows
    ]


def _snapshot_views(report: WeeklyReport) -> int | None:
    try:
        return int(json.loads(report.stats_json).get("views"))
    except (TypeError, ValueError):
        return None


def archive_summary(db: Session) -> dict:
    """Weeks that already have an archive, keyed by Monday, latest revision."""
    rows = (
        db.query(WeeklyReport)
        .filter(WeeklyReport.is_legacy.is_(False))
        .order_by(WeeklyReport.period_start.desc(), WeeklyReport.revision.desc())
        .all()
    )
    seen: set[str] = set()
    items: list[dict] = []
    for r in rows:
        if r.period_start in seen:
            continue
        seen.add(r.period_start)
        items.append(
            {
                "period_start": r.period_start,
                "period_end_exclusive": r.period_end_exclusive,
                "latest_revision": r.revision,
                "generated_at_shanghai": shanghai_iso(r.generated_at),
                "status": r.status,
                "views": _snapshot_views(r),
            }
        )
    return {"weeks": items}


# ------------------------------------------------------------------- export


def export_json(report: WeeklyReport) -> dict:
    return {
        "report": {
            "id": report.id,
            "scope": report.scope,
            "period_start": report.period_start,
            "period_end_exclusive": report.period_end_exclusive,
            "timezone": report.timezone,
            "metrics_version": report.metrics_version,
            "revision": report.revision,
            "is_legacy": bool(report.is_legacy),
            "generated_at": report.generated_at,
            "generated_at_shanghai": shanghai_iso(report.generated_at),
            "data_cutoff": report.data_cutoff,
            "send_status": report.send_status,
            "sent_at": report.sent_at,
        },
        "stats": _safe_json(report.stats_json),
        "coverage": _safe_json(report.coverage_json),
    }


def export_markdown(report: WeeklyReport) -> str:
    """Offline-readable Markdown rendered from the frozen snapshot."""
    stats = _safe_json(report.stats_json)
    lines: list[str] = []
    period = report.period_start or "（旧版滚动区间）"
    end_label = _inclusive_end_label(report)
    lines.append(f"# BiliUP Organizer 周报（{period} ~ {end_label}）")
    lines.append("")
    generated = shanghai_iso(report.generated_at) or report.generated_at
    lines.append(f"- 修订: r{report.revision} · 生成: {generated}（Asia/Shanghai）")
    if report.is_legacy:
        lines.append("- 说明: 旧版周报（滚动 7 天），区间无法精确还原为自然周")
    cutoff = stats.get("coverage", {}).get("note")
    if cutoff:
        lines.append(f"- 数据覆盖: {cutoff}")
    lines.append("")
    samples = stats.get("samples", {})
    lines.append("## 总览")
    lines.append("")
    lines.append(f"- 观看记录数: {stats.get('views', 0)}")
    seconds = stats.get("watch_seconds_est") or 0
    lines.append(f"- 估算观看时长: {_human_duration(seconds)}（按记录进度估算）")
    avg = stats.get("avg_watch_seconds")
    lines.append(f"- 平均单记录估算时长: {_human_duration(avg) if avg else '无有效样本'}")
    lines.append(
        f"- 样本: 有效 {samples.get('valid', 0)} / 下界 {samples.get('bound', 0)}"
        f" / 未知 {samples.get('unknown', 0)}"
    )
    lines.append(f"- 去重视频: {stats.get('distinct_videos', 0)} · 去重 UP: {stats.get('distinct_ups', 0)}")
    lines.append("")
    daily = stats.get("daily") or []
    if daily:
        lines.append("## 每日观看（周一至周日，Asia/Shanghai）")
        lines.append("")
        lines.append("| 日期 | 记录数 |")
        lines.append("| --- | --- |")
        for day in daily:
            value = "—" if day.get("views") is None else str(day["views"])
            lines.append(f"| {day['date']} | {value} |")
        lines.append("")
    by_group = stats.get("by_group") or []
    if by_group:
        lines.append("## 分组偏好（非互斥，UP 可属于多个分组）")
        lines.append("")
        lines.append("| 分组 | 记录数 | UP 数 |")
        lines.append("| --- | --- | --- |")
        for g in by_group:
            lines.append(f"| {g['name']} | {g['views']} | {g.get('ups', '—')} |")
        lines.append("")
    top_ups = stats.get("top_ups") or []
    if top_ups:
        lines.append("## TOP UP（按记录数）")
        lines.append("")
        for up in top_ups:
            name = up.get("uname") or "mid:{}".format(up.get("mid"))
            lines.append("- {}: {} 条".format(name, up.get("views")))
        lines.append("")
    lists = stats.get("lists", {})
    for key, title in (
        ("stale", "长期未更新"),
        ("never_watched", "已同步范围内未发现观看记录（非终身判断）"),
        ("important_unwatched", "重要 UP 有更新未观看"),
    ):
        rows = lists.get(key) or []
        if rows:
            lines.append(f"## {title}")
            lines.append("")
            for up in rows:
                lines.append(f"- {up.get('uname')}")
            lines.append("")
    lines.append("---")
    lines.append("本文件由快照导出；数字为生成时刻的冻结值。")
    return "\n".join(lines)


def _inclusive_end_label(report: WeeklyReport) -> str:
    if not report.period_end_exclusive:
        return "?"
    try:
        end = date.fromisoformat(report.period_end_exclusive)
    except ValueError:
        return report.period_end_exclusive
    return format_date(end - timedelta(days=1))


def _safe_json(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# -------------------------------------------------------------- HTML render


def render_report_html(db: Session, snapshot: dict, start: date, end: date) -> str:
    """Offline-readable HTML (inline CSS, email-safe): static bars + data
    tables for every section. The interactive web page is the primary
    surface; this archive keeps the same numbers without JS dependencies."""
    end_inclusive = end - timedelta(days=1)
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    period_gen = snapshot.get("period", {})
    generated_shanghai = shanghai_iso(period_gen.get("generated_at")) or period_gen.get("generated_at", "")
    avg_seconds = snapshot.get("avg_watch_seconds")
    return env.get_template("weekly_report.html.j2").render(
        period=f"{format_date(start)} ~ {format_date(end_inclusive)}",
        is_complete=period_gen.get("is_complete", True),
        timezone=TZ_NAME,
        generated_at=generated_shanghai,
        total_ups=snapshot.get("total_ups", 0),
        groups=snapshot.get("groups", 0),
        new_videos=snapshot.get("new_videos", 0),
        watched=snapshot.get("views", 0),
        watch_duration=_human_duration(snapshot.get("watch_seconds_est") or 0),
        avg_duration=_human_duration(avg_seconds) if avg_seconds else "—",
        samples=snapshot.get("samples", {}),
        daily=snapshot.get("daily", []),
        hourly=snapshot.get("hourly", []),
        by_group=snapshot.get("by_group", []),
        by_group_primary=snapshot.get("by_group_primary", []),
        top_ups=snapshot.get("top_ups", []),
        heatmap_rows=_heatmap_table_rows(snapshot),
        group_coverage=snapshot.get("group_coverage", []),
        video_coverage=snapshot.get("video_coverage", []),
        explore_return=snapshot.get("explore_return", []),
        up_delta=snapshot.get("up_delta", {}),
        duration_buckets=(snapshot.get("duration_buckets") or {}).get("buckets", []),
        completion_buckets=(snapshot.get("completion_buckets") or {}).get("buckets", []),
        tname_top=snapshot.get("tname_top", []),
        tname_coverage=snapshot.get("tname_coverage", {}),
        coverage_note=(snapshot.get("coverage") or {}).get("note", ""),
        lists=snapshot.get("lists", {}),
        metrics_note=snapshot.get("metrics_note", ""),
        open_reminders=db.query(Reminder).filter(Reminder.status == "open").count(),
        max_daily=_max_daily(snapshot),
        fmt_seconds=_human_duration,
    )


def _heatmap_table_rows(snapshot: dict) -> list[dict]:
    """Flatten C1 for the HTML table: one row per weekday with 24 hour cells."""
    heatmap = snapshot.get("heatmap") or {}
    by_weekday: dict[int, list[int]] = {}
    for day in heatmap.get("days", []):
        weekday = day.get("weekday")
        if weekday is None:
            continue
        cells = by_weekday.setdefault(int(weekday), [0] * 24)
        hours = day.get("hours") or []
        for hour, cell in enumerate(hours[:24]):
            value = cell.get("views")
            if value is not None:
                cells[hour] = cells[hour] + int(value)
    return [
        {"weekday": idx, "label": label, "hours": by_weekday.get(idx, [0] * 24)}
        for idx, label in enumerate(stats_service._WEEKDAY_LABELS)
    ]


def _max_daily(snapshot: dict) -> int:
    return max((d.get("views") or 0) for d in (snapshot.get("daily") or [])) if snapshot.get("daily") else 0


# ------------------------------------------------------------ reminder lists


def _reminder_lists(db: Session, now: datetime) -> dict:
    """Reminder-style lists evaluated at the snapshot's observation cutoff,
    mirroring app/services/reminders.py thresholds (stale_days /
    never_watched_days) so the report and the reminder center agree. 重要UP
    membership is multi-group aware (is_important group via GroupMember)."""
    prefs = get_section_raw(db, "reminders")
    stale_days = int(prefs.get("stale_days") or 30)
    never_days = int(prefs.get("never_watched_days") or 30)

    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_stale = (now - timedelta(days=stale_days)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_never = (now - timedelta(days=never_days)).strftime("%Y-%m-%d %H:%M:%S")

    important_groups = {g.id for g in db.query(GroupLocal).filter(GroupLocal.is_important.is_(True)).all()}
    important_mids = (
        {
            int(mid)
            for (mid,) in db.query(GroupMember.up_mid)
            .filter(GroupMember.group_id.in_(important_groups))
            .all()
        }
        if important_groups
        else set()
    )

    stale: list[dict] = []
    never_watched: list[dict] = []
    important_unwatched: list[dict] = []
    for up in db.query(UpUser).all():
        if up.missing or up.blacklisted:
            continue
        if up.snoozed_until is not None and up.snoozed_until > now_str:
            continue
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
            up.mid in important_mids
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

    # oldest known last-video first; never-posted UPs are covered by
    # never_watched and would sort arbitrarily otherwise
    stale.sort(key=lambda item: item["last_video_at"] or "9999")
    never_watched.sort(key=lambda item: item["followed_at"] or "")
    important_unwatched.sort(key=lambda item: item["last_video_at"], reverse=True)
    return {
        "stale": stale[:_LIST_LIMIT],
        "never_watched": never_watched[:_LIST_LIMIT],
        "important_unwatched": important_unwatched[:_LIST_LIMIT],
        "stale_total": len(stale),
        "never_watched_total": len(never_watched),
        "important_unwatched_total": len(important_unwatched),
    }


def _days_since(ts: str | None, now: datetime) -> int:
    if not ts:
        return 0
    try:
        then = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0
    if now.tzinfo is not None:
        now = now.astimezone(UTC).replace(tzinfo=None)
    return max((now - then).days, 0)


def _human_duration(seconds: int | None) -> str:
    seconds = max(0, int(seconds or 0))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分钟"
    if minutes:
        return f"{minutes} 分钟"
    return f"{sec} 秒"


# --------------------------------------------------------------------- send


def send_report(db: Session, report: WeeklyReport) -> dict:
    """Email the stored snapshot of THIS revision. Failures keep the archive
    untouched (send_status=failed) and never recompute another report."""
    if report.is_legacy:
        return {"ok": False, "message": "旧版周报缺少结构化快照，请先重新生成再发送"}
    prefs = get_section_raw(db, "reminders")
    if not prefs.get("weekly_report_enabled", True):
        return {"ok": False, "message": "周报发送已在设置中关闭"}

    cfg = get_smtp_config(db)
    if not str(cfg.get("host") or "").strip() or not str(cfg.get("to_addr") or "").strip():
        return {"ok": False, "message": "SMTP 未配置，无法发送周报"}

    start_label = report.period_start or ""
    end_label = _inclusive_end_label(report)
    subject = f"[BiliUP Organizer] 周报 {start_label}~{end_label} r{report.revision}"
    try:
        send_email(db, subject, report.html)
    except Exception as exc:  # noqa: BLE001 — report the failure, keep the archive
        message = getattr(exc, "message", None) or str(exc)
        report.send_status = "failed"
        db.commit()
        return {"ok": False, "message": f"周报发送失败：{message}"}
    report.send_status = "sent"
    report.sent_at = utcnow_naive()
    report.sent_to = str(cfg.get("to_addr"))
    report.status = "sent"
    db.commit()
    return {
        "ok": True,
        "message": f"周报 r{report.revision} 已发送",
        "sent_to": report.sent_to,
        "sent_at": report.sent_at,
    }


def send_weekly(db: Session) -> dict:
    """Legacy entry point: generate last complete week + send it."""
    report = generate_last_complete_week(db)
    if isinstance(report, dict):
        return {"ok": False, "message": report.get("message", "周报生成失败")}
    return send_report(db, report)


# ---------------------------------------------------------------------- AI


def build_ai_text(db: Session, report: WeeklyReport) -> dict:
    """Optional AI interpretation of a stored snapshot. The AI only narrates;
    it never receives or rewrites the numbers. Failure keeps the machine
    snapshot intact."""
    stats = _safe_json(report.stats_json)
    compact = {
        "period": [report.period_start, report.period_end_exclusive],
        "views": stats.get("views"),
        "watch_minutes": (stats.get("watch_seconds_est") or 0) // 60,
        "daily": stats.get("daily"),
        "by_group": stats.get("by_group"),
        "top_ups": stats.get("top_ups"),
    }
    try:
        from app.services.ai_classifier import _ai_config, _chat

        cfg = _ai_config(db)
    except Exception:  # noqa: BLE001 — unconfigured AI is the normal fallback path
        return {"ok": False, "message": "AI 未配置，机器统计快照不受影响"}
    system = (
        "你是B站观看数据分析师。根据JSON统计写一段中文解读（100-200字），"
        "只能引用给出的数字，不得编造或修改数据。"
    )
    try:
        content = _chat(
            cfg["base_url"],
            cfg["api_key"],
            cfg["model"],
            json.dumps(compact, ensure_ascii=False),
            system,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"AI 解读失败：{exc}"}
    report.ai_text = content
    db.commit()
    return {"ok": True, "ai_text": content}
