"""Tests for BiliClient (app/services/bilibili/client.py), all mocked with respx.

Fake cookie values only; no request ever leaves the process.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import httpx
import pytest
import respx

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-client-")))

from app.services.bilibili.client import (  # noqa: E402
    API_BASE,
    ARCHIVE_PAGE_SIZE,
    DEFAULT_PAGE_SIZE,
    HISTORY_PAGE_SIZE,
    HOME_URL,
    PASSPORT_BASE,
    QR_EXPIRES_SECONDS,
    USER_AGENT,
    BiliClient,
)
from app.services.bilibili.errors import (  # noqa: E402
    AuthExpiredError,
    BiliError,
    RiskControlError,
)
from app.services.bilibili.wbi import sign_params  # noqa: E402

IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"
FAKE_COOKIES = {"SESSDATA": "fake_sess,with_comma", "bili_jct": "fake_jct", "DedeUserID": "42"}

NAV_DATA = {
    "isLogin": True,
    "mid": 42,
    "uname": "测试号",
    "wbi_img": {
        "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
        "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
    },
}


def make_client(**kwargs) -> BiliClient:  # noqa: ANN001, ANN003
    kwargs.setdefault("cookies", dict(FAKE_COOKIES))
    kwargs.setdefault("min_interval", 0)
    return BiliClient(**kwargs)


def envelope(code: int = 0, message: str = "0", data: object = None) -> httpx.Response:
    return httpx.Response(200, json={"code": code, "message": message, "data": data})


def mock_nav() -> respx.Route:
    return respx.get(f"{API_BASE}/x/web-interface/nav").mock(return_value=envelope(data=NAV_DATA))


@respx.mock
def test_request_success_returns_data_and_sends_browser_headers() -> None:
    client = make_client()
    try:
        route = mock_nav()
        data = client.get_nav()
        assert data["mid"] == 42
        assert route.called
        request = route.calls.last.request
        assert request.headers["User-Agent"] == USER_AGENT
        assert request.headers["Referer"] == "https://www.bilibili.com/"
        assert request.headers["Origin"] == "https://www.bilibili.com"
        cookie = request.headers["Cookie"]
        assert "SESSDATA=fake_sess" in cookie
        assert "bili_jct=fake_jct" in cookie
        assert "DedeUserID=42" in cookie
    finally:
        client.close()


@respx.mock
def test_request_maps_auth_expired() -> None:
    client = make_client()
    try:
        respx.get(f"{API_BASE}/x/anything").mock(return_value=envelope(code=-101, message="账号未登录"))
        with pytest.raises(AuthExpiredError):
            client._request("GET", f"{API_BASE}/x/anything")
    finally:
        client.close()


@respx.mock
def test_request_maps_other_codes_to_bili_error() -> None:
    client = make_client()
    try:
        respx.get(f"{API_BASE}/x/anything").mock(return_value=envelope(code=-400, message="请求错误"))
        with pytest.raises(BiliError) as excinfo:
            client._request("GET", f"{API_BASE}/x/anything")
        assert excinfo.value.code == -400
        assert excinfo.value.message == "请求错误"
    finally:
        client.close()


@respx.mock
def test_request_raises_risk_control_after_two_retries() -> None:
    sleeps: list[float] = []
    client = make_client(sleep=sleeps.append)
    try:
        route = respx.get(f"{API_BASE}/x/anything").mock(
            side_effect=[
                envelope(code=-412, message="request was blocked"),
                envelope(code=-352, message="风控校验失败"),
                envelope(code=-412, message="request was blocked"),
            ]
        )
        with pytest.raises(RiskControlError) as excinfo:
            client._request("GET", f"{API_BASE}/x/anything")
        assert excinfo.value.code == -412
        assert route.call_count == 3  # first call + 2 retries, then give up
        assert sleeps == [2.0, 4.0]  # exponential backoff, injected clock-free
    finally:
        client.close()


@respx.mock
def test_request_retries_risk_control_then_succeeds() -> None:
    sleeps: list[float] = []
    client = make_client(sleep=sleeps.append)
    try:
        route = respx.get(f"{API_BASE}/x/anything").mock(
            side_effect=[envelope(code=-352, message="风控"), envelope(data={"ok": 1})]
        )
        assert client._request("GET", f"{API_BASE}/x/anything") == {"ok": 1}
        assert route.call_count == 2
        assert sleeps == [2.0]
    finally:
        client.close()


@respx.mock
def test_request_rejects_non_200_and_invalid_json() -> None:
    client = make_client()
    try:
        respx.get(f"{API_BASE}/x/a").mock(return_value=httpx.Response(503, text="down"))
        with pytest.raises(BiliError):
            client._request("GET", f"{API_BASE}/x/a")
        respx.get(f"{API_BASE}/x/b").mock(return_value=httpx.Response(200, text="<html>not json</html>"))
        with pytest.raises(BiliError):
            client._request("GET", f"{API_BASE}/x/b")
    finally:
        client.close()


def test_min_interval_throttles_between_calls() -> None:
    now = {"t": 100.0}
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["t"] += seconds

    client = make_client(min_interval=0.6, clock=lambda: now["t"], sleep=fake_sleep)
    try:
        with respx.mock:
            respx.get(f"{API_BASE}/x/a").mock(return_value=envelope(data=1))
            respx.get(f"{API_BASE}/x/b").mock(return_value=envelope(data=2))
            client._request("GET", f"{API_BASE}/x/a")
            client._request("GET", f"{API_BASE}/x/b")
        # first call is free, the second waits base interval + jitter (<= 25%)
        assert len(sleeps) == 1
        assert 0.6 <= sleeps[0] <= 0.751
    finally:
        client.close()


@respx.mock
def test_ensure_buvid_warms_visitor_cookie() -> None:
    client = make_client(cookies={})
    try:
        home = respx.get(HOME_URL).mock(
            return_value=httpx.Response(
                200,
                text="<html>ok</html>",
                headers=[
                    ("Set-Cookie", "buvid3=fakebuvid3; Path=/; Domain=bilibili.com"),
                    ("Set-Cookie", "b_nut=1700000000; Path=/; Domain=bilibili.com"),
                ],
            )
        )
        route = respx.get(f"{API_BASE}/x/web-interface/card").mock(return_value=envelope(data={"card": {}}))
        client.ensure_buvid()
        client._request("GET", f"{API_BASE}/x/web-interface/card")
        assert home.called
        assert "buvid3=fakebuvid3" in route.calls.last.request.headers["Cookie"]
        # already warmed: a second ensure_buvid must not hit the homepage again
        client.ensure_buvid()
        assert home.call_count == 1
    finally:
        client.close()


@respx.mock
def test_generate_qrcode_contract() -> None:
    client = make_client()
    try:
        route = respx.get(f"{PASSPORT_BASE}/x/passport-login/web/qrcode/generate").mock(
            return_value=envelope(
                data={
                    "url": "https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=K",
                    "qrcode_key": "KEY123",
                }
            )
        )
        qr = client.generate_qrcode()
        assert qr == {
            "qr_url": "https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=K",
            "qrcode_key": "KEY123",
            "expires_in": QR_EXPIRES_SECONDS,
        }
        assert route.called
    finally:
        client.close()


@respx.mock
def test_poll_qrcode_captures_set_cookie_with_commas() -> None:
    client = make_client()
    try:
        route = respx.get(f"{PASSPORT_BASE}/x/passport-login/web/qrcode/poll").mock(
            return_value=httpx.Response(
                200,
                headers=[
                    ("Set-Cookie", "SESSDATA=one,two,three; Path=/; Domain=bilibili.com; HttpOnly; Secure"),
                    ("Set-Cookie", "bili_jct=fresh_jct; Path=/; Domain=bilibili.com"),
                    ("Set-Cookie", "DedeUserID=42; Path=/; Domain=bilibili.com"),
                    ("Set-Cookie", "DedeUserID__ckMd5=ckmd5; Path=/; Domain=bilibili.com"),
                    ("Set-Cookie", "sid=websid; Path=/; Domain=bilibili.com"),
                ],
                json={
                    "code": 0,
                    "message": "0",
                    "data": {"code": 0, "url": "https://game.bilibili.com/cross", "refresh_token": "rt"},
                },
            )
        )
        result = client.poll_qrcode("KEY123")
        assert result["code"] == 0
        assert result["url"] == "https://game.bilibili.com/cross"
        # SESSDATA keeps its commas verbatim; unrelated cookies are dropped
        assert result["cookies"] == {
            "SESSDATA": "one,two,three",
            "bili_jct": "fresh_jct",
            "DedeUserID": "42",
        }
        assert route.calls.last.request.url.params["qrcode_key"] == "KEY123"
    finally:
        client.close()


@respx.mock
def test_poll_qrcode_waiting_has_no_cookies() -> None:
    client = make_client()
    try:
        respx.get(f"{PASSPORT_BASE}/x/passport-login/web/qrcode/poll").mock(
            return_value=envelope(data={"code": 86101, "url": "", "message": ""})
        )
        result = client.poll_qrcode("KEY123")
        assert result == {"code": 86101, "url": "", "cookies": {}}
    finally:
        client.close()


@respx.mock
def test_get_followings_signs_with_wbi_and_uses_ps_50() -> None:
    client = make_client()
    try:
        mock_nav()
        route = respx.get(f"{API_BASE}/x/relation/followings").mock(
            return_value=envelope(data={"total": 1, "re_version": 0, "list": [{"mid": 101, "uname": "UP"}]})
        )
        data = client.get_followings(42, page=2)
        assert data["total"] == 1
        assert data["list"][0]["mid"] == 101
        params = dict(route.calls.last.request.url.params)
        assert params["vmid"] == "42"
        assert params["pn"] == "2"
        assert params["ps"] == str(DEFAULT_PAGE_SIZE)
        # re-sign with the same wts: the request signature must match exactly
        expected = sign_params(
            {"vmid": 42, "pn": 2, "ps": DEFAULT_PAGE_SIZE}, IMG_KEY, SUB_KEY, now=int(params["wts"])
        )
        assert params["w_rid"] == expected["w_rid"]
    finally:
        client.close()


@respx.mock
def test_get_all_followings_paginates_until_total() -> None:
    client = make_client()
    try:
        mock_nav()
        page_one = [{"mid": m} for m in range(50)]
        page_two = [{"mid": 50 + m} for m in range(10)]
        route = respx.get(f"{API_BASE}/x/relation/followings").mock(
            side_effect=[
                envelope(data={"total": 60, "list": page_one}),
                envelope(data={"total": 60, "list": page_two}),
            ]
        )
        entries = client.get_all_followings(42)
        assert len(entries) == 60
        assert route.call_count == 2
        assert route.calls[0].request.url.params["pn"] == "1"
        assert route.calls[1].request.url.params["pn"] == "2"
    finally:
        client.close()


@respx.mock
def test_get_all_followings_stops_on_empty_page() -> None:
    client = make_client()
    try:
        mock_nav()
        route = respx.get(f"{API_BASE}/x/relation/followings").mock(
            return_value=envelope(data={"total": 99, "list": []})
        )
        assert client.get_all_followings(42) == []
        assert route.call_count == 1
    finally:
        client.close()


@respx.mock
def test_get_user_archives_is_wbi_signed_with_pubdate_order() -> None:
    client = make_client()
    try:
        mock_nav()
        route = respx.get(f"{API_BASE}/x/space/wbi/arc/search").mock(
            return_value=envelope(
                data={
                    "list": {"vlist": [{"bvid": "BV1a", "title": "t", "created": 1702204169}]},
                    "page": {"count": 7, "pn": 1, "ps": 30},
                }
            )
        )
        data = client.get_user_archives(7)
        assert data["total"] == 7
        assert data["vlist"][0]["bvid"] == "BV1a"
        params = dict(route.calls.last.request.url.params)
        assert params["mid"] == "7"
        assert params["order"] == "pubdate"
        assert params["ps"] == str(ARCHIVE_PAGE_SIZE)
        assert "w_rid" in params and "wts" in params
    finally:
        client.close()


@respx.mock
def test_get_latest_archive_returns_first_or_none() -> None:
    client = make_client()
    try:
        mock_nav()
        respx.get(f"{API_BASE}/x/space/wbi/arc/search").mock(
            return_value=envelope(
                data={"list": {"vlist": [{"bvid": "BV1first"}, {"bvid": "BV1second"}]}, "page": {"count": 2}}
            )
        )
        assert client.get_latest_archive(7)["bvid"] == "BV1first"
        respx.get(f"{API_BASE}/x/space/wbi/arc/search").mock(
            return_value=envelope(data={"list": {"vlist": []}, "page": {"count": 0}})
        )
        assert client.get_latest_archive(7) is None
    finally:
        client.close()


@respx.mock
def test_get_history_uses_business_archive() -> None:
    client = make_client()
    try:
        route = respx.get(f"{API_BASE}/x/web-interface/history/search").mock(
            return_value=envelope(
                data={"page": {"total": 1}, "list": [{"title": "视频", "view_at": 1702204169}]}
            )
        )
        data = client.get_history(page=3)
        assert data["total"] == 1
        assert data["list"][0]["title"] == "视频"
        params = dict(route.calls.last.request.url.params)
        assert params["business"] == "archive"  # NOT business_type (RESEARCH §6)
        assert params["pn"] == "3"
        assert params["ps"] == str(HISTORY_PAGE_SIZE)
        assert params["keyword"] == ""
    finally:
        client.close()


def test_close_closes_underlying_connection() -> None:
    client = make_client()
    client.close()
    assert client._http.is_closed
