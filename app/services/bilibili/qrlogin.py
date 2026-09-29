from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.bilibili.client import BiliClient


def start_login(db: Session) -> dict:
    """Create a QR login session.

    Returns {"qrcode_key": str, "qr_url": str, "expires_at": "YYYY-MM-DD HH:MM:SS"}.
    Must warm up visitor cookies (buvid3) first when required.
    """
    raise NotImplementedError("implemented by the bilibili agent")


def poll_login(db: Session, qrcode_key: str) -> dict:
    """Poll once for the QR login status.

    Returns {"status": "waiting"|"scanned"|"confirmed"|"expired", "account": dict|None}.
    On "confirmed": persist cookies to bilibili_account (SESSDATA/bili_jct/
    DedeUserID...), set login_status='active', mid/uname from cookie or nav,
    and return {"account": BilibiliAccountOut-compatible dict}.
    """
    raise NotImplementedError("implemented by the bilibili agent")


def build_client(db: Session) -> BiliClient:
    """BiliClient loaded with the stored cookies."""
    from app.services.bilibili.cookies import load_cookies

    return BiliClient(cookies=load_cookies(db))
