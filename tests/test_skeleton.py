from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")

_tmp = Path(tempfile.mkdtemp(prefix="biliup-test-"))
os.environ.setdefault("DATA_DIR", str(_tmp))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        # login (demo mode accepts anything)
        res = c.post("/api/v1/auth/login", json={"username": "demo", "password": "demo"})
        assert res.status_code == 200
        csrf = c.cookies.get("biliup_csrf")
        assert csrf, "csrf cookie must be set at login"
        c.headers.update({"X-CSRF-Token": csrf})
        yield c


def test_healthz(client: TestClient) -> None:
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_readyz(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200


def test_auth_flow(client: TestClient) -> None:
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "demo"


def test_groups_crud(client: TestClient) -> None:
    created = client.post("/api/v1/groups", json={"name": "测试分组"})
    assert created.status_code == 200
    gid = created.json()["id"]
    assert created.json()["up_count"] == 0

    listed = client.get("/api/v1/groups")
    assert any(g["name"] == "测试分组" for g in listed.json())

    patched = client.patch(f"/api/v1/groups/{gid}", json={"description": "更新了"})
    assert patched.json()["description"] == "更新了"

    assert client.delete(f"/api/v1/groups/{gid}").status_code == 200


def test_demo_seeded_data(client: TestClient) -> None:
    followings = client.get("/api/v1/followings", params={"page_size": 100})
    assert followings.status_code == 200
    body = followings.json()
    assert body["total"] >= 20
    assert all("group_name" in item for item in body["items"])


def test_followings_filters(client: TestClient) -> None:
    never = client.get("/api/v1/followings", params={"flag": "never"})
    assert never.status_code == 200
    assert all(item["watched_count"] == 0 for item in never.json()["items"])

    ungrouped = client.get("/api/v1/followings", params={"group_id": "none"})
    assert ungrouped.status_code == 200
    assert all(item["group_id"] is None for item in ungrouped.json()["items"])


def test_bulk_set_group(client: TestClient) -> None:
    groups = client.post("/api/v1/groups", json={"name": "批量组"})
    gid = groups.json()["id"]
    listing = client.get("/api/v1/followings", params={"page_size": 5}).json()
    mids = [item["mid"] for item in listing["items"][:3]]
    res = client.post(
        "/api/v1/followings/bulk", json={"mids": mids, "action": "set_group", "params": {"group_id": gid}}
    )
    assert res.status_code == 200
    assert res.json()["changed"] == 3
    detail = client.get(f"/api/v1/followings/{mids[0]}")
    assert detail.json()["up"]["group_id"] == gid


def test_multi_group_membership(client: TestClient) -> None:
    """一个 UP 可同时出现在多个分组：add_to_group 追加成员关系且不覆盖已有分组，
    两组的筛选结果都包含该 UP，remove_from_group 只摘掉对应一组。"""
    from app.db import get_session_factory
    from app.models import UpUser

    db = get_session_factory()()
    up = UpUser(mid=99000000001, uname="多分组测试UP", followed_at="2030-01-01 00:00:00")
    db.add(up)
    db.commit()
    db.close()
    mid = up.mid
    try:
        gid_a = client.post("/api/v1/groups", json={"name": "多分组甲"}).json()["id"]
        gid_b = client.post("/api/v1/groups", json={"name": "多分组乙"}).json()["id"]

        added = client.post(
            "/api/v1/followings/bulk",
            json={"mids": [mid], "action": "add_to_group", "params": {"group_id": gid_a}},
        )
        assert added.json()["changed"] == 1
        second = client.post(
            "/api/v1/followings/bulk",
            json={"mids": [mid], "action": "add_to_group", "params": {"group_id": gid_b}},
        )
        assert second.json()["changed"] == 1

        detail = client.get(f"/api/v1/followings/{mid}").json()["up"]
        assert {g["id"] for g in detail["groups"]} == {gid_a, gid_b}
        assert detail["group_id"] == gid_a  # first membership became primary

        # the UP shows up under BOTH group filters
        in_a = client.get("/api/v1/followings", params={"group_id": str(gid_a), "page_size": 100}).json()
        in_b = client.get("/api/v1/followings", params={"group_id": str(gid_b), "page_size": 100}).json()
        assert mid in [item["mid"] for item in in_a["items"]]
        assert mid in [item["mid"] for item in in_b["items"]]

        removed = client.post(
            "/api/v1/followings/bulk",
            json={"mids": [mid], "action": "remove_from_group", "params": {"group_id": gid_a}},
        )
        assert removed.json()["changed"] == 1
        detail = client.get(f"/api/v1/followings/{mid}").json()["up"]
        assert [g["id"] for g in detail["groups"]] == [gid_b]
        assert detail["group_id"] == gid_b  # primary re-pointed to the remaining group
    finally:
        db = get_session_factory()()
        row = db.query(UpUser).filter(UpUser.mid == mid).first()
        if row is not None:
            db.delete(row)
            db.commit()
        db.close()


def test_reminders_list_and_ack(client: TestClient) -> None:
    reminders = client.get("/api/v1/reminders")
    assert reminders.status_code == 200
    body = reminders.json()
    assert len(body) >= 1
    rid = body[0]["id"]
    assert client.post(f"/api/v1/reminders/{rid}/ack").status_code == 200


def test_review_queue_demo(client: TestClient) -> None:
    queue = client.get("/api/v1/review/queue")
    assert queue.status_code == 200
    assert len(queue.json()) >= 1


def test_settings_roundtrip(client: TestClient) -> None:
    settings = client.get("/api/v1/settings")
    assert settings.status_code == 200
    body = settings.json()
    assert "ai" in body and "smtp" in body

    res = client.put("/api/v1/settings/reminders", json={"stale_days": 45})
    assert res.json()["stale_days"] == 45


def test_history_summary(client: TestClient) -> None:
    summary = client.get("/api/v1/history/summary")
    assert summary.status_code == 200
    assert summary.json()["total_entries"] >= 1


def test_weekly_preview_demo(client: TestClient) -> None:
    res = client.post("/api/v1/weekly-report/preview")
    assert res.status_code == 200
    assert "周报" in res.json()["html"]


def test_feed_public(client: TestClient) -> None:
    res = client.get("/feed/demo-feed-token")
    assert res.status_code == 200
    # demo feeds render via the feeds service; until implemented the route
    # returns 501-ish error envelope — tolerate both while scaffolding
    unknown = client.get("/feed/not-a-token")
    assert unknown.status_code == 404


def test_backups_create_and_list(client: TestClient) -> None:
    created = client.post("/api/v1/system/backups")
    assert created.status_code == 200
    listed = client.get("/api/v1/system/backups")
    assert any(b["filename"] == created.json()["filename"] for b in listed.json())


def test_csrf_required(client: TestClient) -> None:
    # fresh client without CSRF header/cookie handling: craft mismatched header
    csrf_cookie = None
    for cookie in client.cookies.jar:
        if cookie.name == "biliup_csrf":
            csrf_cookie = cookie.value
    assert csrf_cookie, "csrf cookie must be set at login"
    res = client.post("/api/v1/groups", json={"name": "无CSRF"}, headers={"X-CSRF-Token": "wrong"})
    assert res.status_code == 401


def test_audit_log_written(client: TestClient) -> None:
    client.post("/api/v1/groups", json={"name": "审计组"})
    logs = client.get("/api/v1/system/audit")
    assert logs.status_code == 200
    actions = [entry["action"] for entry in logs.json()]
    assert "groups.create" in actions
