"""Native multi-group pushes (T11/T12/T13) with respx-mocked upstream.

Member reads use GET /x/relation/tag (plain array, paginated), per-UP tag
reads use GET /x/relation/tag/user, writes go through
POST /x/relation/tags/{addUsers,moveUsers} with the documented form fields.
Multi-group algebra: append preserves unmanaged tags (target = R ∪ D),
replace clears only the managed scope (target = (R−M) ∪ D, empty target = 0),
identical target sets share one addUsers batch, every write is read back and
mismatches surface as verify failures. BiliError subclasses reach the API as
structured 502s with business codes and never leak cookie text.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
os.environ.setdefault("DATA_DIR", str(Path(tempfile.mkdtemp(prefix="biliup-multigroup-"))))

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
    WatchHistory,
)
from app.services import native_sync  # noqa: E402
from app.services import stats as stats_service  # noqa: E402
from app.services import sync as sync_service  # noqa: E402
from app.services.bilibili import native_groups  # noqa: E402
from app.services.bilibili.client import API_BASE  # noqa: E402
from app.services.bilibili.errors import (  # noqa: E402
    AccountCancelledError,
    AuthExpiredError,
    CsrfError,
    RiskControlError,
    UpstreamContractError,
    UpstreamHttpError,
    UpstreamParamError,
)
from app.services.settings_store import update_section  # noqa: E402

FAKE_COOKIES = {"SESSDATA": "fake_sess", "bili_jct": "fake_jct", "DedeUserID": "42"}
TAG1_NAME = "科技数码"
TAG2_NAME = "影视创作"


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "message": "0", "data": data})


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the 0.6s inter-request throttle; respx answers instantly anyway."""
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
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(BilibiliAccount(id=1, login_status="active", cookie_json=json.dumps(FAKE_COOKIES)))
    group_a = GroupLocal(name=TAG1_NAME)
    group_b = GroupLocal(name=TAG2_NAME)
    session.add_all([group_a, group_b])
    session.flush()
    # both local groups are mapped to managed native tags
    session.add(NativeGroupMap(bili_tag_id=1, bili_tag_name=TAG1_NAME, local_group_id=group_a.id))
    session.add(NativeGroupMap(bili_tag_id=2, bili_tag_name=TAG2_NAME, local_group_id=group_b.id))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _group_ids(db: Session) -> tuple[int, int]:
    rows = {g.name: int(g.id) for g in db.query(GroupLocal).all()}
    return rows[TAG1_NAME], rows[TAG2_NAME]


def make_up(db: Session, mid: int, group_ids: tuple[int, ...] = ()) -> None:
    db.add(UpUser(mid=mid, uname=f"UP{mid}"))
    for gid in group_ids:
        db.add(GroupMember(up_mid=mid, group_id=gid))
    db.flush()


def _form_body(request: httpx.Request) -> dict[str, str]:
    return dict(parse_qsl(request.content.decode()))


def _cancelled_envelope() -> httpx.Response:
    return httpx.Response(200, json={"code": 22013, "message": "账号已注销，无法完成操作", "data": None})


def _mock_push_world(
    members_by_tag: dict[int, list[int]],
    user_tags_before: dict[int, set[int]],
    user_tags_after: dict[int, set[int]] | None = None,
    cancelled_reads: set[int] | None = None,
    cancelled_writes: set[int] | None = None,
) -> dict[str, list]:
    """Read routes + addUsers capture. add_calls records only calls upstream
    ACCEPTED; rejected_add_calls records the fids of 22013-rejected ones.
    cancelled_reads/cancelled_writes model UPs whose account upstream answers
    22013 账号已注销 for per-UP tag reads / addUsers writes respectively."""
    world: dict[str, list] = {"add_calls": [], "rejected_add_calls": []}
    state = {"written": False}
    cancelled_reads = cancelled_reads or set()
    cancelled_writes = cancelled_writes or set()

    respx.get(f"{API_BASE}/x/relation/tags").mock(
        return_value=envelope(
            [
                {"tagid": 1, "name": TAG1_NAME, "count": len(members_by_tag.get(1, [])), "tip": ""},
                {"tagid": 2, "name": TAG2_NAME, "count": len(members_by_tag.get(2, [])), "tip": ""},
            ]
        )
    )

    def _tag_members(request: httpx.Request) -> httpx.Response:
        tag_id = int(request.url.params["tagid"])
        return envelope([{"mid": mid} for mid in members_by_tag.get(tag_id, [])])

    respx.get(f"{API_BASE}/x/relation/tag").mock(side_effect=_tag_members)

    def _user_tags(request: httpx.Request) -> httpx.Response:
        fid = int(request.url.params["fid"])
        if fid in cancelled_reads:
            return _cancelled_envelope()
        if state["written"] and user_tags_after is not None:
            tags = user_tags_after.get(fid, set())
        else:
            tags = user_tags_before.get(fid, set())
        return envelope({str(tag): f"tag{tag}" for tag in tags})

    respx.get(f"{API_BASE}/x/relation/tag/user").mock(side_effect=_user_tags)

    def _add_users(request: httpx.Request) -> httpx.Response:
        body = _form_body(request)
        if set(body["fids"].split(",")) & {str(mid) for mid in cancelled_writes}:
            world["rejected_add_calls"].append(body["fids"])
            return _cancelled_envelope()
        world["add_calls"].append(body)
        state["written"] = True
        return envelope({})

    respx.post(f"{API_BASE}/x/relation/tags/addUsers").mock(side_effect=_add_users)
    return world


