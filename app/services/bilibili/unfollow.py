from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.bilibili.client import BiliClient


def unfollow_users(db: Session, mids: list[int], client: BiliClient | None = None) -> int:
    """Cancel following for the given mids (destructive, audit-logged upstream).

    Rate-limited; returns count of confirmed unfollows. Raises
    RiskControlError when blocked — callers must stop and mark account risk.
    """
    raise NotImplementedError("implemented by the bilibili agent")
