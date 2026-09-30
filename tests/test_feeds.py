from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-feeds-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.db import get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import FeedToken, GroupLocal, GroupMember, UpUser, Video  # noqa: E402
from app.services.feeds import collect_entries, render_atom  # noqa: E402

NS = {"a": "http://www.w3.org/2005/Atom"}
_MAX_XML_BYTES = 1_000_000


def _safe_parse(xml: str) -> ET.Element:
    """Parse trusted-and-checked XML: reject DTD entities and oversize input."""
    if len(xml) > _MAX_XML_BYTES:
        raise ValueError("xml too large")
    lowered = xml[:200].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("DTD entities are not allowed")
    return ET.fromstring(xml)


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def fixture_data(db):  # noqa: ANN001, ANN201
    group = GroupLocal(name=f"RSS组{datetime.now(UTC).timestamp()}")
    db.add(group)
    db.flush()
    up_ok = UpUser(mid=880000001, uname="RSS组内UP", group_id=group.id)
    up_gone = UpUser(mid=880000002, uname="RSS已取关UP", group_id=group.id, missing=True)
    up_black = UpUser(mid=880000003, uname="RSS拉黑UP", group_id=group.id, blacklisted=True)
    up_outside = UpUser(mid=880000004, uname="RSS组外UP")
    db.add_all([up_ok, up_gone, up_black, up_outside])
    db.flush()
    existing = {row[0] for row in db.query(GroupMember.up_mid).filter(GroupMember.group_id == group.id).all()}
    for up in (up_ok, up_gone, up_black):
        if up.mid not in existing:
            db.add(GroupMember(up_mid=up.mid, group_id=group.id))
    db.flush()
    base = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)
    rows = [
        (up_ok, "组内视频A & 特别篇"),
        (up_ok, "组内视频B <更新>"),
        (up_gone, "已取关不该出现"),
        (up_black, "已拉黑不该出现"),
        (up_outside, "组外不该出现"),
    ]
    vids = []
    for idx, (up, title) in enumerate(rows):
        video = Video(
            bvid=f"BV1rss{idx:03d}",
            up_mid=up.mid,
            title=title,
            pubdate=(base + timedelta(hours=idx)).strftime("%Y-%m-%d %H:%M:%S"),
        )
        db.add(video)
        vids.append(video)
    feed_all = FeedToken(name="全部", token="rss-token-all", group_id=None, max_items=100)
    feed_group = FeedToken(name="RSS组", token="rss-token-group", group_id=group.id, max_items=2)
    db.add_all([feed_all, feed_group])
    db.commit()
    yield {"group": group, "feed_all": feed_all, "feed_group": feed_group, "up_ok": up_ok}
    for video in vids:
        db.delete(video)
    for feed in (feed_all, feed_group):
        db.delete(feed)
    for up in (up_ok, up_gone, up_black, up_outside):
        db.delete(up)
    db.delete(group)
    db.commit()


def test_collect_entries_group_filter_and_excludes(db, fixture_data) -> None:  # noqa: ANN001
    entries = collect_entries(db, fixture_data["feed_group"])
    mids = {entry["up_mid"] for entry in entries}
    assert mids == {fixture_data["up_ok"].mid}
    bvids = [entry["bvid"] for entry in entries]
    assert bvids == ["BV1rss001", "BV1rss000"]  # newest first, max_items=2

    all_entries = collect_entries(db, fixture_data["feed_all"])
    assert len(all_entries) >= 3  # includes demo-seeded videos too


def test_render_atom_parses_and_escapes(db, fixture_data) -> None:  # noqa: ANN001
    entries = collect_entries(db, fixture_data["feed_group"])
    xml = render_atom(entries, "测试 & 源 <2026>", "http://test.local/feed/t.xml")
    root = _safe_parse(xml)
    assert root.tag == "{http://www.w3.org/2005/Atom}feed"
    assert root.find("a:title", NS).text == "测试 & 源 <2026>"
    items = root.findall("a:entry", NS)
    assert len(items) == 2
    first_link = items[0].find("a:link", NS).get("href")
    assert first_link == "https://www.bilibili.com/video/BV1rss001"
    author = items[0].find("a:author/a:name", NS).text
    assert author == "RSS组内UP"
    published = items[0].find("a:published", NS).text
    assert published.endswith("Z") and "T" in published