# ---------------------------------------------- T11: member/tag read contract


@respx.mock
def test_list_tag_users_paginates_until_short_page(db: Session) -> None:
    route = respx.get(f"{API_BASE}/x/relation/tag").mock(
        side_effect=lambda request: envelope(
            [{"mid": 1000 + i} for i in range(50)]
            if int(request.url.params["pn"]) == 1
            else [{"mid": 2000}, {"mid": 2001}, {"mid": 2002}]
        )
    )

    mids, complete = native_groups.list_tag_users(db, 7)

    assert mids[0] == 1000 and mids[-1] == 2002 and len(mids) == 53
    assert complete is True  # a short page stops the pagination
    assert route.call_count == 2
    first = route.calls[0].request.url.params
    assert first["tagid"] == "7" and first["pn"] == "1" and first["ps"] == "50"
    assert route.calls[1].request.url.params["pn"] == "2"


@respx.mock
def test_list_tag_users_404_raises_upstream_http_error(db: Session) -> None:
    respx.get(f"{API_BASE}/x/relation/tag").mock(
        return_value=httpx.Response(404, json={"code": -404, "message": "啥都看不到"})
    )
    with pytest.raises(UpstreamHttpError):
        native_groups.list_tag_users(db, 7)


@respx.mock
def test_list_tag_users_tolerates_list_wrapped_payload(db: Session) -> None:
    respx.get(f"{API_BASE}/x/relation/tag").mock(return_value=envelope({"list": [{"mid": 9}]}))
    mids, complete = native_groups.list_tag_users(db, 7)
    assert mids == [9] and complete is True


@respx.mock
def test_list_tag_users_rejects_unexpected_shape(db: Session) -> None:
    respx.get(f"{API_BASE}/x/relation/tag").mock(return_value=envelope({"total": 3, "weird": True}))
    with pytest.raises(UpstreamContractError):
        native_groups.list_tag_users(db, 7)


@respx.mock
def test_list_tags_keeps_default_zero_and_negative_ids(db: Session) -> None:
    respx.get(f"{API_BASE}/x/relation/tags").mock(
        return_value=envelope(
            [
                {"tagid": 0, "name": "默认分组", "count": 1, "tip": ""},
                {"tagid": -10, "name": "特别关注", "count": 2, "tip": ""},
                {"tagid": 194111, "name": "自建组", "count": 3, "tip": ""},
            ]
        )
    )

    tags = native_groups.list_tags(db)

    assert {t["bili_tag_id"] for t in tags} == {0, -10, 194111}  # nothing dropped
    cached = {row.bili_tag_id for row in db.query(NativeGroupMap).all()}
    assert {0, -10, 194111} <= cached


@respx.mock
def test_user_tag_ids_parses_string_and_negative_keys(db: Session) -> None:
    route = respx.get(f"{API_BASE}/x/relation/tag/user").mock(
        return_value=envelope({"-10": "特别关注", "194111": "x"})
    )
    assert native_groups.user_tag_ids(db, 101) == {-10, 194111}
    assert route.calls.last.request.url.params["fid"] == "101"


