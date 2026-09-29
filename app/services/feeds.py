"""RSS/Atom feed rendering for BiliUP Organizer (hand-written XML, zero deps).

Frozen contract (implemented by the main agent after the RSS subagent hit the
concurrency limit): collect_entries / render_atom / render_feed_for_token.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.models import FeedToken, UpUser, Video


def _rfc3339(ts: str | None, fallback: datetime) -> str:
    """Convert stored 'YYYY-MM-DD HH:MM:SS' (UTC) to RFC3339 Z form."""
    if ts:
        text = ts.strip()
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return fallback.strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_entries(db: Session, feed_row: FeedToken) -> list[dict[str, Any]]:
    """Latest videos for the feed's group (or all followed UPs when group is
    NULL), excluding missing/blacklisted UPs, pubdate desc, limited to
    feed_row.max_items."""
    query = (
        db.query(Video, UpUser)
        .join(UpUser, UpUser.mid == Video.up_mid)
        .filter(UpUser.missing.is_(False), UpUser.blacklisted.is_(False))
        .order_by(Video.pubdate.desc(), Video.id.desc())
    )
    if feed_row.group_id is not None:
        query = query.filter(UpUser.group_id == feed_row.group_id)
    rows = query.limit(feed_row.max_items).all()
    return [
        {
            "bvid": video.bvid,
            "title": video.title,
            "pubdate": video.pubdate,
            "up_uname": up.uname,
            "up_mid": up.mid,
        }
        for video, up in rows
    ]


def render_atom(entries: list[dict[str, Any]], title: str, self_url: str) -> str:
    """Render an Atom 1.0 feed. All text is XML-escaped; no external deps."""
    now = datetime.now(UTC)
    feed_id = "urn:biliup-organizer:" + hashlib.sha256(self_url.encode()).hexdigest()[:16]
    updated = _rfc3339(None, now)
    for entry in entries:
        stamp = _rfc3339(entry.get("pubdate"), now)
        if stamp > updated:
            updated = stamp

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(title)}</title>",
        f"  <id>{escape(feed_id)}</id>",
        f"  <updated>{updated}</updated>",
        f'  <link rel="self" href="{escape(self_url)}"/>',
        '  <link rel="alternate" href="https://www.bilibili.com"/>',
    ]
    for entry in entries:
        stamp = _rfc3339(entry.get("pubdate"), now)
        link = f"https://www.bilibili.com/video/{entry['bvid']}"
        lines += [
            "  <entry>",
            f"    <id>urn:biliup:{escape(entry['bvid'])}</id>",
            f"    <title>{escape(entry['title'])}</title>",
            f'    <link rel="alternate" href="{escape(link)}"/>',
            f"    <published>{stamp}</published>",
            f"    <updated>{stamp}</updated>",
            f"    <author><name>{escape(entry['up_uname'])}</name></author>",
            "  </entry>",
        ]
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def render_feed_for_token(db: Session, feed_row: FeedToken, base_url: str) -> str:
    """collect_entries + render_atom with the feed name and self link."""
    entries = collect_entries(db, feed_row)
    self_url = f"{base_url}/feed/{feed_row.token}.xml"
    return render_atom(entries, feed_row.name, self_url)
