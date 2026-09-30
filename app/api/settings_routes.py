from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.errors import bad_request
from app.schemas import SettingsOut, TestResultOut
from app.services.settings_store import load_sections, update_section

router = APIRouter(prefix="/settings", tags=["settings"])

_SECTIONS = ("ai", "smtp", "lumirss", "reminders", "sync")


@router.get("", response_model=SettingsOut)
def get_settings_api(admin: CurrentAdmin, db: DbSession) -> SettingsOut:
    sections = load_sections(db)
    return SettingsOut(**sections)


@router.put("/{section}")
def put_section(section: str, payload: dict, admin: CurrentAdmin, db: DbSession) -> dict:
    if section not in _SECTIONS:
        raise bad_request(f"unknown settings section: {section}")
    result = update_section(db, section, payload)
    log_action(db, admin.username, "settings.update", entity_type="settings", entity_id=section)
    return result


@router.post("/test/{what}", response_model=TestResultOut)
def test_integration(what: str, admin: CurrentAdmin, db: DbSession) -> TestResultOut:
    if what not in ("email", "ai", "lumirss"):
        raise bad_request(f"unknown integration: {what}")
    if get_settings().demo_mode:
        return TestResultOut(ok=True, message="demo mode: integration test skipped")
    if what == "email":
        from app.services.emailer import test_email

        ok, message = test_email(db)
    elif what == "ai":
        from app.services.ai_classifier import test_connection

        ok, message = test_connection(db)
    else:
        from app.services.lumirss import test_connection

        ok, message = test_connection(db)
    log_action(db, admin.username, f"settings.test_{what}", detail={"ok": ok, "message": message[:200]})
    return TestResultOut(ok=ok, message=message)


@router.post("/lumirss/detect")
def detect_lumirss(payload: dict, admin: CurrentAdmin, db: DbSession) -> dict:
    """GET-only probe of candidate LumiRSS URLs; writes base_url/inbox_endpoint."""
    if get_settings().demo_mode:
        return {"ok": False, "message": "demo mode: detect skipped", "tried": []}
    from app.services.lumirss_detect import detect_and_configure

    result = detect_and_configure(db, payload.get("base_url") or None)
    log_action(db, admin.username, "settings.lumirss_detect", detail={"ok": result["ok"]})
    return result
