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
