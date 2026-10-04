"""Weekly report API: archive-first, natural-week, Shanghai timezone.

Endpoints (all behind the standard admin auth/CSRF):
- GET  /weekly-report                     latest stored report (legacy compat)
- GET  /weekly-report/week?date=          week metadata + stored revisions for
                                           the week containing date (Shanghai)
- GET  /weekly-report/archives            archive list + per-week summary
- GET  /weekly-report/stats?start&end     live aggregation for an arbitrary
                                           Shanghai range (preview surface)
- POST /weekly-report/generate            {week_start, save} -> preview (no
                                           persist) or generate+save a revision
- GET  /weekly-report/{id}                one archived revision (snapshot)
- POST /weekly-report/{id}/regenerate     explicit new revision of that week
- POST /weekly-report/{id}/send           email THIS revision's stored snapshot
- POST /weekly-report/{id}/ai             optional AI narration (never edits stats)
- GET  /weekly-report/{id}/export?format  html | md | json download
- POST /weekly-report/preview             legacy rolling preview (kept for old
                                           clients; new UI uses /generate save=false)
- POST /weekly-report/send                legacy: last complete week + send
"""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.models import WeeklyReport
from app.schemas import WeeklyReportOut
from app.services import weekly_report as service
from app.timeutil import format_date, parse_date, shanghai_today
from app.timeutil import week_start as monday_of

router = APIRouter(prefix="/weekly-report", tags=["weekly-report"])


def _report_or_404(db: Session, report_id: int) -> WeeklyReport:
    report = db.get(WeeklyReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


def _report_payload(report: WeeklyReport) -> dict:
    return {
        "id": report.id,
        "scope": report.scope,
        "period_start": report.period_start,
        "period_end_exclusive": report.period_end_exclusive,
        "timezone": report.timezone,
        "metrics_version": report.metrics_version,
        "revision": report.revision,
        "is_legacy": bool(report.is_legacy),
        "status": report.status,
        "generated_at": report.generated_at,
        "generated_at_shanghai": _shanghai_or_none(report.generated_at),
        "data_cutoff": report.data_cutoff,
        "send_status": report.send_status,
        "sent_at": report.sent_at,
        "sent_to": report.sent_to,
        "stats": service._safe_json(report.stats_json),
        "ai_text": report.ai_text,
    }


def _shanghai_or_none(stamp: str | None) -> str | None:
    from app.timeutil import shanghai_iso

    return shanghai_iso(stamp)


def _export_stem(report: WeeklyReport) -> str:
    """Safe download filename: sanitized period + revision (no path chars)."""
    period = (report.period_start or "legacy").replace("-", "")
    return f"biliup-weekly-{period}-r{report.revision}"


@router.get("", response_model=WeeklyReportOut)
def get_report(admin: CurrentAdmin, db: DbSession) -> WeeklyReportOut:
    latest = service.latest_report(db)
    if latest is None:
        legacy = service.legacy_report(db)
        if legacy is not None:
            return WeeklyReportOut(generated_at=legacy.generated_at, html=legacy.html)
        return WeeklyReportOut()
    return WeeklyReportOut(generated_at=latest.generated_at, html=latest.html)


@router.get("/week")
def week_info(admin: CurrentAdmin, db: DbSession, date: str | None = Query(default=None)) -> dict:
    """Week metadata for the Shanghai week containing ``date`` plus any stored
    revisions. Any day of the week resolves to the same natural week."""
    target = parse_date(date)
    if date and target is None:
        raise HTTPException(status_code=400, detail="invalid date, expected YYYY-MM-DD")
    start, end, is_complete = service.resolve_week(target)
    revisions = (
        db.query(WeeklyReport)
        .filter(WeeklyReport.scope == "default", WeeklyReport.period_start == format_date(start))
        .order_by(WeeklyReport.revision.desc())
        .all()
    )
    return {
        "week_start": format_date(start),
        "week_end_exclusive": format_date(end),
        "week_end_inclusive_label": format_date(end - timedelta(days=1)),
        "is_complete": is_complete,
        "today": format_date(shanghai_today()),
        "timezone": "Asia/Shanghai",
        "revisions": [
            {
                "id": r.id,
                "revision": r.revision,
                "generated_at_shanghai": _shanghai_or_none(r.generated_at),
                "status": r.status,
                "send_status": r.send_status,
                "views": service._snapshot_views(r),
            }
            for r in revisions
        ],
    }


@router.get("/archives")
def archives(admin: CurrentAdmin, db: DbSession) -> dict:
    return service.archive_summary(db)


@router.get("/stats")
def stats(
    admin: CurrentAdmin,
    db: DbSession,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int | None = Query(default=None, le=30),
) -> dict:
    """Live aggregation. Preferred: start+end (Shanghai dates, end exclusive).
    Legacy days=N keeps a Shanghai-based rolling window ending today."""
    from app.services.stats import range_stats

    if start and end:
        start_day, end_day = parse_date(start), parse_date(end)
        if start_day is None or end_day is None:
            raise HTTPException(status_code=400, detail="invalid range, expected YYYY-MM-DD")
        if end_day <= start_day:
            raise HTTPException(status_code=400, detail="end must be after start")
        return range_stats(db, start_day, end_day, include_prev=True)
    if days:
        from datetime import timedelta

        today = shanghai_today()
        return range_stats(db, today - timedelta(days=days), today, include_prev=False)
    start_day, end_day, _ = service.resolve_week()
    return range_stats(db, start_day, end_day, include_prev=True)


class GenerateIn(BaseModel):
    week_start: str  # any date inside the target week, YYYY-MM-DD
    save: bool = False


@router.post("/generate")
def generate(admin: CurrentAdmin, db: DbSession, payload: GenerateIn) -> dict:
    """Preview (save=false) or generate+save a revision for the week that
    contains week_start. No SMTP/AI dependency for saving."""
    week_day = parse_date(payload.week_start)
    if week_day is None:
        raise HTTPException(status_code=400, detail="invalid week_start, expected YYYY-MM-DD")
    result = service.generate_report(db, week_day, save=payload.save, actor=admin.username)
    if isinstance(result, dict):  # only errors come back as plain dicts
        raise HTTPException(status_code=400, detail=result.get("message", "generate failed"))
    log_action(
        db,
        admin.username,
        "weekly_report.generate",
        detail={"week_start": format_date(monday_of(week_day)), "save": payload.save},
    )
    return {"saved": bool(payload.save), "report": _report_payload(result)}


@router.get("/{report_id}")
def get_archived(admin: CurrentAdmin, db: DbSession, report_id: int) -> dict:
    report = _report_or_404(db, report_id)
    return _report_payload(report)


@router.post("/{report_id}/regenerate")
def regenerate(admin: CurrentAdmin, db: DbSession, report_id: int) -> dict:
    """Create an explicit new revision; the original stays readable."""
    old = _report_or_404(db, report_id)
    if old.is_legacy or not old.period_start:
        raise HTTPException(status_code=400, detail="旧版周报没有自然周区间，请选择具体周重新生成")
    week_day = parse_date(old.period_start)
    if week_day is None:
        raise HTTPException(status_code=400, detail="stored period_start is not a valid date")
    result = service.generate_report(db, week_day, save=True, actor=admin.username, force_revision=True)
    if isinstance(result, dict):
        raise HTTPException(status_code=400, detail=result.get("message", "regenerate failed"))
    log_action(db, admin.username, "weekly_report.regenerate", entity_id=str(report_id))
    return {"saved": True, "report": _report_payload(result)}


@router.post("/{report_id}/send")
def send(admin: CurrentAdmin, db: DbSession, report_id: int) -> dict:
    report = _report_or_404(db, report_id)
    result = service.send_report(db, report)
    log_action(db, admin.username, "weekly_report.send", entity_id=str(report_id), detail=result)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("message", "send failed"))
    return result


