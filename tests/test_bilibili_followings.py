"""Tests for bilibili fetchers: followings.py, native_groups.py, unfollow.py.

All HTTP is mocked with respx (fake cookie values only); each test gets a
fresh in-memory SQLite database built from app.models.Base.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
os.environ.setdefault("DATA_DIR", str(Path(tempfile.mkdtemp(prefix="biliup-followings-"))))

from app.models import Base, BilibiliAccount, NativeGroupMap  # noqa: E402
from app.services.bilibili import followings as followings_module  # noqa: E402
from app.services.bilibili import native_groups, unfollow  # noqa: E402
from app.services.bilibili.client import (  # noqa: E402
    API_BASE,
    HISTORY_PAGE_SIZE,
    BiliClient,
)
from app.services.bilibili.errors import RiskControlError  # noqa: E402

IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"
FAKE_COOKIES = {"SESSDATA": "fake_sess,with_comma", "bili_jct": "fake_jct", "DedeUserID": "42"}

# official wbi test-vector epoch (docs/RESEARCH_BILIBILI.md §3.2)
EP1 = 1702204169  # "2023-12-10 10:29:29"
EP2 = 1700000000  # "2023-11-14 22:13:20"

NAV_DATA = {
    "isLogin": True,
    "mid": 42,
    "uname": "测试号",
    "wbi_img": {
        "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
        "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
    },
}


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
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def logged_in_db(db: Session) -> Session:
    db.add(
        BilibiliAccount(
            id=1,
            login_status="active",
            cookie_json=json.dumps(FAKE_COOKIES),
        )
    )
    db.commit()
    return db


@pytest.fixture
def client() -> BiliClient:
    c = BiliClient(cookies=dict(FAKE_COOKIES), min_interval=0)
    yield c
    c.close()


def mock_nav() -> respx.Route:
    return respx.get(f"{API_BASE}/x/web-interface/nav").mock(return_value=envelope(NAV_DATA))


# --------------------------------------------------------------- followings


@respx.mock
def test_fetch_followings_maps_relation_fields(logged_in_db: Session, client: BiliClient) -> None:
    mock_nav()
    respx.get(f"{API_BASE}/x/relation/followings").mock(
        return_value=envelope(
            {
                "total": 2,
                "list": [
                    {
                        "mid": 101,
                        "uname": "UP甲",
                        "sign": "签名甲",
                        "face": "http://f/101",
                        "official_verify": {"type": 0, "desc": "官方认证"},
                        "special": 1,
                        "mtime": EP1,
                        "attribute": 2,
                    },
                    {"mid": 102, "uname": "UP乙", "sign": "", "face": "", "mtime": None},
                ],
            }
        )
    )

    rows = followings_module.fetch_followings(logged_in_db, client=client)

    assert rows == [
        {
            "mid": 101,
            "uname": "UP甲",
            "sign": "签名甲",
            "face": "http://f/101",
            "official_type": 0,
            "special": True,
            "followed_at": "2023-12-10 10:29:29",  # from mtime epoch
        },
        {
            "mid": 102,
            "uname": "UP乙",
            "sign": "",
            "face": "",
            "official_type": -1,  # no official_verify block
            "special": False,
            "followed_at": None,
        },
    ]


@respx.mock
def test_fetch_followings_paginates(logged_in_db: Session, client: BiliClient) -> None:
    mock_nav()
    route = respx.get(f"{API_BASE}/x/relation/followings").mock(
        side_effect=[
            envelope({"total": 3, "list": [{"mid": 1, "uname": "A", "mtime": EP2}]}),
            envelope({"total": 3, "list": [{"mid": 2, "uname": "B"}, {"mid": 3, "uname": "C"}]}),
        ]
    )

    rows = followings_module.fetch_followings(logged_in_db, client=client)

    assert [r["mid"] for r in rows] == [1, 2, 3]
    assert route.call_count == 2
    assert route.calls[0].request.url.params["pn"] == "1"
    assert route.calls[1].request.url.params["pn"] == "2"
    assert route.calls[0].request.url.params["ps"] == "50"


@respx.mock
def test_fetch_followings_builds_client_from_cookies(
    logged_in_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        followings_module, "build_client", lambda db: BiliClient(cookies=dict(FAKE_COOKIES), min_interval=0)
    )
    mock_nav()
    route = respx.get(f"{API_BASE}/x/relation/followings").mock(
        return_value=envelope({"total": 1, "list": [{"mid": 101, "uname": "UP甲"}]})
    )

    rows = followings_module.fetch_followings(logged_in_db)

    assert [r["mid"] for r in rows] == [101]
    assert route.calls.last.request.url.params["vmid"] == "42"  # mid from DedeUserID cookie


@respx.mock
def test_fetch_latest_archive_maps_fields(logged_in_db: Session, client: BiliClient) -> None:
    mock_nav()
    respx.get(f"{API_BASE}/x/space/wbi/arc/search").mock(
        return_value=envelope(
            {
                "list": {
                    "vlist": [
                        {
                            "bvid": "BV1z",
                            "title": "新视频",
                            "created": EP2,
                            "pic": "http://pic",
                            "length": "05:00",
                        },
                        {
                            "bvid": "BV1old",
                            "title": "旧视频",
                            "created": EP1,
                            "pic": "http://pic2",
                            "length": "03:00",
                        },
                    ]
                },
                "page": {"count": 2, "pn": 1, "ps": 30},
            }
        )
    )

    arc = followings_module.fetch_latest_archive(logged_in_db, 101, client=client)

    assert arc == {
        "bvid": "BV1z",  # first vlist entry = newest (order=pubdate)
        "title": "新视频",
        "pubdate": "2023-11-14 22:13:20",
        "pic": "http://pic",
        "length": "05:00",
    }


@respx.mock
def test_fetch_latest_archive_none_when_no_uploads(logged_in_db: Session, client: BiliClient) -> None:
    mock_nav()
    respx.get(f"{API_BASE}/x/space/wbi/arc/search").mock(
        return_value=envelope({"list": {"vlist": []}, "page": {"count": 0}})
    )
    assert followings_module.fetch_latest_archive(logged_in_db, 101, client=client) is None


@respx.mock
def test_fetch_recent_archives_dedupes_cross_up_bvids(logged_in_db: Session, client: BiliClient) -> None:
    """同一个 bvid 可能出现在多个 UP 的投稿列表（联创/转载）；落库必须全局去重。"""
    from app.models import Video

    mock_nav()
    shared = {"bvid": "BV1dup", "title": "联合创作", "tname": "科技", "created": 1700000000, "length": "5:00"}
    respx.get(f"{API_BASE}/x/space/wbi/arc/search").mock(
        return_value=envelope(
            {
                "list": {"vlist": [shared, {"bvid": "BV1own", "title": "本命稿件", "created": 1699000000}]},
                "page": {"count": 2},
            }
        )
    )
    refreshed = followings_module.fetch_recent_archives(logged_in_db, [101, 102], client=client)
    assert refreshed == 2
    rows = logged_in_db.query(Video).all()
    assert {r.bvid for r in rows} == {"BV1dup", "BV1own"}
    assert logged_in_db.query(Video).filter(Video.bvid == "BV1dup").count() == 1


@respx.mock
def test_fetch_history_maps_and_filters(logged_in_db: Session, client: BiliClient) -> None:
    respx.get(f"{API_BASE}/x/web-interface/history/search").mock(
        return_value=envelope(
            {
                "page": {"total": 3},
                "list": [
                    {
                        "title": "视频一",
                        "view_at": EP1,
                        "progress": 120,
                        "author_mid": 101,
                        "history": {"bvid": "BV1h1", "oid": 11, "business": "archive"},
                    },
                    {
                        "title": "看完的视频",
                        "view_at": EP2,
                        "progress": -1,
                        "author_mid": None,
                        "history": {"bvid": "BV1h2", "business": "archive"},
                    },
                    {
                        "title": "直播回放",
                        "view_at": EP1,
                        "history": {"bvid": "", "business": "live"},  # no bvid -> filtered
                    },
                ],
            }
        )
    )

    entries = followings_module.fetch_history(logged_in_db, max_pages=3, client=client)

    assert entries == [
        {
            "bvid": "BV1h1",
            "title": "视频一",
            "author_mid": 101,
            "view_at": "2023-12-10 10:29:29",
            "progress": 120,
            "duration": 0,
        },
        {
            "bvid": "BV1h2",
            "title": "看完的视频",
            "author_mid": None,
            "view_at": "2023-11-14 22:13:20",
            "progress": -1,
            "duration": 0,
        },
    ]


@respx.mock
def test_fetch_history_respects_max_pages(logged_in_db: Session, client: BiliClient) -> None:
    def full_page(offset: int) -> httpx.Response:
        rows = [
            {
                "title": f"视频{offset + i}",
                "view_at": EP1 + offset + i,
                "progress": 0,
                "author_mid": 101,
                "history": {"bvid": f"BV1p{offset + i}", "business": "archive"},
            }
            for i in range(HISTORY_PAGE_SIZE)  # full page -> keep paginating
        ]
        return envelope({"page": {"total": 100}, "list": rows})

    route = respx.get(f"{API_BASE}/x/web-interface/history/search").mock(
        side_effect=[full_page(0), full_page(20)]
    )

    entries = followings_module.fetch_history(logged_in_db, max_pages=2, client=client)

    assert len(entries) == 2 * HISTORY_PAGE_SIZE
    assert route.call_count == 2
    assert route.calls[0].request.url.params["pn"] == "1"
    assert route.calls[1].request.url.params["pn"] == "2"
    assert route.calls[0].request.url.params["business"] == "archive"


@respx.mock
def test_fetch_user_card_maps_card(logged_in_db: Session, client: BiliClient) -> None:
    route = respx.get(f"{API_BASE}/x/web-interface/card").mock(
        return_value=envelope(
            {
                "card": {
                    "mid": "101",
                    "name": "UP甲",
                    "sign": "签名",
                    "face": "http://face",
                    "Official": {"type": 0, "title": "认证"},
                },
                "following": True,
                "archive_count": 5,
            }
        )
    )

    card = followings_module.fetch_user_card(logged_in_db, 101, client=client)

    assert card == {"mid": 101, "uname": "UP甲", "sign": "签名", "face": "http://face", "official_type": 0}
    assert route.calls.last.request.url.params["mid"] == "101"


@respx.mock
def test_fetch_user_card_none_for_missing_card(logged_in_db: Session, client: BiliClient) -> None:
    respx.get(f"{API_BASE}/x/web-interface/card").mock(return_value=envelope({"card": None}))
    assert followings_module.fetch_user_card(logged_in_db, 999, client=client) is None


# ------------------------------------------------------------ native groups


@respx.mock
def test_list_tags_upserts_native_group_map(logged_in_db: Session, client: BiliClient) -> None:
    logged_in_db.add(NativeGroupMap(bili_tag_id=2, bili_tag_name="旧名字", synced_at=None))
    logged_in_db.commit()

    route = respx.get(f"{API_BASE}/x/relation/tags").mock(
        return_value=envelope(
            [
                {"tagid": 1, "name": "技术", "count": 0, "tip": ""},
                {"tagid": 2, "name": "生活", "count": 3, "tip": ""},
            ]
        )
    )

    tags = native_groups.list_tags(logged_in_db, client=client)

    assert tags == [{"bili_tag_id": 1, "bili_tag_name": "技术"}, {"bili_tag_id": 2, "bili_tag_name": "生活"}]
    assert route.called
    rows = logged_in_db.query(NativeGroupMap).order_by(NativeGroupMap.bili_tag_id).all()
    assert [r.bili_tag_name for r in rows] == ["技术", "生活"]  # inserted + renamed
    assert all(r.synced_at for r in rows)

    native_groups.list_tags(logged_in_db, client=client)  # second refresh: no duplicates
    assert logged_in_db.query(NativeGroupMap).count() == 2


@respx.mock
def test_create_tag_posts_csrf(logged_in_db: Session, client: BiliClient) -> None:
    route = respx.post(f"{API_BASE}/x/relation/tag/create").mock(return_value=envelope({"tagid": 9}))

    tag_id = native_groups.create_tag(logged_in_db, "新分组", client=client)

    assert tag_id == 9
    form = parse_qs(route.calls.last.request.content.decode())
    assert form["tag"] == ["新分组"]
    assert form["csrf"] == ["fake_jct"]  # csrf must equal stored bili_jct


@respx.mock
def test_add_users_to_tag_batches_of_fifty(logged_in_db: Session, client: BiliClient) -> None:
    route = respx.post(f"{API_BASE}/x/relation/tags/addUsers").mock(return_value=envelope({}))

    added = native_groups.add_users_to_tag(logged_in_db, 9, list(range(120)), client=client)

    assert added == 120
    assert route.call_count == 3  # 50 + 50 + 20
    form = parse_qs(route.calls.last.request.content.decode())
    assert form["fids"] == [",".join(str(m) for m in range(100, 120))]
    assert form["tagids"] == ["9"]
    assert form["csrf"] == ["fake_jct"]


# ----------------------------------------------------------------- unfollow


@respx.mock
def test_unfollow_users_posts_modify_act_2(logged_in_db: Session, client: BiliClient) -> None:
    route = respx.post(f"{API_BASE}/x/relation/modify").mock(return_value=envelope({}))

    confirmed = unfollow.unfollow_users(logged_in_db, [101, 102, 103], client=client)

    assert confirmed == 3
    assert route.call_count == 3
    first = parse_qs(route.calls[0].request.content.decode())
    second = parse_qs(route.calls[1].request.content.decode())
    assert (first["fid"], first["act"], first["csrf"]) == (["101"], ["2"], ["fake_jct"])
    assert second["fid"] == ["102"]


@respx.mock
def test_unfollow_users_stops_on_risk_control(logged_in_db: Session) -> None:
    sleeps: list[float] = []
    client = BiliClient(cookies=dict(FAKE_COOKIES), min_interval=0, sleep=sleeps.append)
    try:
        route = respx.post(f"{API_BASE}/x/relation/modify").mock(
            side_effect=[
                httpx.Response(200, json={"code": -412, "message": "blocked", "data": None}),
                httpx.Response(200, json={"code": -352, "message": "风控", "data": None}),
                httpx.Response(200, json={"code": -412, "message": "blocked", "data": None}),
            ]
        )

        with pytest.raises(RiskControlError):
            unfollow.unfollow_users(logged_in_db, [101, 102], client=client)

        assert route.call_count == 3  # initial + 2 risk retries then abort
        assert sleeps == [2.0, 4.0]
    finally:
        client.close()
