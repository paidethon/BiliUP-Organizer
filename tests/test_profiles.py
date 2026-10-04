"""UP display-name resolution and the bounded profile cache (T7).

Pinned here: resolution priority (followed name first, cached profile as gap
filler, newest watch_authors snapshot last), the no-erase rules of
upsert_profile (empty names and mid placeholders never overwrite, face is
never wiped), the bounded/negative-cached userinfo backfill prioritized by
watch count, big-mid (> 2^31) safety, snapshot_authors behavior, and the
never-network guarantee when logged out. Upstream card lookups are respx
mocks; no request ever leaves the process.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-profiles-")))

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.models import Base, BilibiliAccount, UpProfile, UpUser, WatchAuthor  # noqa: E402
from app.services import up_profiles  # noqa: E402
from app.services.bilibili.client import API_BASE  # noqa: E402
from app.util import utcnow  # noqa: E402

FAKE_COOKIES = {"SESSDATA": "fake_sess", "bili_jct": "fake_jct", "DedeUserID": "42"}


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "message": "0", "data": data})


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.bilibili.client import BiliClient

    monkeypatch.setattr(BiliClient, "_throttle", lambda self: None)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def login(db: Session) -> None:
    db.add(BilibiliAccount(id=1, login_status="active", cookie_json=json.dumps(FAKE_COOKIES)))
    db.commit()


# --------------------------------------------------------- resolution priority


def test_resolve_names_followed_then_profile_then_snapshot(db: Session) -> None:
    # followed name and cached profile both present -> followed data wins
    db.add(UpUser(mid=101, uname="关注名"))
    db.add(UpProfile(mid=101, uname="缓存名", source="userinfo"))
    # empty followed uname -> the cached profile fills the gap
    db.add(UpUser(mid=102, uname=""))
    db.add(UpProfile(mid=102, uname="缓存名B", source="userinfo"))
    # neither followed nor profile -> newest history snapshot (higher history_id)
    db.add(WatchAuthor(history_id=3, author_mid=103, author_name="旧快照名"))
    db.add(WatchAuthor(history_id=7, author_mid=103, author_name="新快照名"))
    db.commit()

    names = up_profiles.resolve_names(db, [101, 102, 103, 999])

    assert names[101].name == "关注名" and names[101].source == "followed"
    assert names[102].name == "缓存名B" and names[102].source == "profile"
    assert names[103].name == "新快照名" and names[103].source == "snapshot"
    # unknown mids resolve to an explicit "not known" instead of blowing up
    assert names[999].name is None and names[999].source is None
    assert names[999].known is False


def test_snapshot_only_mid_with_empty_newest_name_resolves_nothing(db: Session) -> None:
    """The newest snapshot per mid wins; an empty newest name is not garbage
    that hides the fact we simply do not know the name."""
    db.add(WatchAuthor(history_id=11, author_mid=110, author_name="只有旧快照"))
    db.add(WatchAuthor(history_id=12, author_mid=110, author_name=None))
    db.commit()

    names = up_profiles.resolve_names(db, [110])
    # newest snapshot (history_id=12) has no name -> no name, never the stale one
    assert names[110].name is None


# --------------------------------------------------------------- upsert rules


def test_upsert_profile_never_erases_valid_name_or_face(db: Session) -> None:
    up_profiles.upsert_profile(db, 201, "原始名", "http://face/1", "history")
    db.commit()

    up_profiles.upsert_profile(db, 201, None, None, "userinfo")
    up_profiles.upsert_profile(db, 201, "", "http://face/2", "userinfo")
    db.commit()

    row = db.get(UpProfile, 201)
    assert row.uname == "原始名"  # empty names never overwrite
    assert row.face == "http://face/1"  # existing face never erased

    # a face fills in only when missing
    db.add(UpProfile(mid=202, uname="已有名", face=None, source="history"))
    db.commit()
    up_profiles.upsert_profile(db, 202, None, "http://face/x", "userinfo")
    db.commit()
    filled = db.get(UpProfile, 202)
    assert filled.uname == "已有名" and filled.face == "http://face/x"


def test_upsert_profile_rejects_placeholder_names(db: Session) -> None:
    up_profiles.upsert_profile(db, 203, "mid:203", None, "history")
    up_profiles.upsert_profile(db, 204, "204", None, "history")
    up_profiles.upsert_profile(db, 205, "  真名字  ", None, "history")
    db.commit()

    assert db.get(UpProfile, 203).uname is None  # "mid:<mid>" placeholder
    assert db.get(UpProfile, 204).uname is None  # bare mid string placeholder
    assert db.get(UpProfile, 205).uname == "真名字"  # real names are kept (and stripped)


# ------------------------------------------------------------ bounded backfill


@respx.mock
def test_backfill_respects_max_ups_priority_and_negative_cache(db: Session) -> None:
    login(db)
    # watch counts via author snapshots: 301 x3, 302 x2, 303 x1, 304 x2, 305 x2
    for history_id, mid in [
        (1, 301),
        (2, 301),
        (3, 301),
        (4, 302),
        (5, 302),
        (6, 303),
        (7, 304),
        (8, 304),
        (9, 305),
        (10, 305),
    ]:
        db.add(WatchAuthor(history_id=history_id, author_mid=mid, author_name=None))
    db.add(UpProfile(mid=304, uname=None, attempts=3, last_attempt_at=None))  # too many attempts
    db.add(UpProfile(mid=305, uname=None, attempts=1, last_attempt_at=utcnow()))  # attempted recently
    db.commit()

    card_route = respx.get(f"{API_BASE}/x/web-interface/card").mock(
        return_value=envelope({"card": {"name": "名字", "face": "http://x/y.jpg"}})
    )

    result = up_profiles.backfill_missing_profiles(db, max_ups=2)

    assert result["looked_up"] == 2
    # queue is watch-count ordered and stops at max_ups: 301 (x3) then 302 (x2);
    # 303 (x1) is beyond the bound, 304/305 are negative-cached out
    asked = [int(call.request.url.params["mid"]) for call in card_route.calls]
    assert asked == [301, 302]
    assert result["remaining"] == 3

    for mid in (301, 302):
        row = db.get(UpProfile, mid)
        assert row.uname == "名字"
        assert row.face == "http://x/y.jpg"
        assert row.source == "userinfo"
        assert row.attempts == 1  # attempts incremented for the negative cache
        assert row.last_attempt_at is not None
    assert db.get(UpProfile, 303) is None  # untouched by the bound


# ------------------------------------------------------------- big-mid safety


def test_big_mid_survives_upsert_resolve_and_json(db: Session) -> None:
    big = 3_500_000_000  # > 2^31, fits SQLite INTEGER

    up_profiles.upsert_profile(db, big, "大MIDUP", "http://face/big", "userinfo")
    db.commit()

    row = db.get(UpProfile, big)
    assert row is not None and row.uname == "大MIDUP" and row.face == "http://face/big"

    names = up_profiles.resolve_names(db, [big, 1])
    # resolution reports the logical source "profile" for cached rows
    assert names[big].name == "大MIDUP" and names[big].source == "profile"
    assert names[1].name is None

    # JSON serialization keeps python int precision (no float rounding)
    text = json.dumps({"mid": big})
    round_trip = json.loads(text)
    assert round_trip["mid"] == big and isinstance(round_trip["mid"], int)
    assert "3500000000" in text


# ------------------------------------------------------------ snapshot authors


def test_snapshot_authors_creates_updates_and_skips_garbage(db: Session) -> None:
    up_profiles.snapshot_authors(db, 50, 401, "快照名", "http://face/a")
    db.commit()

    snap = db.get(WatchAuthor, 50)
    assert snap.author_mid == 401 and snap.author_name == "快照名"
    profile = db.get(UpProfile, 401)
    assert profile.uname == "快照名" and profile.source == "history"

    # a second call for the same history row updates in place
    up_profiles.snapshot_authors(db, 50, 401, "改名了", None)
    db.commit()
    assert db.get(WatchAuthor, 50).author_name == "改名了"
    assert db.get(UpProfile, 401).uname == "改名了"

    # empty name AND no mid: nothing is created at all
    up_profiles.snapshot_authors(db, 51, None, "", None)
    db.commit()
    assert db.get(WatchAuthor, 51) is None

    # empty name with a known mid: authorship kept, no garbage name cached
    up_profiles.snapshot_authors(db, 52, 402, "", None)
    db.commit()
    assert db.get(WatchAuthor, 52).author_name is None
    assert db.get(UpProfile, 402).uname is None
    names = up_profiles.resolve_names(db, [402])
    assert names[402].name is None


# ---------------------------------------------------------- never-network rule


@respx.mock
def test_backfill_without_cookies_never_touches_network(db: Session) -> None:
    # an explicit logged-out account row (cookie_json None) -> falsy cookies
    db.add(BilibiliAccount(id=1, login_status="none", cookie_json=None))
    db.commit()
    result = up_profiles.backfill_missing_profiles(db, max_ups=5)
    assert result == {"skipped": "not_logged_in", "looked_up": 0}

    # no account row at all behaves the same (load_cookies fabricates an empty one)
    db.query(BilibiliAccount).delete(synchronize_session=False)
    db.commit()
    assert up_profiles.backfill_missing_profiles(db, max_ups=5)["skipped"] == "not_logged_in"
    # respx would raise AllMockedAssertionError on any attempt; be explicit too
    assert respx.calls.call_count == 0
