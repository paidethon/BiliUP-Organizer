from __future__ import annotations

from sqlalchemy.orm import Session


def collect_entries(db: Session, feed_row) -> list[dict]:  # noqa: ANN001
    """Frozen contract (implemented by the RSS agent):

    Latest videos for the feed's group (or all followed UPs when group is NULL),
    excluding missing/blacklisted UPs, ordered pubdate desc, limited to
    feed_row.max_items. Each entry: {bvid, title, pubdate, up_uname, up_mid}.
    """
    raise NotImplementedError("implemented by the RSS agent")


def render_atom(entries: list[dict], title: str, self_url: str) -> str:
    """Hand-written Atom 1.0 XML (xml.sax.saxutils.escape for all text; no
    external dependency). updated = max pubdate or now. Entries link to
    https://www.bilibili.com/video/{bvid}."""
    raise NotImplementedError("implemented by the RSS agent")


def render_feed_for_token(db: Session, feed_row, base_url: str) -> str:  # noqa: ANN001
    """collect_entries + render_atom with feed name and self link."""
    raise NotImplementedError("implemented by the RSS agent")
