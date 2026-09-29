from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth import get_bilibili_account


def load_cookies(db: Session) -> dict[str, str]:
    """Stored Bilibili cookies for the account row (empty dict when logged out)."""
    import json

    account = get_bilibili_account(db)
    if not account.cookie_json:
        return {}
    try:
        data: dict[str, str] = json.loads(account.cookie_json)
        return data
    except json.JSONDecodeError:
        return {}