@respx.mock
def test_move_users_posts_documented_fields_on_new_path(db: Session) -> None:
    new_route = respx.post(f"{API_BASE}/x/relation/tags/moveUsers").mock(return_value=envelope({}))
    old_route = respx.post(f"{API_BASE}/x/relation/moveUsers").mock(return_value=envelope({}))

    native_groups.move_users(db, [101, 102], before_tag_id=1, after_tag_id=2)

    assert new_route.called and not old_route.called  # the old path must stay dead
    assert _form_body(new_route.calls.last.request) == {
        "fids": "101,102",
        "beforeTagids": "1",
        "afterTagids": "2",
        "csrf": "fake_jct",
    }


@respx.mock
def test_set_users_tags_posts_comma_joined_fids_and_tagids(db: Session) -> None:
    route = respx.post(f"{API_BASE}/x/relation/tags/addUsers").mock(return_value=envelope({}))

    submitted = native_groups.set_users_tags(db, [101, 102], [1, 2, 5])

    assert submitted == 2
    assert _form_body(route.calls.last.request) == {
        "fids": "101,102",
        "tagids": "1,2,5",
        "csrf": "fake_jct",
    }


# ------------------------------------- T12: multi-group append/replace algebra


@respx.mock
def test_append_preserves_unmanaged_remote_group(db: Session) -> None:
    group_a, group_b = _group_ids(db)
    make_up(db, 301, (group_a, group_b))  # member of both -> desired tags {1, 2}
    world = _mock_push_world(
        members_by_tag={1: [], 2: []},
        user_tags_before={301: {5}},  # remotely also in an unmanaged tag 5
        user_tags_after={301: {1, 2, 5}},
    )

    result = native_sync.push(db, mode="append")

    # the FULL target set (managed + unmanaged) goes out in one addUsers call
    assert world["add_calls"] == [{"fids": "301", "tagids": "1,2,5", "csrf": "fake_jct"}]
    assert result["failed_ups"] == 0 and result["verify_failed_mids"] == []
    assert result["written_ups"] == 1 and result["verified_ups"] == 1


@respx.mock
def test_replace_drops_managed_membership_keeps_unmanaged(db: Session) -> None:
    group_a, group_b = _group_ids(db)
    make_up(db, 302, (group_b,))  # desired: tag 2 only
    world = _mock_push_world(
        members_by_tag={1: [302], 2: []},  # remotely still in managed tag 1
        user_tags_before={302: {1, 5}},
        user_tags_after={302: {2, 5}},
    )

    result = native_sync.push(db, mode="replace")

    # target = (R − M) ∪ D = ({1,5} − {1,2}) ∪ {2} = {2,5}
    assert world["add_calls"] == [{"fids": "302", "tagids": "2,5", "csrf": "fake_jct"}]
    assert result["verify_failed_mids"] == []


@respx.mock
def test_replace_with_empty_target_moves_to_default_tag(db: Session) -> None:
    db.add(UpUser(mid=303, uname="UP303"))  # followed, but in no local group
    db.flush()
    world = _mock_push_world(
        members_by_tag={1: [303], 2: []},  # remotely only in managed tag 1
        user_tags_before={303: {1}},
        user_tags_after={303: set()},  # after tagids=0 upstream omits everything
    )

    result = native_sync.push(db, mode="replace")

    assert world["add_calls"] == [{"fids": "303", "tagids": "0", "csrf": "fake_jct"}]
    assert result["verify_failed_mids"] == []


@respx.mock
def test_verify_mismatch_retries_then_reports_failure(db: Session) -> None:
    group_a, _group_b = _group_ids(db)
    make_up(db, 304, (group_a,))
    world = _mock_push_world(
        members_by_tag={1: [], 2: []},
        user_tags_before={304: {5}},  # read-back never converges
    )

    result = native_sync.push(db, mode="append")

    assert result["failed_ups"] == 1
    assert result["verify_failed_mids"] == [304]
    assert result["verified_ups"] == 0
    assert len(world["add_calls"]) == 2  # the initial write plus one verify retry


@respx.mock
def test_identical_target_sets_share_one_addusers_batch(db: Session) -> None:
    group_a, _group_b = _group_ids(db)
    make_up(db, 305, (group_a,))
    make_up(db, 306, (group_a,))
    world = _mock_push_world(
        members_by_tag={1: [], 2: []},
        user_tags_before={305: {5}, 306: {5}},
        user_tags_after={305: {1, 5}, 306: {1, 5}},
    )

    result = native_sync.push(db, mode="append")

    assert len(world["add_calls"]) == 1
    assert world["add_calls"][0] == {"fids": "305,306", "tagids": "1,5", "csrf": "fake_jct"}
    assert result["verify_failed_mids"] == []


