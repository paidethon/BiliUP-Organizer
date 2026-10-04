"""Full-mode listing, bulk-by-query, undo, status labels and tag routing."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-followings-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.main import app  # noqa: E402
from app.schemas import STATUS_LABELS  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        res = c.post("/api/v1/auth/login", json={"username": "demo", "password": "demo"})
        assert res.status_code == 200
        csrf = c.cookies.get("biliup_csrf")
        assert csrf, "csrf cookie must be set at login"
        c.headers.update({"X-CSRF-Token": csrf})
        yield c


def _all_items(client: TestClient, **params) -> list[dict]:
    res = client.get("/api/v1/followings", params={"all": "true", **params})
    assert res.status_code == 200
    return res.json()["items"]


def test_pagination_compatible(client: TestClient) -> None:
    body = client.get("/api/v1/followings", params={"page": 1, "page_size": 5}).json()
    assert body["page"] == 1 and body["page_size"] == 5
    assert len(body["items"]) == 5
    assert body["total"] >= 24  # the demo seed alone ships 24 UPs
    assert all("group_name" in item and "groups" in item for item in body["items"])

    page2 = client.get("/api/v1/followings", params={"page": 2, "page_size": 5}).json()
    mids1 = {item["mid"] for item in body["items"]}
    mids2 = {item["mid"] for item in page2["items"]}
    assert page2["page"] == 2
    assert not mids1 & mids2


def test_all_mode_returns_everything(client: TestClient) -> None:
    res = client.get("/api/v1/followings", params={"all": "true"})
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 1
    assert body["page_size"] == body["total"]
    assert len(body["items"]) == body["total"]
    assert body["total"] >= 24

    paged = client.get("/api/v1/followings", params={"page_size": 200}).json()
    assert {item["mid"] for item in paged["items"]} <= {item["mid"] for item in body["items"]}


def test_all_mode_with_filters(client: TestClient) -> None:
    everything = _all_items(client)

    never = client.get("/api/v1/followings", params={"all": "true", "flag": "never"}).json()
    expect_never = {item["mid"] for item in everything if item["watched_count"] == 0}
    assert {item["mid"] for item in never["items"]} == expect_never
    assert never["page_size"] == never["total"] == len(expect_never)
    assert len(expect_never) >= 3  # 吕永汉 / 早睡早起冠军 / 新关注的UP from the seed

    status_res = client.get("/api/v1/followings", params={"all": "true", "status": "吃灰"}).json()
    expect_status = {item["mid"] for item in everything if "吃灰" in item["status_labels"]}
    assert {item["mid"] for item in status_res["items"]} == expect_status
    assert len(expect_status) >= 2

    ungrouped = client.get("/api/v1/followings", params={"all": "true", "group_id": "none"}).json()
    expect_none = {item["mid"] for item in everything if item["group_id"] is None}
    assert {item["mid"] for item in ungrouped["items"]} == expect_none
    assert all(item["group_id"] is None and not item["groups"] for item in ungrouped["items"])

    q_res = client.get("/api/v1/followings", params={"all": "true", "q": "罗翔"}).json()
    assert [item["uname"] for item in q_res["items"]] == ["罗翔说刑法"]

    combined = client.get(
        "/api/v1/followings",
        params={"all": "true", "flag": "never", "status": "吃灰", "group_id": "none"},
    ).json()
    expect_combined = {
        item["mid"]
        for item in everything
        if item["watched_count"] == 0 and "吃灰" in item["status_labels"] and item["group_id"] is None
    }
    assert {item["mid"] for item in combined["items"]} == expect_combined
    assert len(expect_combined) == 2  # exactly the two 吃灰 seed UPs, both ungrouped


def test_zero_and_single_result(client: TestClient) -> None:
    empty = client.get("/api/v1/followings", params={"all": "true", "q": "绝不存在的UP名称xyz"}).json()
    assert empty["items"] == []
    assert empty["total"] == 0
    assert empty["page"] == 1 and empty["page_size"] == 0

    single = client.get("/api/v1/followings", params={"all": "true", "q": "法外狂徒张三"}).json()
    assert single["total"] == 1 and len(single["items"]) == 1


def test_sort_with_all_mode(client: TestClient) -> None:
    body = client.get("/api/v1/followings", params={"all": "true", "sort": "name", "order": "asc"}).json()
    unames = [item["uname"] for item in body["items"]]
    assert unames == sorted(unames)

    watched = client.get(
        "/api/v1/followings", params={"all": "true", "sort": "last_watched", "order": "desc"}
    ).json()
    stamps = [item["last_watched_at"] for item in watched["items"]]
    if None in stamps:
        first_null = stamps.index(None)
        assert all(t is None for t in stamps[first_null:])  # nulls last
        non_null = stamps[:first_null]
    else:
        non_null = stamps
    assert non_null == sorted(non_null, reverse=True)

    assert client.get("/api/v1/followings", params={"sort": "bogus"}).status_code == 400
    assert client.get("/api/v1/followings", params={"order": "sideways"}).status_code == 400
    assert client.get("/api/v1/followings", params={"status": "不存在的状态"}).status_code == 400
    assert client.get("/api/v1/followings", params={"tag_id": "abc"}).status_code == 400


def test_status_counts_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/followings/statuses")
    assert res.status_code == 200
    labels = {item["label"]: item["count"] for item in res.json()["labels"]}
    assert set(labels) <= set(STATUS_LABELS)
    assert labels.get("吃灰") == 2  # 吕永汉 + 早睡早起冠军, only set by the demo seed
    assert labels.get("新关注") == 1

    detail = client.get(f"/api/v1/followings/{_all_items(client, q='吕永汉')[0]['mid']}").json()["up"]
    assert sorted(detail["status_labels"]) == ["吃灰", "待整理"]


def test_bulk_by_query_with_undo(client: TestClient) -> None:
    never_mids = [item["mid"] for item in _all_items(client, flag="never")]
    assert len(never_mids) >= 2
    exclude = [never_mids[0]]

    add_res = client.post(
        "/api/v1/followings/bulk",
        json={
            "query": {"flag": "never"},
            "exclude_mids": exclude,
            "action": "add_tags",
            "params": {"tags": ["批量测试标签"]},
        },
    )
    assert add_res.status_code == 200
    add_body = add_res.json()
    assert add_body["changed"] == len(never_mids) - 1
    assert add_body["undo_id"] is not None
    add_undo = add_body["undo_id"]

    excluded_tags = client.get(f"/api/v1/followings/{exclude[0]}").json()["up"]["tags"]
    assert all(tag["name"] != "批量测试标签" for tag in excluded_tags)

    status_res = client.post(
        "/api/v1/followings/bulk",
        json={"query": {"flag": "never"}, "action": "set_status", "params": {"labels": ["重点关注"]}},
    )
    assert status_res.status_code == 200
    status_body = status_res.json()
    assert status_body["changed"] == len(never_mids)
    assert status_body["undo_id"] is not None
    status_undo = status_body["undo_id"]

    for mid in never_mids[1:]:
        up = client.get(f"/api/v1/followings/{mid}").json()["up"]
        assert any(tag["name"] == "批量测试标签" for tag in up["tags"])
        assert "重点关注" in up["status_labels"]

    undone_status = client.post(f"/api/v1/followings/undo/{status_undo}")
    assert undone_status.status_code == 200
    assert undone_status.json()["restored"] == len(never_mids)
    undone_tags = client.post(f"/api/v1/followings/undo/{add_undo}")
    assert undone_tags.status_code == 200

    for mid in never_mids:
        up = client.get(f"/api/v1/followings/{mid}").json()["up"]
        assert all(tag["name"] != "批量测试标签" for tag in up["tags"])
        assert "重点关注" not in up["status_labels"]


def test_bulk_undo_restores_exact_state(client: TestClient) -> None:
    listing = _all_items(client, q="稚晖君")
    assert len(listing) == 1
    mid = listing[0]["mid"]
    before = client.get(f"/api/v1/followings/{mid}").json()["up"]
    assert before["tags"], "seed UP 稚晖君 must carry content tags"

    gid = client.post("/api/v1/groups", json={"name": "撤销验证组"}).json()["id"]
    set_group_undo = client.post(
        "/api/v1/followings/bulk",
        json={"mids": [mid], "action": "set_group", "params": {"group_id": gid}},
    ).json()["undo_id"]
    assert set_group_undo is not None

    add_undo = client.post(
        "/api/v1/followings/bulk",
        json={"mids": [mid], "action": "add_tags", "params": {"tags": ["撤销标签A", "撤销标签B"]}},
    ).json()["undo_id"]

    removed_tag = before["tags"][0]["name"]
    rm_undo = client.post(
        "/api/v1/followings/bulk",
        json={"mids": [mid], "action": "remove_tags", "params": {"tags": [removed_tag]}},
    ).json()["undo_id"]

    status_undo = client.post(
        "/api/v1/followings/bulk",
        json={"mids": [mid], "action": "set_status", "params": {"labels": ["吃灰"]}},
    ).json()["undo_id"]

    moved = client.get(f"/api/v1/followings/{mid}").json()["up"]
    assert moved["group_id"] == gid  # primary re-pointed
    # set_group adds a membership; pre-existing ones stay
    assert set(g["id"] for g in moved["groups"]) == {g["id"] for g in before["groups"]} | {gid}
    assert "吃灰" in moved["status_labels"]
    assert all(tag["name"] != removed_tag for tag in moved["tags"])
    assert {"撤销标签A", "撤销标签B"} <= {tag["name"] for tag in moved["tags"]}

    for undo_id in (status_undo, rm_undo, add_undo, set_group_undo):
        res = client.post(f"/api/v1/followings/undo/{undo_id}")
        assert res.status_code == 200
        assert res.json() == {"ok": True, "restored": 1}
        assert client.post(f"/api/v1/followings/undo/{undo_id}").status_code == 400

    after = client.get(f"/api/v1/followings/{mid}").json()["up"]
    assert after["group_id"] == before["group_id"]
    assert [g["id"] for g in after["groups"]] == [g["id"] for g in before["groups"]]
    assert [tag["name"] for tag in after["tags"]] == [tag["name"] for tag in before["tags"]]
    assert sorted(after["status_labels"]) == sorted(before["status_labels"])


def test_native_move_demo_has_no_undo(client: TestClient) -> None:
    mids = [item["mid"] for item in client.get("/api/v1/followings", params={"page_size": 3}).json()["items"]]
    res = client.post(
        "/api/v1/followings/bulk",
        json={"mids": mids, "action": "native_move", "params": {"tag_id": 1}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["changed"] == len(mids)
    assert body["undo_id"] is None


def test_undo_list_and_execute_endpoints(client: TestClient) -> None:
    mid = client.get("/api/v1/followings", params={"page_size": 1}).json()["items"][0]["mid"]
    original = client.get(f"/api/v1/followings/{mid}").json()["up"]["snoozed_until"]
    res = client.post(
        "/api/v1/followings/bulk",
        json={"mids": [mid], "action": "snooze", "params": {"days": 3}},
    )
    undo_id = res.json()["undo_id"]
    assert undo_id is not None

    items = client.get("/api/v1/followings/undo").json()["items"]
    mine = [item for item in items if item["id"] == undo_id]
    assert len(mine) == 1
    record = mine[0]
    assert record["action"] == "snooze"
    assert record["status"] == "active"
    assert record["item_count"] == 1
    assert record["summary"]
    assert record["expires_at"] >= record["created_at"]

    executed = client.post(f"/api/v1/followings/undo/{undo_id}")
    assert executed.status_code == 200
    assert executed.json() == {"ok": True, "restored": 1}
    after = client.get(f"/api/v1/followings/{mid}").json()["up"]
    assert after["snoozed_until"] == original is None

    remaining = client.get("/api/v1/followings/undo").json()["items"]
    assert all(item["id"] != undo_id for item in remaining)
    assert client.post(f"/api/v1/followings/undo/{undo_id}").status_code == 400
    assert client.post("/api/v1/followings/undo/999999999").status_code == 404


def test_bulk_validation(client: TestClient) -> None:
    # neither mids nor query
    assert client.post("/api/v1/followings/bulk", json={"action": "snooze"}).status_code == 400
    # unknown action
    assert client.post("/api/v1/followings/bulk", json={"action": "bogus", "mids": [1]}).status_code == 400
    # over the mid cap
    too_many = client.post("/api/v1/followings/bulk", json={"action": "snooze", "mids": list(range(10001))})
    assert too_many.status_code == 400
    # invalid status label
    mid = client.get("/api/v1/followings", params={"page_size": 1}).json()["items"][0]["mid"]
    assert (
        client.post(
            "/api/v1/followings/bulk",
            json={"mids": [mid], "action": "set_status", "params": {"labels": ["不存在的状态"]}},
        ).status_code
        == 400
    )
    # invalid query sort
    assert (
        client.post(
            "/api/v1/followings/bulk", json={"query": {"sort": "bogus"}, "action": "snooze"}
        ).status_code
        == 400
    )
    # query with no hits -> a plain no-op, not an error
    no_hit = client.post(
        "/api/v1/followings/bulk", json={"query": {"q": "绝不存在的UPxyz"}, "action": "snooze"}
    )
    assert no_hit.status_code == 200 and no_hit.json()["changed"] == 0


def test_tags_crud_and_followings_filter(client: TestClient) -> None:
    created = client.post("/api/v1/tags", json={"name": "测试标签甲", "color": "#123456"})
    assert created.status_code == 200
    tag = created.json()
    assert tag["up_count"] == 0

    assert client.post("/api/v1/tags", json={"name": "测试标签甲"}).status_code == 400

    mid = client.get("/api/v1/followings", params={"page_size": 1}).json()["items"][0]["mid"]
    attached = client.post(
        "/api/v1/followings/bulk",
        json={"mids": [mid], "action": "add_tags", "params": {"tags": ["测试标签甲"]}},
    )
    assert attached.status_code == 200

    listed = client.get("/api/v1/tags").json()
    mine = next(t for t in listed if t["id"] == tag["id"])
    assert mine["up_count"] == 1 and mine["color"] == "#123456"

    filtered = client.get("/api/v1/followings", params={"tag_id": str(tag["id"]), "all": "true"}).json()
    assert {item["mid"] for item in filtered["items"]} == {mid}

    patched = client.patch(f"/api/v1/tags/{tag['id']}", json={"name": "测试标签乙"})
    assert patched.status_code == 200 and patched.json()["name"] == "测试标签乙"
    # renaming onto an existing demo tag is rejected
    assert client.patch(f"/api/v1/tags/{tag['id']}", json={"name": "数码"}).status_code == 400

    assert client.delete(f"/api/v1/tags/{tag['id']}").json() == {"ok": True}
    assert client.delete(f"/api/v1/tags/{tag['id']}").status_code == 404
    up_tags = client.get(f"/api/v1/followings/{mid}").json()["up"]["tags"]
    assert all(t["name"] != "测试标签乙" for t in up_tags)


def test_groups_merge_similar_aliases(client: TestClient) -> None:
    gid_a = client.post("/api/v1/groups", json={"name": "合并源组"}).json()["id"]
    gid_b = client.post("/api/v1/groups", json={"name": "合并目标组"}).json()["id"]
    mid = client.get("/api/v1/followings", params={"page_size": 1}).json()["items"][0]["mid"]
    client.post(
        "/api/v1/followings/bulk",
        json={"mids": [mid], "action": "set_group", "params": {"group_id": gid_a}},
    )

    client.post(f"/api/v1/groups/{gid_a}/aliases", json={"alias": "源组别名"})
    client.post(f"/api/v1/groups/{gid_a}/aliases", json={"alias": "源组别名"})  # deduped no-op
    groups = client.get("/api/v1/groups").json()
    source = next(g for g in groups if g["id"] == gid_a)
    assert source["aliases"].count("源组别名") == 1

    # 合并源组区 normalizes to 合并源组 (suffix 区 stripped) -> similar-name cluster
    client.post("/api/v1/groups", json={"name": "合并源组区"})
    clusters = client.get("/api/v1/groups/similar").json()["clusters"]
    hit = [c for c in clusters if "合并源组" in c["names"]]
    assert hit and "合并源组区" in hit[0]["names"]

    assert client.post(f"/api/v1/groups/{gid_a}/merge", json={"into_id": gid_a}).status_code == 400
    assert client.post(f"/api/v1/groups/{gid_a}/merge", json={"into_id": 987654321}).status_code == 404

    merged = client.post(f"/api/v1/groups/{gid_a}/merge", json={"into_id": gid_b})
    assert merged.status_code == 200
    body = merged.json()
    assert body["ok"] is True and body["moved"] == 1 and body["undo_id"]
    # after the merge the source's alias and source-name alias live on the target
    target_after = next(g for g in client.get("/api/v1/groups").json() if g["id"] == gid_b)
    assert "源组别名" in target_after["aliases"] and "合并源组" in target_after["aliases"]
    assert mid not in [
        item["mid"]
        for item in client.get("/api/v1/followings", params={"all": "true", "group_id": "none"}).json()[
            "items"
        ]
    ]

    undo_items = client.get("/api/v1/followings/undo").json()["items"]
    merge_records = [item for item in undo_items if item["action"] == "group_merge"]
    assert merge_records and merge_records[0]["status"] == "active"
    restored = client.post(f"/api/v1/followings/undo/{merge_records[0]['id']}")
    assert restored.status_code == 200 and restored.json()["restored"] == 1

    groups_after_undo = client.get("/api/v1/groups").json()
    names = [g["name"] for g in groups_after_undo]
    assert "合并源组" in names
    # aliases move BACK to the restored source; target keeps none of them
    source_after = next(g for g in groups_after_undo if g["name"] == "合并源组")
    assert "源组别名" in source_after["aliases"]
    target_after_undo = next(g for g in groups_after_undo if g["id"] == gid_b)
    assert "源组别名" not in target_after_undo["aliases"] and "合并源组" not in target_after_undo["aliases"]
    up = client.get(f"/api/v1/followings/{mid}").json()["up"]
    assert up["group_name"] == "合并源组"

    # alias remove (Chinese path parameter) + missing alias -> 404
    client.post(f"/api/v1/groups/{gid_b}/aliases", json={"alias": "目标组别名"})
    assert client.delete(f"/api/v1/groups/{gid_b}/aliases/目标组别名").json() == {"ok": True}
    assert client.delete(f"/api/v1/groups/{gid_b}/aliases/目标组别名").status_code == 404

    assert client.delete(f"/api/v1/groups/{gid_b}").json() == {"ok": True}
