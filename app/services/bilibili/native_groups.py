from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.bilibili.client import BiliClient


def list_tags(db: Session, client: BiliClient | None = None) -> list[dict]:
    """Bilibili native follow tags for the stored account:
    [{bili_tag_id, bili_tag_name}]. Refreshes the native_group_map cache."""
    raise NotImplementedError("implemented by the bilibili agent")


def create_tag(db: Session, name: str, client: BiliClient | None = None) -> int:
    """Create a native tag and return its id (csrf via bili_jct)."""
    raise NotImplementedError("implemented by the bilibili agent")


def add_users_to_tag(db: Session, tag_id: int, mids: list[int], client: BiliClient | None = None) -> int:
    """Add users to a native tag (batched, rate-limited). Returns added count."""
    raise NotImplementedError("implemented by the bilibili agent")
