"""Tests for the sync orchestration service (app/services/sync.py).

All bilibili fetchers are monkeypatched with fakes: no network access happens.
Each test gets a fresh in-memory SQLite database built from app.models.Base.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
os.environ.setdefault("DATA_DIR", str(Path(tempfile.mkdtemp(prefix="biliup-sync-test-"))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.models import AppSetting, Base, BilibiliAccount, UpUser, WatchHistory  # noqa: E402
from app.services import sync as sync_service  # noqa: E402
from app.services.bilibili import followings as followings_module  # noqa: E402
from app.services.bilibili.errors import AuthExpiredError, RiskControlError  # noqa: E402


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_account(db: Session, logged_in: bool = True) -> BilibiliAccount:
    account = BilibiliAccount(
        id=1,
        login_status="active" if logged_in else "none",
        cookie_json=json.dumps({"SESSDATA": "s", "bili_jct": "j"}) if logged_in else None,
    )
    db.add(account)
    db.commit()
    return account


def make_up(db: Session, mid: int, **fields) -> UpUser:
    up = UpUser(mid=mid, uname=fields.pop("uname", f"UP {mid}"), **fields)
    db.add(up)
    db.commit()
    return up


def patch_fetch(monkeypatch: pytest.MonkeyPatch, name: str, result, calls: list[dict] | None = None):
    """Replace fetch_followings / fetch_history on the bilibili module.

    ``result`` is either the list to return or an exception instance to raise.
    fetch_history results are wrapped in the {"entries": [...], "truncated":
    bool} envelope the real fetcher returns. ``calls`` records (args, kwargs)
    of every invocation.
    """

    def fake(*args, **kwargs):
        if calls is not None:
            calls.append({"args": args, "kwargs": kwargs})
        if isinstance(result, Exception):
            raise result
        if name == "fetch_history":
            return {"entries": result, "truncated": False}
        return result

    monkeypatch.setattr(followings_module, name, fake)
    return fake


FOLLOWING_ROWS = [
    {
        "mid": 101,
        "uname": "UP甲",
        "sign": "签名甲",
        "face": "http://f/101",
        "official_type": 0,
        "special": True,
    },
    {"mid": 102, "uname": "UP乙", "sign": "", "face": "", "official_type": -1, "special": False},
]

HISTORY_ENTRIES = [
    {"bvid": "BV1h1", "title": "视频一", "author_mid": 101, "view_at": "2026-09-01 10:00:00", "progress": -1},
    {
        "bvid": "BV1h2",
        "title": "视频二",
        "author_mid": 101,
        "view_at": "2026-09-02 12:30:00",
        "progress": 120,
    },
    {
        "bvid": "BV1u1",
        "title": "未关注UP",
        "author_mid": 555,
        "view_at": "2026-09-03 08:00:00",
        "progress": 30,
    },
]


def test_followings_skips_without_cookie(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db, logged_in=False)
    calls: list[dict] = []
    patch_fetch(monkeypatch, "fetch_followings", [], calls)

    stats = sync_service.run_followings_sync(db)

    assert stats == {"skipped": "not_logged_in"}
    assert calls == []


def test_followings_inserts_updates_and_marks_missing(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    gone = make_up(db, 999, uname="跑路UP")
    here = make_up(db, 101, uname="旧名字", sign="旧签名", official_type=-1, special=False)
    patch_fetch(monkeypatch, "fetch_followings", FOLLOWING_ROWS)

    stats = sync_service.run_followings_sync(db)

    assert stats == {"total": 2, "new": 1, "updated": 1, "missing": 1}

    new_up = db.query(UpUser).filter(UpUser.mid == 102).one()
    assert new_up.uname == "UP乙"
    assert new_up.followed_at is not None
    assert new_up.ai_status == "none"
    assert new_up.last_seen_at is not None
    assert new_up.missing is False

    db.refresh(here)
    assert here.uname == "UP甲"
    assert here.sign == "签名甲"
    assert here.official_type == 0
    assert here.special is True
    assert here.missing is False
    assert here.last_seen_at is not None

    db.refresh(gone)
    assert gone.missing is True


def test_followings_marks_returning_up_present_again(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    up = make_up(db, 101, missing=True)
    patch_fetch(monkeypatch, "fetch_followings", [FOLLOWING_ROWS[0]])

    stats = sync_service.run_followings_sync(db)

    assert stats == {"total": 1, "new": 0, "updated": 1, "missing": 0}
    db.refresh(up)
    assert up.missing is False
    assert up.last_seen_at is not None


def test_followings_risk_control_sets_flag_and_reraises(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    patch_fetch(monkeypatch, "fetch_followings", RiskControlError(code=-412))

    with pytest.raises(RiskControlError):
        sync_service.run_followings_sync(db)

    account = db.get(BilibiliAccount, 1)
    assert account is not None
    assert account.risk_flag is True


def test_history_skips_without_cookie(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db, logged_in=False)
    calls: list[dict] = []
    patch_fetch(monkeypatch, "fetch_history", [], calls)

    stats = sync_service.run_watch_history_sync(db)

    assert stats == {"skipped": "not_logged_in"}
    assert calls == []


def test_history_upsert_idempotent_and_stats(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    up = make_up(db, 101)
    patch_fetch(monkeypatch, "fetch_history", HISTORY_ENTRIES)

    stats = sync_service.run_watch_history_sync(db)

    assert stats == {
        "fetched": 3,
        "new": 3,
        "ups_touched": 1,
        "history_truncated": False,
        "profiles_backfilled": 0,
    }
    assert db.query(WatchHistory).count() == 3
    db.refresh(up)
    assert up.last_watched_at == "2026-09-02 12:30:00"
    assert up.watched_count == 2  # distinct bvids of followed mid 101 only

    unknown = db.query(WatchHistory).filter(WatchHistory.bvid == "BV1u1").one()
    assert unknown.up_mid == 555  # stored as data, but never counted toward an up

    # identical second run: nothing new, stats stay stable
    stats2 = sync_service.run_watch_history_sync(db)
    assert stats2 == {
        "fetched": 3,
        "new": 0,
        "ups_touched": 1,
        "history_truncated": False,
        "profiles_backfilled": 0,
    }
    assert db.query(WatchHistory).count() == 3
    db.refresh(up)
    assert up.last_watched_at == "2026-09-02 12:30:00"
    assert up.watched_count == 2


def test_history_uses_sync_settings_max_pages(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    make_up(db, 101)
    db.add(AppSetting(key="section:sync", value=json.dumps({"history_max_pages": 7})))
    db.commit()
    calls: list[dict] = []
    patch_fetch(monkeypatch, "fetch_history", [], calls)

    stats = sync_service.run_watch_history_sync(db)

    assert stats == {
        "fetched": 0,
        "new": 0,
        "ups_touched": 0,
        "history_truncated": False,
        "profiles_backfilled": 0,
    }
    assert calls[0]["kwargs"].get("max_pages") == 7


def test_history_default_max_pages_is_five(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    calls: list[dict] = []
    patch_fetch(monkeypatch, "fetch_history", [], calls)

    sync_service.run_watch_history_sync(db)

    assert calls[0]["kwargs"].get("max_pages") == 5


def test_history_auth_expired_sets_login_status_and_reraises(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_account(db)
    patch_fetch(monkeypatch, "fetch_history", AuthExpiredError("session expired"))

    with pytest.raises(AuthExpiredError):
        sync_service.run_watch_history_sync(db)

    account = db.get(BilibiliAccount, 1)
    assert account is not None
    assert account.login_status == "expired"


def test_run_sync_kind_full_merges_stats(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    make_up(db, 101)
    patch_fetch(monkeypatch, "fetch_followings", FOLLOWING_ROWS)
    patch_fetch(monkeypatch, "fetch_history", HISTORY_ENTRIES)
    monkeypatch.setattr(sync_service, "refresh_archives", lambda _db: 2)
    import app.services.native_sync as native_sync_module

    def _fail_push(_db):  # noqa: ANN001
        raise AssertionError("full sync must not push native groups")

    monkeypatch.setattr(native_sync_module, "push_overwrite", _fail_push)

    stats = sync_service.run_sync_kind(db, "full")

    # followings keys stay unprefixed; history keys are namespaced because the
    # old flat merge let history["new"] clobber the followings "new".
    # Native pushes are decoupled: "full" never includes them.
    assert stats["total"] == 2
    assert stats["updated"] == 1
    assert stats["archives_refreshed"] == 2
    assert stats["history_fetched"] == 3
    assert stats["history_new"] == 3
    assert stats["ups_touched"] == 1
    assert stats["new"] == 1
    assert "native" not in stats

    with pytest.raises(ValueError):
        sync_service.run_sync_kind(db, "nope")


def test_history_window_days_passed_to_fetcher(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    make_account(db)
    calls: list[dict] = []
    patch_fetch(monkeypatch, "fetch_history", [], calls)
    sync_service.run_watch_history_sync(db)
    assert calls[0]["kwargs"].get("window_days") == 14
