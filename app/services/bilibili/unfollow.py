from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.services.bilibili.client import API_BASE
from app.services.bilibili.cookies import load_cookies
from app.services.bilibili.qrlogin import build_client

if TYPE_CHECKING:
    from app.services.bilibili.client import BiliClient


def unfollow_users(db: Session, mids: list[int], client: BiliClient | None = None) -> int:
    """Cancel following for the given mids (destructive, audit-logged upstream).

    Rate-limited; returns count of confirmed unfollows. Raises
    RiskControlError when blocked — callers must stop and mark account risk.
    """
    own = client is None
    c = client or build_client(db)
    csrf = load_cookies(db).get("bili_jct", "")
    confirmed = 0
    try:
        for mid in mids:
            # POST /x/relation/modify act=2 = unfollow (RESEARCH §7.1).
            # Serial, rate-limited by the client; no auto-retry for a
            # destructive op (RiskControlError aborts the remaining mids).
            c._request(
                "POST",
                f"{API_BASE}/x/relation/modify",
                data={"fid": str(int(mid)), "act": "2", "re_src": "11", "csrf": csrf},
            )
            confirmed += 1
    finally:
        if own:
            c.close()
    return confirmed
