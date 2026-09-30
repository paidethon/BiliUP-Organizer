from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-reminders-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.db import get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AiSuggestion,
    BilibiliAccount,
    GroupLocal,
    Reminder,
    SyncRun,
    UpUser,
)
from app.services.reminders import acknowledge, run_scan  # noqa: E402
from app.util import utcnow  # noqa: E402

_MID_BASE = 930_000_000
_TS = "%Y-%m-%d %H:%M:%S"


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime(_TS)


def _in_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime(_TS)


def _row(db, dedup_key: str) -> Reminder | None:  # noqa: ANN001
    return db.query(Reminder).filter(Reminder.dedup_key == dedup_key).first()


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def factory(db):  # noqa: ANN001, ANN201
    """Create isolated test rows; everything is removed on teardown."""
    seq = iter(range(1, 1000))
    mids: list[int] = []
    group_ids: list[int] = []
    run_ids: list[int] = []

    def make_up(**kwargs) -> UpUser:
        n = next(seq)
        mid = kwargs.pop("mid", _MID_BASE + n)
        params = dict(
            uname=f"提醒测试UP{n}",
            followed_at=_days_ago(1),
            last_video_at=_days_ago(1),
            last_watched_at=_days_ago(1),
            watched_count=2,
        )
        params.update(kwargs)
        up = UpUser(mid=mid, **params)
        db.add(up)
        db.flush()
        mids.append(mid)
        return up

    def make_group(**kwargs) -> GroupLocal:
        n = next(seq)
        params = dict(name=f"提醒测试组{n}", is_important=False)
        params.update(kwargs)
        group = GroupLocal(**params)
        db.add(group)
        db.flush()
        group_ids.append(group.id)
        return group

    def make_suggestion(up: UpUser, **kwargs) -> AiSuggestion:
        params = dict(
            up_mid=up.mid,
            suggested_group_name="建议分组",
            confidence=0.3,
            status="pending",
            created_at=utcnow(),
        )
        params.update(kwargs)
        suggestion = AiSuggestion(**params)
        db.add(suggestion)
        db.flush()
        return suggestion

    def make_sync_run(**kwargs) -> SyncRun:
        params = dict(kind="followings", status="failed", started_at=utcnow(), error="reminders-test")
        params.update(kwargs)
        run = SyncRun(**params)
        db.add(run)
        db.flush()
        run_ids.append(run.id)
        return run

    yield SimpleNamespace(
        make_up=make_up, make_group=make_group, make_suggestion=make_suggestion, make_sync_run=make_sync_run
    )

    if mids:
        db.query(Reminder).filter(Reminder.entity_id.in_([str(m) for m in mids])).delete(
            synchronize_session=False
        )
        db.query(AiSuggestion).filter(AiSuggestion.up_mid.in_(mids)).delete(synchronize_session=False)
        db.query(UpUser).filter(UpUser.mid.in_(mids)).delete(synchronize_session=False)
    if group_ids:
        db.query(GroupLocal).filter(GroupLocal.id.in_(group_ids)).delete(synchronize_session=False)
    if run_ids:
        db.query(SyncRun).filter(SyncRun.id.in_(run_ids)).delete(synchronize_session=False)
    db.commit()


