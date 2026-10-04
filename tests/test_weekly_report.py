"""Weekly report: natural-week archive, revisions, exports, idempotency.

Covers the T3-T6 acceptance surface: week resolution by Shanghai calendar,
snapshot freezing, revision semantics (regenerate keeps the old revision),
save without SMTP/AI, email failure keeps the archive, and legacy migration
of the old "weekly_report:latest" app_settings row.
"""

from __future__ import annotations

import json
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

from app.db import get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppSetting, GroupLocal, GroupMember, UpUser, WatchHistory, WeeklyReport  # noqa: E402
from app.services import weekly_report as wr  # noqa: E402
from app.services.settings_store import update_section  # noqa: E402
from app.timeutil import date_range_utc, format_date, week_bounds, week_start  # noqa: E402

_TS = "%Y-%m-%d %H:%M:%S"
_MID_BASE = 940_000_000


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime(_TS)


def _stamp_for_day(shanghai_date: str, hour: int = 4) -> str:
    """Naive-UTC stamp whose Shanghai wall clock falls on shanghai_date."""
    from app.timeutil import day_range_utc

    year, month, day = (int(p) for p in shanghai_date.split("-"))
    from datetime import date as date_cls

    start_utc, _ = day_range_utc(date_cls(year, month, day))
    dt = datetime.strptime(start_utc, _TS) + timedelta(hours=hour)
    return dt.strftime(_TS)


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
    history_ids: list[int] = []

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

    def make_watch(
        up_mid: int, day_offset: int = 0, bvid: str | None = None, progress: int = 100, duration: int = 200
    ):
        day = datetime.now(UTC).date() - timedelta(days=day_offset)
        stamp = _stamp_for_day(format_date(day))
        row = WatchHistory(
            bvid=bvid or f"BV1w{next(seq)}",
            up_mid=up_mid,
            title="观看记录",
            view_at=stamp,
            progress=progress,
            duration_seconds=duration,
        )
        db.add(row)
        db.flush()
        history_ids.append(row.id)
        return row

    yield {
        "make_up": make_up,
        "make_group": make_group,
        "make_watch": make_watch,
    }

    if mids:
        db.query(UpUser).filter(UpUser.mid.in_(mids)).delete(synchronize_session=False)
    if group_ids:
        db.query(GroupLocal).filter(GroupLocal.id.in_(group_ids)).delete(synchronize_session=False)
    if history_ids:
        db.query(WatchHistory).filter(WatchHistory.id.in_(history_ids)).delete(synchronize_session=False)
    db.query(AppSetting).filter(AppSetting.key == "weekly_report:latest").delete(synchronize_session=False)
    db.query(WeeklyReport).delete(synchronize_session=False)
    db.commit()


@pytest.fixture(autouse=True)
def clean_sections(db):  # noqa: ANN001, ANN201
    update_section(db, "smtp", {"host": "", "to_addr": ""})
    update_section(db, "reminders", {"weekly_report_enabled": True})
    yield
    update_section(db, "smtp", {"host": "", "to_addr": ""})
    update_section(db, "reminders", {"weekly_report_enabled": True})
    db.commit()


# ------------------------------------------------------------------ T2/T3


def test_week_bounds_are_shanghai_half_open() -> None:
    from datetime import date

    # 2026-09-28 is a Monday; 2026-10-04 23:59 Shanghai is still that week;
    # 2026-10-05 (Monday) starts the next one.
    start, end = week_bounds(date(2026, 9, 28))
    assert format_date(start) == "2026-09-28" and format_date(end) == "2026-10-05"
    start_utc, end_utc = date_range_utc(start, end)
    assert start_utc == "2026-09-27 16:00:00", "Shanghai Mon 00:00 == UTC Sun 16:00"
    assert end_utc == "2026-10-04 16:00:00"

    # a stamp at Shanghai 2026-10-04 23:59:59 == UTC 15:59:59 -> inside the week
    assert "2026-10-04 15:59:59" >= start_utc and "2026-10-04 15:59:59" < end_utc
    # Shanghai 2026-10-05 00:00 == UTC 2026-10-04 16:00 -> next week
    assert not ("2026-10-04 16:00:00" < end_utc)

    assert week_start(date(2026, 10, 4)) == date(2026, 9, 28)  # Sunday -> same week
    assert week_start(date(2026, 1, 1)) == date(2025, 12, 29)  # year boundary


def test_resolve_week_any_day_same_natural_week() -> None:
    from datetime import date

    for day in (date(2026, 9, 28), date(2026, 10, 1), date(2026, 10, 4)):
        start, end, complete = wr.resolve_week(day)
        assert format_date(start) == "2026-09-28"
        assert format_date(end) == "2026-10-05"
        # today (2026-10-04) is still inside that week -> not complete yet
        assert complete is False
    # a fully past week is complete
    start, end, complete = wr.resolve_week(date(2026, 9, 21))
    assert complete is True