@respx.mock
def test_different_target_sets_never_share_a_batch(db: Session) -> None:
    group_a, group_b = _group_ids(db)
    make_up(db, 307, (group_a,))
    make_up(db, 308, (group_b,))
    world = _mock_push_world(
        members_by_tag={1: [], 2: []},
        user_tags_before={307: {5}, 308: {6}},
        user_tags_after={307: {1, 5}, 308: {2, 6}},
    )

    result = native_sync.push(db, mode="append")

    assert len(world["add_calls"]) == 2
    bodies = {call["fids"]: call["tagids"] for call in world["add_calls"]}
    assert bodies == {"307": "1,5", "308": "2,6"}
    assert result["verify_failed_mids"] == []


@respx.mock
def test_push_skips_cancelled_account_detected_in_plan(db: Session) -> None:
    """22013 账号已注销: the UP stays in the following list and local groups,
    but upstream rejects every relation mutation for it — the push must skip
    the mid and succeed instead of failing the whole run."""
    group_a, _group_b = _group_ids(db)
    make_up(db, 401, (group_a,))
    world = _mock_push_world(
        members_by_tag={1: [], 2: []},
        user_tags_before={},
        user_tags_after={},
        cancelled_reads={401},
        cancelled_writes={401},
    )

    plan = native_sync.plan_push(db, mode="append")
    assert plan["skipped_cancelled"] == [401]
    assert plan["batches"] == []  # never enters a write batch

    result = native_sync.push(db, mode="append")
    assert world["add_calls"] == []  # nothing written for the cancelled mid
    assert world["rejected_add_calls"] == []
    assert result["written_ups"] == 0 and result["failed_ups"] == 0
    assert result["skipped_cancelled"] == 1
    assert result["skipped_cancelled_mids"] == [401]


@respx.mock
def test_batch_write_rejected_by_cancelled_mid_falls_back_per_up(db: Session) -> None:
    """The plan read succeeds but addUsers rejects the shared batch (mid 404's
    account is cancelled): fall back to one-by-one writes so 403 still
    converges and only 404 is skipped."""
    group_a, _group_b = _group_ids(db)
    make_up(db, 403, (group_a,))
    make_up(db, 404, (group_a,))  # same target set -> shares 403's batch
    world = _mock_push_world(
        members_by_tag={1: [], 2: []},
        user_tags_before={403: {5}, 404: {5}},
        user_tags_after={403: {1, 5}},
        cancelled_writes={404},
    )

    result = native_sync.push(db, mode="append")

    assert world["rejected_add_calls"] == ["403,404", "404"]  # batch + per-UP retry
    assert [call["fids"] for call in world["add_calls"]] == ["403"]  # per-UP retry
    assert result["written_ups"] == 1 and result["verified_ups"] == 1
    assert result["failed_ups"] == 0
    assert result["skipped_cancelled_mids"] == [404]


def test_multi_group_membership_does_not_inflate_stats(db: Session) -> None:
    """One record, one UP in TWO groups: non-exclusive by_group counts it under
    both; by_group_primary attributes it exactly once; totals stay at 1."""
    group_a, group_b = _group_ids(db)
    db.add(UpUser(mid=309, uname="双组UP", group_id=group_a))
    db.add(GroupMember(up_mid=309, group_id=group_a))
    db.add(GroupMember(up_mid=309, group_id=group_b))
    db.add(
        WatchHistory(
            bvid="BV1two",
            up_mid=309,
            title="t",
            view_at="2026-09-29 04:00:00",  # Shanghai 2026-09-29 12:00
            progress=-1,
            duration_seconds=300,
        )
    )
    db.commit()

    payload = stats_service.range_stats(db, date(2026, 9, 28), date(2026, 10, 5))

    assert payload["views"] == 1  # no JOIN inflation
    non_exclusive = {row["name"]: row["views"] for row in payload["by_group"]}
    assert non_exclusive == {TAG1_NAME: 1, TAG2_NAME: 1}
    primary = {row["name"]: row["views"] for row in payload["by_group_primary"]}
    assert primary == {TAG1_NAME: 1}
    assert sum(primary.values()) == 1


