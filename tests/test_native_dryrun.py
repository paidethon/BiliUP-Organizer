"""Native-group dry runs and push gating.

A dry run must never issue a remote write (tag create/delete, member add/move)
nor create a backup file; scheduled pushes stay off unless
sync.native_push_enabled is explicitly on, and "full" sync never pushes.
Managed-scope overwrite rebuilds ONLY tags mapped to local groups.
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
os.environ.setdefault("DATA_DIR", str(Path(tempfile.mkdtemp(prefix="biliup-native-"))))

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.models import (  # noqa: E402
    Base,
    BilibiliAccount,
    GroupLocal,
    GroupMember,
    NativeGroupMap,
    UpUser,
)
from app.services import native_sync  # noqa: E402
from app.services import sync as sync_service  # noqa: E402
from app.services.bilibili.client import API_BASE  # noqa: E402
from app.services.settings_store import update_section  # noqa: E402

FAKE_COOKIES = {"SESSDATA": "fake_sess", "bili_jct": "fake_jct", "DedeUserID": "42"}

TAGS_DATA = [
    {"tagid": 1, "name": "科技数码", "count": 1, "tip": ""},
    {"tagid": 2, "name": "旧标签", "count": 1, "tip": ""},  # not mapped to any local group
]


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "message": "0", "data": data})


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
    session.add(BilibiliAccount(id=1, login_status="active", cookie_json=json.dumps(FAKE_COOKIES)))
    tech = GroupLocal(name="科技数码")
    media = GroupLocal(name="影视创作")
    game = GroupLocal(name="游戏")
    session.add_all([tech, media, game])
    session.flush()
    for mid in (101, 102):
        session.add(UpUser(mid=mid, uname=f"UP{mid}", group_id=tech.id))
        session.add(GroupMember(up_mid=mid, group_id=tech.id))
    session.add(UpUser(mid=201, uname="UP201"))  # no membership -> skipped
    # 科技数码's local group is mapped to remote tag 1 (managed scope)
    session.add(NativeGroupMap(bili_tag_id=1, bili_tag_name="科技数码", local_group_id=tech.id))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _mock_read_routes() -> dict[str, respx.Route]:
    return {
        "tags": respx.get(f"{API_BASE}/x/relation/tags").mock(return_value=envelope(TAGS_DATA)),
        # correct member-read path: GET /x/relation/tag with a plain array body
        "users": respx.get(f"{API_BASE}/x/relation/tag").mock(
            return_value=envelope([{"mid": 101, "uname": "UP101"}])
        ),
        "user_tags": respx.get(f"{API_BASE}/x/relation/tag/user").mock(
            return_value=envelope({"1": "科技数码"})
        ),
    }


def _mock_write_routes() -> dict[str, respx.Route]:
    counter = {"tagid": 8}

    def _create(request: httpx.Request) -> httpx.Response:
        counter["tagid"] += 1
        return envelope({"tagid": counter["tagid"]})

    return {
        "create": respx.post(f"{API_BASE}/x/relation/tag/create").mock(side_effect=_create),
        "delete": respx.post(f"{API_BASE}/x/relation/tag/del").mock(return_value=envelope({})),
        "add": respx.post(f"{API_BASE}/x/relation/tags/addUsers").mock(return_value=envelope({})),
        "move": respx.post(f"{API_BASE}/x/relation/tags/moveUsers").mock(return_value=envelope({})),
    }


@respx.mock
def test_plan_overwrite_is_read_only(db: Session) -> None:
    _mock_read_routes()
    writes = _mock_write_routes()

    plan = native_sync.plan_overwrite(db)

    assert plan["mode"] == "overwrite" and plan["dry_run"] is True
    assert plan["scope"] == "managed_tags_only"
    assert plan["managed_tags"] == {"科技数码": 1}
    assert plan["protected_remote_tags"] == ["旧标签"]  # unmapped remote tag survives
    assert plan["would_place"] >= 1
    for route in writes.values():
        assert not route.called


@respx.mock
def test_push_overwrite_dry_run_never_writes(db: Session) -> None:
    _mock_read_routes()
    writes = _mock_write_routes()

    plan = native_sync.push_overwrite(db, dry_run=True)

    assert plan["dry_run"] is True
    for route in writes.values():
        assert not route.called


@respx.mock
def test_push_incremental_dry_run_never_writes(db: Session) -> None:
    _mock_read_routes()
    writes = _mock_write_routes()

    plan = native_sync.push_incremental(db, dry_run=True)

    assert plan["mode"] == "append" and plan["dry_run"] is True
    for route in writes.values():
        assert not route.called


@respx.mock
def test_push_overwrite_real_run_writes_managed_scope_only(db: Session) -> None:
    reads = _mock_read_routes()
    writes = _mock_write_routes()

    result = native_sync.push_overwrite(db)

    assert result["mode"] == "overwrite"
    assert result["scope"] == "managed_tags_only"
    assert writes["delete"].called
    assert writes["create"].called
    assert writes["add"].called
    # only the mapped tag was deleted; the unmapped remote tag must survive
    deleted_bodies = [
        dict(pair.split("=", 1) for pair in c.request.content.decode().split("&"))
        for c in writes["delete"].calls
    ]
    assert {body["tagid"] for body in deleted_bodies} == {"1"}
    assert reads["tags"].called


@respx.mock
def test_backup_precedes_delete_and_aborts_when_incomplete(db: Session) -> None:
    """Backup completes BEFORE any write; a failed member read aborts writes."""
    backups_dir = Path(get_settings().data_dir) / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    for stale in backups_dir.glob("*"):
        stale.unlink()
    reads = _mock_read_routes()
    writes = _mock_write_routes()
    # tag member read for tag 1 fails -> backup incomplete -> must abort
    reads["users"].mock(side_effect=httpx.ConnectError("boom"))

    result = native_sync.push_overwrite(db)

    assert result.get("aborted") == "backup_incomplete"
    assert not writes["delete"].called
    assert not writes["add"].called
    backups = list(backups_dir.glob("*"))
    assert len(backups) == 1  # the (partial, flagged incomplete) snapshot file
    assert json.loads(backups[0].read_text())["complete"] is False


@respx.mock
def test_full_sync_does_not_push(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: list[bool] = []
    monkeypatch.setattr(sync_service, "run_followings_sync", lambda db: {"total": 0})
    monkeypatch.setattr(sync_service, "refresh_archives", lambda db: 0)
    monkeypatch.setattr(sync_service, "run_watch_history_sync", lambda db: {"fetched": 0})

    def _fail_push(db):  # noqa: ANN001
        pushed.append(True)
        raise AssertionError("full sync must not push native groups")

    monkeypatch.setattr(native_sync, "push_overwrite", _fail_push)
    monkeypatch.setattr(native_sync, "push", _fail_push)
    stats = sync_service.run_sync_kind(db, "full")
    assert pushed == []
    assert "native" not in stats


@respx.mock
def test_native_incremental_gated_by_setting(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native_sync, "push_incremental", lambda *a, **k: {"mode": "append"})

    skipped = sync_service.run_sync_kind(db, "native_incremental")
    assert skipped == {"skipped": "native_push_disabled"}

    update_section(db, "sync", {"native_push_enabled": True})
    pushed = sync_service.run_sync_kind(db, "native_incremental")
    assert pushed == {"mode": "append"}


@respx.mock
def test_dry_run_endpoint_previews(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """API surface: push-overwrite accepts dry_run without body-compat break."""
    from fastapi.testclient import TestClient

    from app.main import app

    plan_calls: list[bool] = []
    monkeypatch.setattr(
        native_sync,
        "plan_overwrite",
        lambda db: plan_calls.append(True) or {"mode": "overwrite", "dry_run": True, "notes": ["demo 预览"]},
    )
    with TestClient(app) as client:  # demo mode short-circuits at the route
        login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "demo"})
        assert login.status_code == 200
        csrf = client.cookies.get("biliup_csrf")
        client.headers.update({"X-CSRF-Token": csrf})
        res = client.post(
            "/api/v1/bilibili/native-groups/push-overwrite",
            json={"dry_run": True},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["mode"] == "overwrite" and body["dry_run"] is True
