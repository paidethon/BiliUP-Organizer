from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.auth import get_bilibili_account


def load_cookies(db: Session) -> dict[str, str]:
    account = get_bilibili_account(db)
    if not account.cookie_json:
        return {}
    try:
        data: dict[str, str] = json.loads(account.cookie_json)
        return data
    except json.JSONDecodeError:
        return {}


class BiliClient:
    """Synchronous httpx client for the Bilibili web API.

    Frozen interface (implemented by the bilibili agent):

    - ``__init__(cookies: dict[str, str] | None = None)``
    - ``_request(method, url, params=None, data=None, wbi=False) -> dict``:
      returns ``data`` when ``code == 0``; maps -101 -> AuthExpiredError,
      -412/-352 -> RiskControlError, other codes -> BiliError. Applies rate
      limiting and retries with backoff.
    - ``ensure_buvid() -> None``: warm up visitor cookies (buvid3).
    - ``get_nav() -> dict``
    - ``generate_qrcode() -> dict`` (qr_url, qrcode_key, expires seconds)
    - ``poll_qrcode(qrcode_key) -> dict`` (status + cookies on confirm)
    - ``get_followings(mid, page, page_size=50) -> dict`` (total, list)
    - ``get_all_followings(mid) -> list[dict]``
    - ``get_user_archives(mid, page=1, page_size=30) -> dict`` (total, vlist)
    - ``get_latest_archive(mid) -> dict | None``
    - ``get_history(page=1, page_size=20) -> dict`` (total, list)
    - ``close() -> None``
    """

    def __init__(self, cookies: dict[str, str] | None = None) -> None:
        raise NotImplementedError("implemented by the bilibili agent")

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        wbi: bool = False,
    ) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