# --------------------------------------------------- T13: structured API errors


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (AuthExpiredError(), "bili_auth"),
        (CsrfError(), "bili_csrf"),
        (RiskControlError(), "bili_risk_control"),
        (UpstreamHttpError(404), "bili_http"),
        (UpstreamParamError(22105, "未关注"), "bili_param"),
        (AccountCancelledError(), "bili_cancelled"),
    ],
)
def test_bili_errors_surface_as_structured_502(monkeypatch: pytest.MonkeyPatch, exc, expected_code) -> None:  # noqa: ANN001
    from fastapi.testclient import TestClient

    from app.api import bilibili_routes as br
    from app.main import app

    real_settings = get_settings()
    # the route short-circuits in demo mode; bypass that to reach the service
    monkeypatch.setattr(br, "get_settings", lambda: real_settings.model_copy(update={"demo_mode": False}))

    def _boom(_db, mode="append"):  # noqa: ANN001, ANN202
        raise exc

    monkeypatch.setattr(native_sync, "plan_push", _boom)

    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "demo"})
        assert login.status_code == 200
        client.headers.update({"X-CSRF-Token": client.cookies.get("biliup_csrf")})

        res = client.post("/api/v1/bilibili/native-groups/push-plan", json={"mode": "append"})

    assert res.status_code == 502
    body = res.json()
    assert body["error"]["code"] == expected_code
    assert body["error"]["message"]
    # never leak cookie material in the error surface
    assert "SESSDATA" not in res.text
    assert "fake_sess" not in res.text and "fake_jct" not in res.text


