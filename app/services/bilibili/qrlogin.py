from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.auth import get_bilibili_account
from app.services.bilibili.client import BiliClient
from app.util import utcnow

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# poll data.code status machine (RESEARCH §2.2); unknown codes read as waiting.
_STATUS_BY_CODE = {86101: "waiting", 86090: "scanned", 86038: "expired", 0: "confirmed"}


def start_login(db: Session) -> dict:
    """Create a QR login session.

    Returns {"qrcode_key": str, "qr_url": str, "expires_at": "YYYY-MM-DD HH:MM:SS"}.
    Must warm up visitor cookies (buvid3) first when required.
    """
    client = build_client(db)
    try:
        client.ensure_buvid()
        qr = client.generate_qrcode()
    finally:
        client.close()
    expires_at = (datetime.now(UTC) + timedelta(seconds=qr["expires_in"])).strftime(_TS_FORMAT)
    return {"qrcode_key": qr["qrcode_key"], "qr_url": qr["qr_url"], "expires_at": expires_at}


def poll_login(db: Session, qrcode_key: str) -> dict:
    """Poll once for the QR login status.

    Returns {"status": "waiting"|"scanned"|"confirmed"|"expired", "account": dict|None}.
    On "confirmed": persist cookies to bilibili_account (SESSDATA/bili_jct/
    DedeUserID...), set login_status='active', mid/uname from cookie or nav,
    and return {"account": BilibiliAccountOut-compatible dict}.
    """
    client = build_client(db)
    try:
        result = client.poll_qrcode(qrcode_key)
        status = _STATUS_BY_CODE.get(result["code"], "waiting")
        account_out: dict | None = None
        if status == "confirmed":
            account_out = _persist_account(db, client, result["cookies"])
    finally:
        client.close()
    return {"status": status, "account": account_out}


def _persist_account(db: Session, client: BiliClient, cookies: dict[str, str]) -> dict:
    account = get_bilibili_account(db)
    if cookies:
        account.cookie_json = json.dumps(cookies)
        account.cookie_updated_at = utcnow()
        account.login_status = "active"
        account.risk_flag = False
        raw_mid = str(cookies.get("DedeUserID") or "").strip()
        if raw_mid.isdigit():
            account.mid = int(raw_mid)
    # uname/avatar from nav are best-effort; a nav failure must not block
    # an otherwise confirmed login.
    try:
        nav = client.get_nav()
        if nav.get("uname"):
            account.uname = str(nav["uname"])
        if nav.get("face"):
            account.avatar = str(nav["face"])
    except Exception:  # noqa: BLE001 - deliberately swallow, nav is optional here
        pass
    db.commit()
    return {
        "login_status": account.login_status,
        "mid": account.mid,
        "uname": account.uname,
        "avatar": account.avatar,
        "cookie_updated_at": account.cookie_updated_at,
        "risk_flag": bool(account.risk_flag),
        "cookie_masked": "; ".join(f"{k}=••••" for k in cookies) if cookies else "••••",
    }


def build_client(db: Session) -> BiliClient:
    """BiliClient loaded with the stored cookies."""
    from app.services.bilibili.cookies import load_cookies

    return BiliClient(cookies=load_cookies(db))
