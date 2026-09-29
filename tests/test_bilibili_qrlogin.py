"""Tests for the QR login service (app/services/bilibili/qrlogin.py).

All HTTP is mocked with respx (fake cookie values only); each test gets a
fresh in-memory SQLite database built from app.models.Base.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
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
os.environ.setdefault("DATA_DIR", str(Path(tempfile.mkdtemp(prefix="biliup-qrlogin-"))))

from app.models import Base, BilibiliAccount  # noqa: E402
from app.services.bilibili import qrlogin as qrlogin_module  # noqa: E402
from app.services.bilibili.client import (  # noqa: E402
    API_BASE,
    HOME_URL,
    PASSPORT_BASE,
    BiliClient,
)
from app.services.bilibili.cookies import load_cookies  # noqa: E402

IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"

NAV_DATA = {
    "isLogin": True,
    "mid": 42,
    "uname": "bili测试号",
    "face": "http://i0.hdslb.com/face/42.png",
    "wbi_img": {
        "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
        "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
    },
}

QR_URL = "https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=KEY123"

CONFIRM_HEADERS = [
    ("Set-Cookie", "SESSDATA=fake_sess,with_commas; Path=/; Domain=bilibili.com; HttpOnly; Secure"),
    ("Set-Cookie", "bili_jct=fake_jct; Path=/; Domain=bilibili.com"),
    ("Set-Cookie", "DedeUserID=42; Path=/; Domain=bilibili.com"),
]


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
def fast_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_client with zero rate-limit interval so tests stay instant."""

    def _build(db: Session) -> BiliClient:
        return BiliClient(cookies=load_cookies(db), min_interval=0)

    monkeypatch.setattr(qrlogin_module, "build_client", _build)


def mock_home() -> respx.Route:
    return respx.get(HOME_URL).mock(
        return_value=httpx.Response(
            200,
            text="<html>ok</html>",
            headers=[("Set-Cookie", "buvid3=fakebuvid3; Path=/; Domain=bilibili.com")],
        )
    )


def mock_generate() -> respx.Route:
    return respx.get(f"{PASSPORT_BASE}/x/passport-login/web/qrcode/generate").mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "message": "0", "data": {"url": QR_URL, "qrcode_key": "KEY123"}},
        )
    )


def mock_poll(code: int, headers: list | None = None) -> respx.Route:
    return respx.get(f"{PASSPORT_BASE}/x/passport-login/web/qrcode/poll").mock(
        return_value=httpx.Response(
            200,
            headers=list(headers or []),
            json={
                "code": 0,
                "message": "0",
                "data": {"code": code, "url": "https://x", "refresh_token": "rt"},
            },
        )
    )


def mock_nav_ok() -> respx.Route:
    return respx.get(f"{API_BASE}/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={"code": 0, "message": "0", "data": NAV_DATA})
    )


@respx.mock
def test_start_login_warms_buvid_and_matches_qr_start_out(db: Session, fast_client) -> None:
    home = mock_home()
    generate = mock_generate()

    result = qrlogin_module.start_login(db)

    assert home.called  # buvid3 warmed before generating
    request = generate.calls.last.request
    assert "buvid3=fakebuvid3" in request.headers["Cookie"]  # same cookie jar

    assert set(result) == {"qrcode_key", "qr_url", "expires_at"}
    assert result["qrcode_key"] == "KEY123"
    assert result["qr_url"] == QR_URL
    expires = datetime.strptime(result["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    delta = expires - datetime.now(UTC)
    assert timedelta(seconds=170) < delta <= timedelta(seconds=181)  # 180s TTL


@respx.mock
def test_poll_login_states_waiting_scanned_expired(db: Session, fast_client) -> None:
    for code, status in ((86101, "waiting"), (86090, "scanned"), (86038, "expired")):
        mock_poll(code)
        result = qrlogin_module.poll_login(db, "KEY123")
        assert result == {"status": status, "account": None}

    account = db.get(BilibiliAccount, 1)
    assert account is None or account.cookie_json is None  # nothing persisted


@respx.mock
def test_poll_login_confirmed_persists_cookies_and_profile(db: Session, fast_client) -> None:
    mock_poll(0, CONFIRM_HEADERS)
    mock_nav_ok()

    result = qrlogin_module.poll_login(db, "KEY123")

    assert result["status"] == "confirmed"
    account = db.get(BilibiliAccount, 1)
    assert account is not None
    cookies = json.loads(account.cookie_json or "{}")
    assert cookies["SESSDATA"] == "fake_sess,with_commas"  # comma preserved verbatim
    assert cookies["bili_jct"] == "fake_jct"
    assert cookies["DedeUserID"] == "42"
    assert account.login_status == "active"
    assert account.risk_flag is False
    assert account.mid == 42
    assert account.uname == "bili测试号"  # filled from nav
    assert account.avatar == "http://i0.hdslb.com/face/42.png"
    assert account.cookie_updated_at is not None

    out = result["account"]
    assert out is not None
    assert set(out) == {
        "login_status",
        "mid",
        "uname",
        "avatar",
        "cookie_updated_at",
        "risk_flag",
        "cookie_masked",
    }
    assert out["mid"] == 42
    assert out["uname"] == "bili测试号"
    assert out["risk_flag"] is False
    assert "SESSDATA=••••" in out["cookie_masked"]


@respx.mock
def test_poll_login_confirmed_survives_nav_failure(db: Session, fast_client) -> None:
    mock_poll(0, CONFIRM_HEADERS)
    respx.get(f"{API_BASE}/x/web-interface/nav").mock(return_value=httpx.Response(500, text="nav boom"))

    result = qrlogin_module.poll_login(db, "KEY123")

    assert result["status"] == "confirmed"  # nav failure must not block
    account = db.get(BilibiliAccount, 1)
    assert account is not None
    assert account.login_status == "active"
    assert account.mid == 42  # from the DedeUserID cookie
    assert account.uname is None  # nav never answered
    assert result["account"] is not None


@respx.mock
def test_poll_login_maps_unknown_code_to_waiting(db: Session, fast_client) -> None:
    mock_poll(99999)
    result = qrlogin_module.poll_login(db, "KEY123")
    assert result == {"status": "waiting", "account": None}