@router.post("/{report_id}/ai")
def ai(admin: CurrentAdmin, db: DbSession, report_id: int) -> dict:
    report = _report_or_404(db, report_id)
    result = service.build_ai_text(db, report)
    log_action(db, admin.username, "weekly_report.ai", entity_id=str(report_id))
    return result


@router.get("/{report_id}/export")
def export(
    admin: CurrentAdmin, db: DbSession, report_id: int, format: str = Query(default="html")
) -> Response:
    report = _report_or_404(db, report_id)
    stem = _export_stem(report)
    if format == "html":
        return Response(
            content=report.html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.html"'},
        )
    if format == "md":
        return Response(
            content=service.export_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
        )
    if format == "json":
        return Response(
            content=json.dumps(service.export_json(report), ensure_ascii=False, indent=1),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
        )
    raise HTTPException(status_code=400, detail="format must be html, md or json")


# ----------------------------------------------------------- legacy endpoints


@router.post("/preview")
def preview(admin: CurrentAdmin, db: DbSession) -> dict:
    """Legacy rolling preview kept for old clients: current Shanghai week."""
    if get_settings().demo_mode:
        html = _demo_html(db)
        return {"generated_at": _now(), "html": html}
    start, end, _ = service.resolve_week()
    snapshot = service.build_week_snapshot(db, start)
    html = service.render_report_html(db, snapshot, start, end)
    return {"generated_at": _now(), "html": html}


@router.post("/send")
def send_legacy(admin: CurrentAdmin, db: DbSession) -> dict:
    settings = get_settings()
    if settings.demo_mode:
        html = _demo_html(db)
        store_report(db, html)
        return {"ok": True, "message": "demo mode: report generated locally, not emailed"}
    result = service.send_weekly(db)
    log_action(db, admin.username, "weekly_report.send", detail=result)
    return result


def store_report(db: Session, html: str) -> None:
    """Backwards-compatible store used by demo mode and legacy callers."""
    from app.models import AppSetting
    from app.util import utcnow

    row = db.get(AppSetting, "weekly_report:latest")
    payload = json.dumps({"generated_at": utcnow(), "html": html}, ensure_ascii=False)
    if row is None:
        db.add(AppSetting(key="weekly_report:latest", value=payload))
    else:
        row.value = payload
    db.commit()


def _now() -> str:
    from app.timeutil import utcnow_naive

    return utcnow_naive()


def _demo_html(db: Session) -> str:  # noqa: ANN001
    from app.demo import _UPS

    important = [u for u in _UPS if u[2] is not None and u[2] in (0, 4)]
    rows = "".join(f"<tr><td>{u[0]}</td><td>{u[4]} 天前</td><td>{u[5]} 次</td></tr>" for u in important)
    return (
        "<html><body style='font-family:sans-serif'>"
        "<h1>BiliUP Organizer 周报（演示数据）</h1>"
        f"<p>生成时间：{_now()}</p>"
        "<table border='1' cellpadding='6'><tr><th>重要UP</th><th>最近更新</th><th>累计观看</th></tr>"
        f"{rows}</table></body></html>"
    )
