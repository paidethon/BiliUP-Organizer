"""Settings storage: env defaults overridden by the app_settings table.

Secrets are stored in the DB (single-user self-hosted app) but always masked in
API responses. An empty secret value on update means "keep the stored one".
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import bad_request, not_found
from app.models import AppSetting
from app.schemas import AiSection, LumirssSection, ReminderPrefs, SmtpSection, SyncPrefs
from app.util import utcnow

_SECTIONS: dict[str, type] = {
    "ai": AiSection,
    "smtp": SmtpSection,
    "lumirss": LumirssSection,
    "reminders": ReminderPrefs,
    "sync": SyncPrefs,
}
_SECRET_FIELDS: dict[str, set[str]] = {"ai": {"api_key"}, "smtp": {"password"}, "lumirss": {"token"}}
_MASK = "••••••••"


def _env_defaults(section: str) -> dict[str, Any]:
    s = get_settings()
    if section == "ai":
        data: dict[str, Any] = {
            "base_url": s.ai_base_url,
            "api_key": s.ai_api_key,
            "model": s.ai_model,
            "enabled": False,
        }
    elif section == "smtp":
        data = {
            "host": s.smtp_host,
            "port": s.smtp_port,
            "username": s.smtp_username,
            "password": s.smtp_password,
            "from_addr": s.smtp_from,
            "to_addr": s.smtp_to,
            "use_tls": s.smtp_use_tls,
            "enabled": False,
        }
    elif section == "lumirss":
        data = {
            "base_url": s.lumirss_base_url,
            "token": s.lumirss_token,
            "inbox_endpoint": s.lumirss_inbox_endpoint,
            "enabled": False,
        }
    else:
        data = {}
    return data


def _stored(db: Session, section: str) -> dict[str, Any]:
    row = db.get(AppSetting, f"section:{section}")
    if row is None:
        return {}
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return {}


def get_section_raw(db: Session, section: str) -> dict[str, Any]:
    """Unmasked section values, for service use."""
    if section not in _SECTIONS:
        raise not_found(f"unknown settings section {section}")
    data = _env_defaults(section)
    data.update(_stored(db, section))
    return data


def load_sections(db: Session) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, model in _SECTIONS.items():
        data = get_section_raw(db, name)
        configured = bool(data.get("enabled")) and all(
            v for k, v in data.items() if k in _SECRET_FIELDS.get(name, set())
        )
        if name == "ai":
            configured = bool(data.get("base_url")) and bool(data.get("api_key")) and bool(data.get("model"))
        elif name == "smtp":
            configured = bool(data.get("host")) and bool(data.get("to_addr"))
        elif name == "lumirss":
            configured = bool(data.get("base_url")) and bool(data.get("token"))
        masked = dict(data)
        for field in _SECRET_FIELDS.get(name, set()):
            if masked.get(field):
                masked[field] = _MASK
        out[name] = {**model(**masked).model_dump(), "configured": configured}
    return out


def update_section(db: Session, section: str, payload: dict[str, Any]) -> dict[str, Any]:
    if section not in _SECTIONS:
        raise not_found(f"unknown settings section {section}")
    model = _SECTIONS[section]
    current = get_section_raw(db, section)
    incoming = {k: v for k, v in payload.items() if k in model.model_fields}
    for field in _SECRET_FIELDS.get(section, set()):
        value = incoming.get(field)
        if value is None or value == "" or value == _MASK:
            incoming[field] = current.get(field, "")
    merged = {**current, **incoming}
    try:
        model(**merged)
    except Exception as exc:  # pydantic validation
        raise bad_request(f"invalid settings for {section}", str(exc)) from exc
    row = db.get(AppSetting, f"section:{section}")
    if row is None:
        row = AppSetting(key=f"section:{section}", value="{}")
        db.add(row)
    row.value = json.dumps(merged, ensure_ascii=False)
    row.updated_at = utcnow()
    db.commit()
    return load_sections(db)[section]