def test_up_rules_trigger_and_dedup(db, factory) -> None:  # noqa: ANN001
    stale = factory.make_up(followed_at=_days_ago(35), last_video_at=_days_ago(40), watched_count=5)
    unwatched = factory.make_up(followed_at=_days_ago(2), last_watched_at=_days_ago(20))
    never = factory.make_up(
        followed_at=_days_ago(60), watched_count=0, last_watched_at=None, last_video_at=_days_ago(1)
    )
    important_group = factory.make_group(is_important=True)
    important = factory.make_up(
        group_id=important_group.id, last_video_at=_days_ago(2), last_watched_at=_days_ago(10)
    )
    low_conf = factory.make_up()
    factory.make_suggestion(low_conf, confidence=0.3)
    clean = factory.make_up()
    db.commit()

    first = run_scan(db)
    assert first["created"] >= 5  # our rows plus first-run demo/system rows

    stale_row = _row(db, f"stale_uploader:{stale.mid}")
    assert stale_row is not None and stale_row.status == "open" and stale_row.severity == "info"
    unwatched_row = _row(db, f"long_unwatched:{unwatched.mid}:14")
    assert unwatched_row is not None
    assert unwatched_row.status == "open" and unwatched_row.severity == "warning"
    never_row = _row(db, f"never_watched:{never.mid}")
    assert never_row is not None
    assert never_row.status == "open" and never_row.severity == "warning"
    important_row = _row(db, f"important_unwatched:{important.mid}")
    assert important_row is not None
    assert important_row.status == "open" and important_row.severity == "warning"
    low_row = _row(db, f"low_confidence:{low_conf.mid}")
    assert low_row is not None
    assert low_row.status == "open" and low_row.severity == "info"
    up_rules = ("stale_uploader", "long_unwatched", "never_watched", "important_unwatched", "low_confidence")
    for rule in up_rules:
        assert _row(db, f"{rule}:{clean.mid}") is None

    second = run_scan(db)
    assert second == {"created": 0, "resolved": 0}
    assert db.query(Reminder).filter(Reminder.dedup_key == f"stale_uploader:{stale.mid}").count() == 1


def test_condition_cleared_resolves(db, factory) -> None:  # noqa: ANN001
    unwatched = factory.make_up(followed_at=_days_ago(2), last_watched_at=_days_ago(20))
    low_conf = factory.make_up()
    suggestion = factory.make_suggestion(low_conf, confidence=0.2)
    db.commit()

    run_scan(db)
    assert _row(db, f"long_unwatched:{unwatched.mid}:14").status == "open"
    assert _row(db, f"low_confidence:{low_conf.mid}").status == "open"

    unwatched.last_watched_at = _days_ago(0)
    suggestion.status = "rejected"
    db.commit()
    result = run_scan(db)
    assert result["resolved"] >= 2
    assert _row(db, f"long_unwatched:{unwatched.mid}:14").status == "resolved"
    assert _row(db, f"low_confidence:{low_conf.mid}").status == "resolved"


def test_reopen_after_resolve_when_condition_returns(db, factory) -> None:  # noqa: ANN001
    up = factory.make_up(followed_at=_days_ago(2), last_watched_at=_days_ago(20))
    db.commit()
    run_scan(db)
    up.last_watched_at = _days_ago(0)
    db.commit()
    run_scan(db)
    assert _row(db, f"long_unwatched:{up.mid}:14").status == "resolved"
    up.last_watched_at = _days_ago(20)
    db.commit()
    result = run_scan(db)
    assert result["created"] >= 1
    assert _row(db, f"long_unwatched:{up.mid}:14").status == "open"


def test_snoozed_missing_blacklisted_skipped(db, factory) -> None:  # noqa: ANN001
    snoozed = factory.make_up(last_video_at=_days_ago(40), snoozed_until=_in_days(1))
    snooze_expired = factory.make_up(last_video_at=_days_ago(40), snoozed_until=_days_ago(1))
    missing = factory.make_up(last_video_at=_days_ago(40), missing=True)
    blacklisted = factory.make_up(last_video_at=_days_ago(40), blacklisted=True)
    db.commit()

    run_scan(db)
    assert _row(db, f"stale_uploader:{snoozed.mid}") is None
    assert _row(db, f"stale_uploader:{missing.mid}") is None
    assert _row(db, f"stale_uploader:{blacklisted.mid}") is None
    expired_row = _row(db, f"stale_uploader:{snooze_expired.mid}")
    assert expired_row is not None and expired_row.status == "open"


