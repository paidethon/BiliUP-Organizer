from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-lumirss-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.db import get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import LumirssPushLog, Reminder, UpUser, Video  # noqa: E402
from app.services import lumirss as lumirss_service  # noqa: E402
from app.services.settings_store import update_section  # noqa: E402

LUMI_BASE = "http://lumi.test"
INGEST_PATH = "/api/v1/inbox/ingest/uuid-1"


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def configured(db, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr("app.services.lumirss.time.sleep", lambda _s: None)
    update_section(
        db,
        "lumirss",
        {"base_url": LUMI_BASE, "token": "secret-1", "inbox_endpoint": INGEST_PATH, "enabled": True},
    )
    yield
    update_section(db, "lumirss", {"base_url": "", "token": "", "inbox_endpoint": "", "enabled": False})


def _make_video(db, bvid: str, pubdate: str) -> Video:  # noqa: ANN001
    up = db.query(UpUser).filter(UpUser.mid == 880010001).first()
    if up is None:
        up = UpUser(mid=880010001, uname="Lumi测试UP")
        db.add(up)
        db.flush()
    video = Video(bvid=bvid, up_mid=up.mid, title=f"Lumi {bvid}", pubdate=pubdate)
    db.add(video)
    db.commit()
    return video


def _item(video: Video) -> dict:  # noqa: ANN001
    return {"bvid": video.bvid, "title": video.title, "pubdate": video.pubdate, "up_uname": "Lumi测试UP"}


def test_push_pending_short_circuits_unconfigured(db) -> None:  # noqa: ANN001
    assert lumirss_service.push_pending(db) == {"pushed": 0, "failed": 0}


@respx.mock
def test_push_items_success_and_idempotent_log(db, configured) -> None:  # noqa: ANN001
    video = _make_video(db, "BV1lumi001", "2026-09-25 10:00:00")
    route = respx.post(f"{LUMI_BASE}{INGEST_PATH}").mock(
        return_value=httpx.Response(200, json={"status": "created"})
    )
    result = lumirss_service.push_items(db, [_item(video)])
    assert result == {"pushed": 1, "failed": 0}
    assert route.call_count == 1
    log_row = db.query(LumirssPushLog).filter(LumirssPushLog.bvid == video.bvid).first()
    assert log_row is not None and log_row.status == "success"

    # replaying the same guid is fine: LumiRSS dedups server-side (exists)
    route.mock(return_value=httpx.Response(200, json={"status": "exists"}))
    result2 = lumirss_service.push_items(db, [_item(video)])
    assert result2 == {"pushed": 1, "failed": 0}
    assert route.call_count == 2


@respx.mock
def test_push_items_retries_then_failure_reminder(db, configured) -> None:  # noqa: ANN001
    video = _make_video(db, "BV1lumi002", "2026-09-25 11:00:00")
    route = respx.post(f"{LUMI_BASE}{INGEST_PATH}").mock(return_value=httpx.Response(500, text="boom"))

    result = lumirss_service.push_items(db, [_item(video)])

    assert result == {"pushed": 0, "failed": 1}
    assert route.call_count == 3  # max attempts
    log_row = db.query(LumirssPushLog).filter(LumirssPushLog.bvid == video.bvid).first()
    assert log_row is not None and log_row.status == "failed"
    reminder = db.query(Reminder).filter(Reminder.dedup_key == "lumirss_failure:system").first()
    assert reminder is not None
    assert reminder.rule_key == "lumirss_failure" and reminder.status == "open"


@respx.mock
def test_push_pending_only_new_videos(db, configured) -> None:  # noqa: ANN001
    # drop logs left by earlier tests so "no successful push yet" holds
    db.query(LumirssPushLog).delete()
    db.commit()
    old = _make_video(db, "BV1lumi003", "2024-01-01 00:00:00")
    fresh = _make_video(
        db, "BV1lumi004", (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    )
    respx.post(f"{LUMI_BASE}{INGEST_PATH}").mock(return_value=httpx.Response(200, json={"status": "created"}))

    result = lumirss_service.push_pending(db)

    # earlier tests leave recent videos too; assert semantics, not the count:
    # the fresh video must be pushed, the 2024 one must never be.
    assert result["pushed"] >= 1
    pushed_bvids = {row.bvid for row in db.query(LumirssPushLog).filter(LumirssPushLog.status == "success")}
    assert fresh.bvid in pushed_bvids
    assert old.bvid not in pushed_bvids


@respx.mock
def test_test_connection_paths(db, configured) -> None:  # noqa: ANN001
    respx.post(f"{LUMI_BASE}{INGEST_PATH}").mock(return_value=httpx.Response(200, json={"status": "created"}))
    ok, message = lumirss_service.test_connection(db)
    assert ok and "连接成功" in message

    respx.post(f"{LUMI_BASE}{INGEST_PATH}").mock(return_value=httpx.Response(401))
    ok, message = lumirss_service.test_connection(db)
    assert not ok and "token" in message


def test_test_connection_unconfigured(db) -> None:  # noqa: ANN001
    ok, message = lumirss_service.test_connection(db)
    assert not ok and "未配置" in message
