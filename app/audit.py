from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog

# Never persist these keys in audit details.
_REDACT_KEYS = {"password", "cookie", "token", "api_key", "secret", "new_password", "old_password"}


def _redact(detail: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k.lower() in _REDACT_KEYS else v) for k, v in detail.items()}


def log_action(
    db: Session,
    actor: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            detail_json=json.dumps(_redact(detail), ensure_ascii=False) if detail else None,
        )
    )
    db.commit()