def test_system_login_and_risk_roundtrip(db, factory) -> None:  # noqa: ANN001
    mine = factory.make_up(ai_status="error")
    # other test modules may leave ai_status=error rows behind (shared DB); only
    # then does ai_failed:system stay open after we clear our own row
    foreign_errors = db.query(UpUser).filter(UpUser.ai_status == "error", UpUser.mid != mine.mid).count() > 0
    account = db.query(BilibiliAccount).first()
    created = account is None
    if created:
        account = BilibiliAccount(id=1)
        db.add(account)
        db.flush()
    original = (account.login_status, account.risk_flag)
    try:
        account.login_status = "expired"
        account.risk_flag = True
        db.commit()
        run_scan(db)
        assert _row(db, "login_expired:system").status == "open"
        assert _row(db, "login_expired:system").severity == "critical"
        assert _row(db, "risk_control:system").status == "open"
        assert _row(db, "ai_failed:system").status == "open"

        account.login_status, account.risk_flag = original
        mine.ai_status = "done"
        db.commit()
        result = run_scan(db)
        assert result["resolved"] >= 2
        assert _row(db, "login_expired:system").status == "resolved"
        assert _row(db, "risk_control:system").status == "resolved"
        if not foreign_errors:
            assert _row(db, "ai_failed:system").status == "resolved"
    finally:
        account.login_status, account.risk_flag = original
        db.commit()
        if created:
            db.delete(account)
            db.commit()


def test_sync_failed_latest_run_wins(db, factory) -> None:  # noqa: ANN001
    failed = factory.make_sync_run(status="failed", started_at=utcnow())
    db.commit()
    run_scan(db)
    assert _row(db, "sync_failed:system") is not None
    assert _row(db, "sync_failed:system").status == "open"

    factory.make_sync_run(status="success", started_at=utcnow())
    db.commit()
    run_scan(db)
    assert _row(db, "sync_failed:system").status == "resolved"
    assert failed.status == "failed"


def test_lumirss_failure_owned_externally(db) -> None:  # noqa: ANN001
    # earlier modules may already have created the row (shared DB); reuse it
    row = db.query(Reminder).filter(Reminder.dedup_key == "lumirss_failure:system").first()
    pre_existing = row is not None
    if not pre_existing:
        row = Reminder(
            rule_key="lumirss_failure",
            severity="warning",
            title="LumiRSS 推送失败",
            body="测试插入",
            entity_type="system",
            entity_id="lumirss",
            dedup_key="lumirss_failure:system",
            status="acknowledged",
        )
        db.add(row)
        db.commit()
    row_id = row.id
    try:
        row.status = "acknowledged"
        db.commit()
        run_scan(db)
        fresh = _row(db, "lumirss_failure:system")
        assert fresh is not None and fresh.status == "open"
        assert fresh.id == row_id  # re-opened in place, never re-created
        db.delete(fresh)
        db.commit()
        run_scan(db)
        assert _row(db, "lumirss_failure:system") is None  # never re-created by scan
    finally:
        leftover = db.query(Reminder).filter(Reminder.dedup_key == "lumirss_failure:system").first()
        if pre_existing:
            if leftover is None:
                db.add(
                    Reminder(
                        rule_key="lumirss_failure",
                        severity="warning",
                        title="LumiRSS 推送失败",
                        body="",
                        entity_type="system",
                        entity_id="lumirss",
                        dedup_key="lumirss_failure:system",
                        status="open",
                    )
                )
            else:
                leftover.status = "open"
            db.commit()
        elif leftover is not None:
            db.delete(leftover)
            db.commit()


def test_scan_never_raises_on_dirty_state(db, factory, monkeypatch) -> None:  # noqa: ANN001
    factory.make_up(last_video_at=_days_ago(40))
    db.commit()

    def boom(*_args):  # noqa: ANN002
        raise RuntimeError("settings exploded")

    monkeypatch.setattr("app.services.reminders.get_section_raw", boom)
    assert run_scan(db) == {"created": 0, "resolved": 0}
    monkeypatch.undo()
    assert run_scan(db)["created"] >= 1


def test_acknowledge(db, factory) -> None:  # noqa: ANN001
    up = factory.make_up(last_video_at=_days_ago(40))
    db.commit()
    run_scan(db)
    row = _row(db, f"stale_uploader:{up.mid}")
    assert row is not None
    assert acknowledge(db, row.id) is True
    assert _row(db, f"stale_uploader:{up.mid}").status == "acknowledged"
    assert acknowledge(db, 999_999_999) is False
