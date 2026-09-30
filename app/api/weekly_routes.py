from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.models import AppSetting
from app.schemas import WeeklyReportOut
from app.util import utcnow

router = APIRouter(prefix="/weekly-report", tags=["weekly-report"])

_LATEST_KEY = "weekly_report:latest"


def store_report(db: Session, html: str) -> None:
    row = db.get(AppSetting, _LATEST_KEY)
    payload = __import__("json").dumps({"generated_at": utcnow(), "html": html}, ensure_ascii=False)
    if row is None:
        row = AppSetting(key=_LATEST_KEY, value=payload)
        db.add(row)
    else:
        row.value = payload
    db.commit()


def load_report(db: Session) -> dict | None:
    import json

    row = db.get(AppSetting, _LATEST_KEY)
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return None


@router.get("", response_model=WeeklyReportOut)
def get_report(admin: CurrentAdmin, db: DbSession) -> WeeklyReportOut:
    data = load_report(db)
    if data is None:
        return WeeklyReportOut()
    return WeeklyReportOut(generated_at=data.get("generated_at"), html=data.get("html"))


@router.post("/preview")
def preview(admin: CurrentAdmin, db: DbSession) -> dict:
    if get_settings().demo_mode:
        html = _demo_html(db)
        return {"generated_at": utcnow(), "html": html}
    from app.services.weekly_report import build_report

    html = build_report(db)
    return {"generated_at": utcnow(), "html": html}


@router.get("/stats")
def stats(admin: CurrentAdmin, db: DbSession, days: int = 7) -> dict:
    from app.services.weekly_report import build_stats

    return build_stats(db, days=max(1, min(days, 30)))


@router.post("/ai")
def ai_report(admin: CurrentAdmin, db: DbSession) -> dict:
    from app.services.weekly_report import build_ai_report

    result = build_ai_report(db)
    log_action(db, admin.username, "weekly_report.ai", detail={"fallback": result.get("fallback")})
    return result


@router.post("/send")
def send(admin: CurrentAdmin, db: DbSession) -> dict:
    settings = get_settings()
    if settings.demo_mode:
        html = _demo_html(db)
        store_report(db, html)
        return {"ok": True, "message": "demo mode: report generated locally, not emailed"}
    from app.services.weekly_report import send_weekly

    result = send_weekly(db)
    log_action(db, admin.username, "weekly_report.send", detail=result)
    return result


def _demo_html(db: Session) -> str:  # noqa: ANN001
    from app.demo import _UPS

    important = [u for u in _UPS if u[2] is not None and u[2] in (0, 4)]
    rows = "".join(f"<tr><td>{u[0]}</td><td>{u[4]} 天前</td><td>{u[5]} 次</td></tr>" for u in important)
    return (
        "<html><body style='font-family:sans-serif'>"
        "<h1>BiliUP Organizer 周报（演示数据）</h1>"
        f"<p>生成时间：{utcnow()}</p>"
        "<table border='1' cellpadding='6'><tr><th>重要UP</th><th>最近更新</th><th>累计观看</th></tr>"
        f"{rows}</table></body></html>"
    )