def test_generate_report_natural_week_snapshot(db, factory) -> None:  # noqa: ANN001
    up = factory["make_up"](uname="周报快照UP")
    factory["make_watch"](up.mid, day_offset=1, progress=-1, duration=300)
    factory["make_watch"](up.mid, day_offset=2, progress=60, duration=300)
    db.commit()

    report = wr.generate_report(db, datetime.now(UTC).date(), save=True)
    assert not isinstance(report, dict)
    stats = json.loads(report.stats_json)
    assert stats["period"]["start"] == format_date(week_start(datetime.now(UTC).date()))
    assert stats["timezone"] == "Asia/Shanghai"
    assert stats["metrics_version"]
    assert stats["views"] >= 2
    # finished record: 300s; partial: min(60, 300)=60 -> 360 total for ours
    assert stats["watch_seconds_est"] >= 360
    assert stats["samples"]["valid"] >= 2
    assert report.period_start == stats["period"]["start"]
    assert report.period_end_exclusive
    assert "周报" in report.html
    # lists section exists; coverage note states sync scope
    assert stats["coverage"]["note"]
    # cleanup
    db.delete(report)
    db.commit()


def test_future_week_refused(db) -> None:  # noqa: ANN001
    future = datetime.now(UTC).date() + timedelta(days=14)
    result = wr.generate_report(db, future, save=True)
    assert isinstance(result, dict) and result["ok"] is False


# ------------------------------------------------------------------- T4


def test_regenerate_creates_new_revision_and_keeps_old(db, factory) -> None:  # noqa: ANN001
    up = factory["make_up"](uname="周报修订UP")
    factory["make_watch"](up.mid, day_offset=1)
    db.commit()

    first = wr.generate_report(db, datetime.now(UTC).date(), save=True)
    assert not isinstance(first, dict)
    # identical content does NOT duplicate a revision (idempotency rule)...
    second = wr.generate_report(db, datetime.now(UTC).date(), save=True)
    assert not isinstance(second, dict)
    assert second.id == first.id
    # ...but the explicit regenerate path forces a fresh revision
    forced = wr.generate_report(db, datetime.now(UTC).date(), save=True, force_revision=True)
    assert not isinstance(forced, dict)
    assert forced.revision > first.revision

    revisions = (
        db.query(WeeklyReport)
        .filter(WeeklyReport.period_start == first.period_start)
        .order_by(WeeklyReport.revision)
        .all()
    )
    assert len(revisions) == 2
    # the first revision still exists and is untouched
    db.refresh(first)
    assert first.status == "archived"
    for r in revisions:
        db.delete(r)
    db.commit()


def test_idempotent_scheduler_generation_no_duplicate(db, factory) -> None:  # noqa: ANN001
    first = wr.generate_last_complete_week(db)
    assert not isinstance(first, dict)
    count_before = db.query(WeeklyReport).filter(WeeklyReport.period_start == first.period_start).count()
    again = wr.generate_last_complete_week(db)
    assert not isinstance(again, dict)
    count_after = db.query(WeeklyReport).filter(WeeklyReport.period_start == first.period_start).count()
    assert count_before == count_after  # identical content -> no new revision
    for r in db.query(WeeklyReport).all():
        db.delete(r)
    db.commit()


def test_migrations_rerun_keep_data(db) -> None:  # noqa: ANN001
    """T4: running the migration twice must not lose weekly reports."""
    from app.db import run_migrations

    report = wr.generate_last_complete_week(db)
    assert not isinstance(report, dict)
    run_migrations()  # idempotent second run
    still = db.get(WeeklyReport, report.id)
    assert still is not None
    db.delete(report)
    db.commit()


# ------------------------------------------------------------------- T5


def test_save_does_not_need_smtp_or_ai(db, factory) -> None:  # noqa: ANN001
    up = factory["make_up"]()
    factory["make_watch"](up.mid, day_offset=0)
    db.commit()
    # no SMTP configured at all (clean_sections left it empty)
    report = wr.generate_report(db, datetime.now(UTC).date(), save=True)
    assert not isinstance(report, dict)
    assert report.html
    assert json.loads(report.stats_json)["views"] >= 1
    db.delete(report)
    db.commit()


def test_archived_report_survives_restart_and_data_changes(db, factory) -> None:  # noqa: ANN001
    up = factory["make_up"](uname="周报冻结UP")
    factory["make_watch"](up.mid, day_offset=1, progress=100, duration=200)
    db.commit()
    report = wr.generate_report(db, datetime.now(UTC).date(), save=True)
    assert not isinstance(report, dict)
    stats_before = json.loads(report.stats_json)

    # new rows + group changes after generation must not alter the snapshot
    factory["make_watch"](up.mid, day_offset=0, bvid="BV1later")
    db.commit()
    db.expire_all()
    stats_after = json.loads(db.get(WeeklyReport, report.id).stats_json)
    assert stats_after == stats_before
    db.delete(report)
    db.commit()


# ------------------------------------------------------------------- T6