def test_push_run_gated_by_native_push_enabled_setting(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    skipped = sync_service.run_sync_kind(db, "native_push")
    assert skipped == {"skipped": "native_push_disabled"}

    captured: dict[str, str] = {}

    def _fake_push(_db, mode="append", dry_run=False, run=None):  # noqa: ANN001, ANN202
        captured["mode"] = mode
        return {"mode": mode}

    monkeypatch.setattr(native_sync, "push", _fake_push)
    update_section(db, "sync", {"native_push_enabled": True})

    result = sync_service.run_sync_kind(db, "native_push", mode="append")
    assert result == {"mode": "append"}
    assert captured["mode"] == "append"


# --------------------------------------- stale mappings (tag deleted upstream)


def _mock_tags_deleted_world(
    live_tags: list[dict],
    user_tags_before: dict[int, set[int]],
    user_tags_after: dict[int, set[int]],
    created_log: list[str],
    deleted_log: list[str],
    add_log: list[dict],
):
    """Upstream world where a mapped tag was deleted outside the app:
    /x/relation/tags returns only the surviving tags; tag/create appends a
    fresh id; per-UP reads flip to user_tags_after once a write lands."""
    state = {"written": False, "next_id": 900}
    tags_state = {"list": [dict(t) for t in live_tags]}

    respx.get(f"{API_BASE}/x/relation/tags").mock(
        side_effect=lambda request: envelope([dict(t) for t in tags_state["list"]])
    )
    respx.get(f"{API_BASE}/x/relation/tag").mock(return_value=envelope([]))

    def _user_tags(request: httpx.Request) -> httpx.Response:
        fid = int(request.url.params["fid"])
        tags = user_tags_after.get(fid, set()) if state["written"] else user_tags_before.get(fid, set())
        return envelope({str(tag): f"tag{tag}" for tag in tags})

    respx.get(f"{API_BASE}/x/relation/tag/user").mock(side_effect=_user_tags)

    def _create(request: httpx.Request) -> httpx.Response:
        body = _form_body(request)
        created_log.append(body["tag"])
        tags_state["list"].append({"tagid": state["next_id"], "name": body["tag"], "count": 0, "tip": ""})
        state["next_id"] += 1
        return envelope({"tagid": state["next_id"] - 1})

    respx.post(f"{API_BASE}/x/relation/tag/create").mock(side_effect=_create)

    def _delete(request: httpx.Request) -> httpx.Response:
        deleted_log.append(_form_body(request)["tagid"])
        return envelope({})

    respx.post(f"{API_BASE}/x/relation/tag/del").mock(side_effect=_delete)

    def _add_users(request: httpx.Request) -> httpx.Response:
        body = _form_body(request)
        add_log.append(body)
        state["written"] = True
        return envelope({})

    respx.post(f"{API_BASE}/x/relation/tags/addUsers").mock(side_effect=_add_users)


@respx.mock
def test_plan_clears_stale_mapping(db: Session) -> None:
    """Mapped tag deleted upstream (e.g. manually on Bilibili): the previous
    behaviour crashed every plan with 22104 该分组不存在. Now the dead mapping
    is cleared and the plan surfaces it as unmapped (push will rebuild it)."""
    _group_a, _group_b = _group_ids(db)
    created: list[str] = []
    deleted: list[str] = []
    adds: list[dict] = []
    _mock_tags_deleted_world(
        live_tags=[{"tagid": 1, "name": TAG1_NAME, "count": 0, "tip": ""}],
        user_tags_before={},
        user_tags_after={},
        created_log=created,
        deleted_log=deleted,
        add_log=adds,
    )

    plan = native_sync.plan_push(db, mode="append")
    assert plan["stale_mappings_cleared"] == [TAG2_NAME]
    assert TAG2_NAME in plan["unmapped_local_groups"]
    assert created == []  # dry run: preview never creates tags


@respx.mock
def test_push_clears_stale_mapping_and_recreates_tag(db: Session) -> None:
    """Push after an upstream tag deletion: the tag is recreated from the
    LOCAL group name (never a stub) and members re-converge."""
    _group_a, group_b = _group_ids(db)
    make_up(db, 501, (group_b,))
    created: list[str] = []
    deleted: list[str] = []
    adds: list[dict] = []
    _mock_tags_deleted_world(
        live_tags=[{"tagid": 1, "name": TAG1_NAME, "count": 0, "tip": ""}],
        user_tags_before={},
        user_tags_after={501: {900}},
        created_log=created,
        deleted_log=deleted,
        add_log=adds,
    )

    result = native_sync.push(db, mode="append")

    assert created == [TAG2_NAME]  # rebuilt from the LOCAL name, never a stub
    assert deleted == []  # append mode never deletes
    mapping = db.query(NativeGroupMap).filter(NativeGroupMap.bili_tag_id == 900).one()
    assert mapping.local_group_id == group_b
    assert mapping.bili_tag_name == TAG2_NAME
    assert any(call["tagids"] == "900" and call["fids"] == "501" for call in adds)
    assert result["created_tags"] == 1
    assert result["stale_mappings_cleared"] == [TAG2_NAME]


@respx.mock
def test_overwrite_rebuilds_stale_group_without_deleting_missing_tag(db: Session) -> None:
    """Managed-scope rebuild with a stale mapping: only the LIVE tag is
    deleted upstream (the missing one must not trigger 22104), and the stale
    group's tag is still recreated and filled."""
    _group_a, group_b = _group_ids(db)
    make_up(db, 601, (group_b,))
    created: list[str] = []
    deleted: list[str] = []
    adds: list[dict] = []
    _mock_tags_deleted_world(
        live_tags=[{"tagid": 1, "name": TAG1_NAME, "count": 0, "tip": ""}],
        user_tags_before={},
        user_tags_after={601: {901}},
        created_log=created,
        deleted_log=deleted,
        add_log=adds,
    )

    result = native_sync.push_overwrite(db)

    assert deleted == ["1"]  # tag 2 (already gone upstream) is not deleted
    assert created == [TAG1_NAME, TAG2_NAME]  # the whole managed scope rebuilds
    mapping = db.query(NativeGroupMap).filter(NativeGroupMap.bili_tag_id == 901).one()
    assert mapping.local_group_id == group_b
    assert result["stale_mappings_cleared"] == [TAG2_NAME]
    assert any(call["tagids"] == "901" and call["fids"] == "601" for call in adds)


@respx.mock
def test_member_read_22104_race_is_tolerated(db: Session) -> None:
    """A tag deleted between the listing and the member read answers 22104 —
    its members fell back to the default tag, so an empty set is correct."""
    group_a, _group_b = _group_ids(db)
    make_up(db, 701, (group_a,))

    def _tag_members(request: httpx.Request) -> httpx.Response:
        if int(request.url.params["tagid"]) == 1:
            return httpx.Response(200, json={"code": 22104, "message": "该分组不存在", "data": None})
        return envelope([])

    respx.get(f"{API_BASE}/x/relation/tags").mock(
        return_value=envelope(
            [
                {"tagid": 1, "name": TAG1_NAME, "count": 0, "tip": ""},
                {"tagid": 2, "name": TAG2_NAME, "count": 0, "tip": ""},
            ]
        )
    )
    respx.get(f"{API_BASE}/x/relation/tag").mock(side_effect=_tag_members)
    respx.get(f"{API_BASE}/x/relation/tag/user").mock(return_value=envelope({}))

    plan = native_sync.plan_push(db, mode="append")
    assert plan["to_add"] == {"1": [701]}  # desired members still converge
    assert plan["tag_reads_complete"] is True
