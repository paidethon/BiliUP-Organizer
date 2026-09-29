from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.bilibili.client import BiliClient


def fetch_followings(db: Session, client: BiliClient | None = None) -> list[dict]:
    """Fetch every followings entry for the stored account.

    Returns a list of dicts with at least:
    mid, uname, sign, face, official_type, special(bool), followed_at (ISO).
    Wbi-signed, paginated (ps=50), rate-limited.
    """
    raise NotImplementedError("implemented by the bilibili agent")


def fetch_latest_archive(db: Session, mid: int, client: BiliClient | None = None) -> dict | None:
    """Latest upload for an UP: {bvid, title, pubdate(ISO), pic, length} or None."""
    raise NotImplementedError("implemented by the bilibili agent")


def fetch_history(db: Session, max_pages: int = 5, client: BiliClient | None = None) -> list[dict]:
    """Recent watch history, newest first.

    Returns dicts with: bvid, title, author_mid(int|None), view_at(ISO), progress.
    """
    raise NotImplementedError("implemented by the bilibili agent")


def fetch_user_card(db: Session, mid: int, client: BiliClient | None = None) -> dict | None:
    """Public user card: {mid, uname, sign, face, official_type} or None."""
    raise NotImplementedError("implemented by the bilibili agent")