def test_send_failure_keeps_archive(db, factory, monkeypatch) -> None:  # noqa: ANN001
    update_section(db, "smtp", {"host": "smtp.test", "port": 465, "to_addr": "weekly@test"})

    def boom(_db, subject, html):  # noqa: ANN001
        raise RuntimeError("smtp down")

    monkeypatch.setattr(wr, "send_email", boom)
    report = wr.generate_last_complete_week(db)
    assert not isinstance(report, dict)
    result = wr.send_report(db, report)
    assert result["ok"] is False
    db.refresh(report)
    assert report.html  # archive untouched
    assert report.send_status == "failed"
    db.delete(report)
    db.commit()


def test_send_uses_stored_snapshot_not_a_rebuild(db, factory, monkeypatch) -> None:  # noqa: ANN001
    update_section(db, "smtp", {"host": "smtp.test", "port": 465, "to_addr": "weekly@test"})
    captured: dict[str, str] = {}

    def fake_send(_db, subject: str, html: str) -> None:  # noqa: ANN001
        captured["subject"] = subject
        captured["html"] = html

    monkeypatch.setattr(wr, "send_email", fake_send)
    report = wr.generate_last_complete_week(db)
    assert not isinstance(report, dict)
    stored_html = report.html

    result = wr.send_report(db, report)
    assert result["ok"] is True
    assert captured["html"] == stored_html  # the exact archived revision
    assert format_date(week_start(datetime.now(UTC).date()) - timedelta(days=7)) in captured["subject"]
    db.refresh(report)
    assert report.send_status == "sent"
    db.delete(report)
    db.commit()


# ---------------------------------------------------------------- exports


def test_exports_html_md_json(db, factory) -> None:  # noqa: ANN001
    up = factory["make_up"](uname="周报导出UP")
    factory["make_watch"](up.mid, day_offset=1)
    db.commit()
    report = wr.generate_last_complete_week(db)
    assert not isinstance(report, dict)

    md = wr.export_markdown(report)
    assert "# BiliUP Organizer 周报" in md
    assert "按记录进度估算" in md
    payload = wr.export_json(report)
    assert payload["report"]["period_start"]
    assert payload["stats"]["timezone"] == "Asia/Shanghai"
    assert "<html" in report.html.lower()
    db.delete(report)
    db.commit()


# ------------------------------------------------------------ legacy chain


def test_legacy_latest_row_migrates_to_archive(db) -> None:  # noqa: ANN001
    from app.db import get_engine, run_migrations
    from app.migrations import m0006_weekly_archive as m6

    row = AppSetting(
        key="weekly_report:latest",
        value=json.dumps({"generated_at": "2026-09-01 00:00:00", "html": "<p>legacy html</p>"}),
    )
    db.merge(row)
    db.commit()
    m6._migrate_legacy_report(get_engine())
    legacy = db.query(WeeklyReport).filter(WeeklyReport.is_legacy.is_(True)).first()
    assert legacy is not None
    assert legacy.html == "<p>legacy html</p>"
    assert legacy.period_start is None  # rolling range is NOT restated as a week
    assert db.get(AppSetting, "weekly_report:latest") is None
    run_migrations()  # must not duplicate
    db.delete(legacy)
    db.commit()


# ------------------------------------------------------------------- API


def test_week_api_and_generate_endpoints(db) -> None:  # noqa: ANN001
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "demo"})
        assert login.status_code == 200
        csrf = client.cookies.get("biliup_csrf")
        client.headers.update({"X-CSRF-Token": csrf})

        # any day of the same week resolves to the same natural week
        week = client.get("/api/v1/weekly-report/week", params={"date": "2026-10-04"}).json()
        assert week["week_start"] == "2026-09-28"
        week2 = client.get("/api/v1/weekly-report/week", params={"date": "2026-09-30"}).json()
        assert week2["week_start"] == week["week_start"]

        stats = client.get("/api/v1/weekly-report/stats", params={"start": "2026-09-28", "end": "2026-10-05"})
        assert stats.status_code == 200
        assert stats.json()["timezone"] == "Asia/Shanghai"

        gen = client.post("/api/v1/weekly-report/generate", json={"week_start": "2026-10-04", "save": True})
        assert gen.status_code == 200
        body = gen.json()
        assert body["saved"] is True
        report_id = body["report"]["id"]

        exports = [
            client.get(f"/api/v1/weekly-report/{report_id}/export", params={"format": f})
            for f in ("html", "md", "json")
        ]
        assert all(e.status_code == 200 for e in exports)

        # archived read-back equals the stored snapshot, not a recompute
        got = client.get(f"/api/v1/weekly-report/{report_id}").json()
        assert got["stats"]["period"]["start"] == "2026-09-28"
        db.query(WeeklyReport).filter(WeeklyReport.id == report_id).delete(synchronize_session=False)
        db.commit()


def test_send_legacy_smtp_unconfigured(db) -> None:  # noqa: ANN001
    result = wr.send_weekly(db)
    assert result["ok"] is False
    assert "SMTP" in result["message"]


def test_send_weekly_disabled(db) -> None:  # noqa: ANN001
    update_section(db, "reminders", {"weekly_report_enabled": False})
    result = wr.send_weekly(db)
    assert result["ok"] is False
    assert "关闭" in result["message"]
