from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-weekly-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.api.weekly_routes import load_report  # noqa: E402
from app.db import get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppSetting, GroupLocal, GroupMember, UpUser  # noqa: E402
from app.services import weekly_report as wr  # noqa: E402
from app.services.settings_store import update_section  # noqa: E402
from app.services.weekly_report import build_report, send_weekly  # noqa: E402

_TS = "%Y-%m-%d %H:%M:%S"
_MID_BASE = 940_000_000


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime(_TS)


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def factory(db):  # noqa: ANN001, ANN201
    seq = iter(range(1, 1000))
    mids: list[int] = []
    group_ids: list[int] = []

    def make_up(**kwargs):
        n = next(seq)
        mid = kwargs.pop("mid", _MID_BASE + n)
        params = dict(
            uname=f"周报测试UP{n}",
            followed_at=_days_ago(1),
            last_video_at=_days_ago(1),
            last_watched_at=_days_ago(1),
            watched_count=2,
        )
        params.update(kwargs)
        up = UpUser(mid=mid, **params)
        db.add(up)
        db.flush()
        if up.group_id is not None:
            db.add(GroupMember(up_mid=up.mid, group_id=up.group_id))
            db.flush()
        mids.append(mid)
        return up

    def make_group(**kwargs):
        n = next(seq)
        params = dict(name=f"周报测试组{n}", is_important=False)
        params.update(kwargs)
        group = GroupLocal(**params)
        db.add(group)
        db.flush()
        group_ids.append(group.id)
        return group

    yield {"make_up": make_up, "make_group": make_group}

    if mids:
        db.query(UpUser).filter(UpUser.mid.in_(mids)).delete(synchronize_session=False)
    if group_ids:
        db.query(GroupLocal).filter(GroupLocal.id.in_(group_ids)).delete(synchronize_session=False)
    db.query(AppSetting).filter(AppSetting.key == "weekly_report:latest").delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def clean_sections(db):  # noqa: ANN001, ANN201
    update_section(db, "smtp", {"host": "", "to_addr": ""})
    update_section(db, "reminders", {"weekly_report_enabled": True})
    yield
    update_section(db, "smtp", {"host": "", "to_addr": ""})
    update_section(db, "reminders", {"weekly_report_enabled": True})
    db.query(AppSetting).filter(AppSetting.key == "weekly_report:latest").delete(synchronize_session=False)
    db.commit()


def test_build_report_html_and_sections(db, factory) -> None:  # noqa: ANN001
    important = factory["make_group"](is_important=True)
    # very old so it survives the top-10 cutoff even with leftovers from other
    # test modules in the shared database
    factory["make_up"](uname="周报停更UP", last_video_at=_days_ago(1000), last_watched_at=_days_ago(1))
    factory["make_up"](
        uname="周报从未观看UP",
        followed_at=_days_ago(60),
        watched_count=0,
        last_video_at=_days_ago(1),
        last_watched_at=None,
    )
    factory["make_up"](
        uname="周报重要UP",
        group_id=important.id,
        last_video_at=_days_ago(2),
        last_watched_at=_days_ago(10),
    )
    db.commit()

    html = build_report(db)
    assert "BiliUP Organizer 周报" in html
    assert "生成时间" in html
    for heading in ("总览", "长期未更新", "从未观看", "重要UP未观看"):
        assert heading in html
    assert "周报停更UP" in html
    assert "周报从未观看UP" in html
    assert "周报重要UP" in html
    assert "近7天新增视频" in html and "近7天观看次数" in html and "关注 UP 总数" in html
    assert "未处理提醒" in html
    # email-safe: inline styles, no scripts, zh-CN
    assert 'style="' in html
    assert "<script" not in html.lower()
    assert "<link" not in html.lower()


def test_send_weekly_disabled(db, clean_sections) -> None:  # noqa: ANN001
    update_section(db, "reminders", {"weekly_report_enabled": False})
    result = send_weekly(db)
    assert result["ok"] is False
    assert "关闭" in result["message"]


def test_send_weekly_smtp_unconfigured(db, clean_sections) -> None:  # noqa: ANN001
    result = send_weekly(db)
    assert result["ok"] is False
    assert "SMTP" in result["message"]


def test_send_weekly_sends_and_stores_latest(db, clean_sections, factory, monkeypatch) -> None:  # noqa: ANN001
    update_section(
        db,
        "smtp",
        {"host": "smtp.test", "port": 465, "to_addr": "weekly@test", "use_tls": True},
    )
    captured: dict[str, str] = {}

    def fake_send(_db, subject: str, html: str) -> None:  # noqa: ANN001
        captured["subject"] = subject
        captured["html"] = html

    monkeypatch.setattr(wr, "send_email", fake_send)

    result = send_weekly(db)
    assert result["ok"] is True
    assert "周报" in captured["subject"]
    assert "BiliUP Organizer 周报" in captured["html"]

    latest = load_report(db)
    assert latest is not None
    assert set(latest) >= {"generated_at", "html"}
    assert latest["html"] == captured["html"]
    assert latest["generated_at"].count("-") == 2  # "YYYY-MM-DD HH:MM:SS" stamp


def test_store_and_load_report_roundtrip(db) -> None:  # noqa: ANN001
    from app.api.weekly_routes import store_report

    try:
        store_report(db, "<p>roundtrip</p>")
        latest = load_report(db)
        assert latest["html"] == "<p>roundtrip</p>"
        assert latest["generated_at"].count("-") == 2
    finally:
        db.query(AppSetting).filter(AppSetting.key == "weekly_report:latest").delete(
            synchronize_session=False
        )
        db.commit()
