"""Timezone-correct statistics (T1/T2/T8/T9).

Every bucket is Asia/Shanghai wall clock over naive-UTC stored stamps: weeks
are Monday..Sunday half-open, day/hour/weekday buckets shift +8h inside SQL,
and week boundaries survive year changes. Also pinned here: watch-second
semantics per record (point / finished / bound / unknown), Shanghai day
bucketing at the 00:00 boundary, C4 per-UP deltas, C6 new vs returning UPs,
the C2 previous-period payload and the T9 incomplete-week flags.

Bound samples (progress > 0 without a usable duration) count progress as a
lower bound: included in watch_seconds_est, excluded from averages, and
reported separately in samples.bound. The NULL-duration case is covered by a
NULL-safe SQL predicate (NOT (NULL > 0) would be NULL under three-valued
logic).
"""

from __future__ import annotations

import itertools
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-stats-")))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.models import Base, UpUser, WatchHistory  # noqa: E402
from app.services import stats  # noqa: E402
from app.timeutil import (  # noqa: E402
    day_range_utc,
    format_date,
    parse_utc,
    shanghai_date,
    shanghai_iso,
    week_range_utc,
    week_start,
)

_TS = "%Y-%m-%d %H:%M:%S"
_BVIDS = itertools.count(1)

# Fixed observation clock: Shanghai "today" is 2026-10-04 in every test below,
# so zero-fill / is_complete semantics are deterministic.
_NOW = datetime(2026, 10, 4, 10, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _stamp_for_day(shanghai_date: str, hour: int = 4) -> str:
    """Naive-UTC stamp whose Shanghai wall clock falls on shanghai_date."""
    year, month, day = (int(p) for p in shanghai_date.split("-"))
    start_utc, _ = day_range_utc(date(year, month, day))
    return (datetime.strptime(start_utc, _TS) + timedelta(hours=hour)).strftime(_TS)


def add_watch(
    db: Session,
    up_mid: int,
    shanghai_day: str,
    hour: int = 12,
    progress: int = 0,
    duration: int | None = 300,
) -> WatchHistory:
    row = WatchHistory(
        bvid=f"BV1tz{next(_BVIDS)}",
        up_mid=up_mid,
        title="时区测试观看",
        view_at=_stamp_for_day(shanghai_day, hour),
        progress=progress,
        duration_seconds=duration,
    )
    db.add(row)
    return row


# ------------------------------------------------------------------- T1/T2


def test_week_and_day_bounds_are_shanghai_half_open() -> None:
    assert week_range_utc(date(2026, 9, 28)) == ("2026-09-27 16:00:00", "2026-10-04 16:00:00")
    assert day_range_utc(date(2026, 9, 28)) == ("2026-09-27 16:00:00", "2026-09-28 16:00:00")
    # half-open: Sunday 23:59 Shanghai is inside, Monday 00:00 next week is not
    assert "2026-10-04 15:59:59" < "2026-10-04 16:00:00"
    assert week_range_utc(date(2026, 9, 21))[1] == "2026-09-27 16:00:00"


def test_shanghai_iso_always_carries_explicit_offset() -> None:
    assert shanghai_iso("2026-09-27 16:00:00") == "2026-09-28T00:00:00+08:00"
    assert shanghai_iso(None) is None
    assert shanghai_iso("garbage") is None


def test_parse_utc_robustness() -> None:
    expected = datetime(2026, 9, 27, 16, 0, 0, tzinfo=UTC)
    assert parse_utc(None) is None
    assert parse_utc("") is None
    assert parse_utc("   ") is None
    assert parse_utc("garbage") is None
    assert parse_utc("2026-09-27T16:00:00Z") == expected  # Z suffix
    assert parse_utc("2026-09-27 16:00:00+00:00") == expected  # explicit offset
    assert parse_utc("2026-09-27T16:00:00") == expected  # ISO with T, no offset
    assert parse_utc("2026-09-27 16:00:00") == expected  # canonical stored form
    assert parse_utc("2026-09-27 16:00") is None  # incomplete stamp -> None


def test_week_start_crosses_year_boundary() -> None:
    assert week_start(date(2026, 1, 1)) == date(2025, 12, 29)
    assert week_start(date(2026, 10, 4)) == date(2026, 9, 28)  # Sunday -> same week
    assert week_start(date(2026, 9, 28)) == date(2026, 9, 28)  # Monday -> itself


def test_watch_seconds_sample_categories(db: Session) -> None:
    """progress/duration -> contribution matrix, all records in one Shanghai week."""
    db.add(UpUser(mid=101, uname="时长UP"))
    add_watch(db, 101, "2026-09-29", progress=60, duration=300)  # point -> 60
    add_watch(db, 101, "2026-09-29", progress=-1, duration=300)  # finished -> 300
    add_watch(db, 101, "2026-09-29", progress=-1, duration=None)  # unknown -> 0
    add_watch(db, 101, "2026-09-29", progress=45, duration=None)  # bound -> 45 (lower bound)
    add_watch(db, 101, "2026-09-29", progress=0, duration=0)  # unknown
    add_watch(db, 101, "2026-09-29", progress=0, duration=None)  # unknown
    add_watch(db, 101, "2026-09-29", progress=0, duration=300)  # valid, contributes 0
    add_watch(db, 101, "2026-09-29", progress=500, duration=300)  # clipped to 300
    db.commit()

    payload = stats.range_stats(db, date(2026, 9, 28), date(2026, 10, 5), now=_NOW)

    assert payload["views"] == 8
    assert payload["watch_seconds_est"] == 60 + 300 + 45 + 0 + 300  # 705
    assert payload["samples"]["valid"] == 4  # point, finished, zero-progress, clipped
    assert payload["samples"]["bound"] == 1  # NULL-duration row with progress > 0
    assert payload["samples"]["unknown"] == 3  # 8 - 4 valid - 1 bound
    # averages divide by valid samples only (bound rows are excluded)
    assert payload["avg_watch_seconds"] == payload["watch_seconds_est"] // payload["samples"]["valid"]
    assert payload["avg_watch_seconds"] == 176


def test_bound_sample_with_explicit_zero_duration_counts_progress(db: Session) -> None:
    """The documented bound-sample rule, as implemented for duration = 0."""
    add_watch(db, 102, "2026-09-29", progress=45, duration=0)
    db.commit()

    payload = stats.range_stats(db, date(2026, 9, 28), date(2026, 10, 5), now=_NOW)

    assert payload["views"] == 1
    assert payload["watch_seconds_est"] == 45  # progress kept as a lower bound
    assert payload["samples"]["bound"] == 1
    assert payload["samples"]["valid"] == 0
    assert payload["samples"]["unknown"] == 0
    assert payload["avg_watch_seconds"] is None  # bound rows never enter averages


# ------------------------------------------------------ Shanghai bucketing


def test_day_and_hour_buckets_follow_shanghai_wall_clock(db: Session) -> None:
    monday_start = _stamp_for_day("2026-09-28", 0)  # UTC 2026-09-27 16:00:00
    # UTC 2026-09-27 16:30 == Shanghai Monday 2026-09-28 00:30
    monday_0030 = (datetime.strptime(monday_start, _TS) + timedelta(minutes=30)).strftime(_TS)
    # UTC 2026-09-27 15:30 == Shanghai Sunday 2026-09-27 23:30
    sunday_2330 = (datetime.strptime(monday_start, _TS) - timedelta(minutes=30)).strftime(_TS)
    db.add(
        WatchHistory(
            bvid="BV1sun", up_mid=201, title="t", view_at=sunday_2330, progress=-1, duration_seconds=60
        )
    )
    db.add(
        WatchHistory(
            bvid="BV1mon", up_mid=202, title="t", view_at=monday_0030, progress=-1, duration_seconds=60
        )
    )
    db.commit()

    payload = stats.range_stats(db, date(2026, 9, 27), date(2026, 10, 4), now=_NOW)

    daily = {d["date"]: d for d in payload["daily"]}
    assert daily["2026-09-27"]["views"] == 1  # Shanghai Sunday
    assert daily["2026-09-28"]["views"] == 1  # Shanghai Monday
    assert payload["hourly"][23] == 1  # 23:30 Shanghai
    assert payload["hourly"][0] == 1  # 00:30 Shanghai

    weekday = payload["weekday"]
    assert [w["label"] for w in weekday] == ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    values = {w["label"]: w["value"] for w in weekday}
    assert values["周一"] == 1 and values["周日"] == 1
    assert sum(w["value"] for w in weekday) == 2


# ------------------------------------------------------- empty range / T9


def test_empty_range_zero_fills_past_and_marks_future(db: Session) -> None:
    payload = stats.range_stats(db, date(2026, 9, 30), date(2026, 10, 8), now=_NOW)

    assert payload["views"] == 0
    assert payload["watch_seconds_est"] == 0
    assert payload["samples"] == {"valid": 0, "bound": 0, "unknown": 0}
    assert payload["avg_watch_seconds"] is None
    assert payload["distinct_videos"] == 0 and payload["distinct_ups"] == 0

    daily = {d["date"]: d for d in payload["daily"]}
    for past in ("2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"):
        assert daily[past] == {"date": past, "views": 0, "seconds": 0, "covered": True}
    for future in ("2026-10-05", "2026-10-06", "2026-10-07"):
        assert daily[future] == {"date": future, "views": None, "seconds": None, "covered": False}


def test_incomplete_week_flags_partial_days_as_uncovered(db: Session) -> None:
    """T9: an end date in the future means the week is not complete; days that
    have not fully passed must report views=None, never a fake zero."""
    add_watch(db, 210, "2026-09-29", progress=-1, duration=100)
    db.commit()

    partial_now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    payload = stats.range_stats(db, date(2026, 9, 28), date(2026, 10, 5), now=partial_now)

    assert payload["period"]["is_complete"] is False
    assert payload["views"] == 1
    daily = {d["date"]: d for d in payload["daily"]}
    assert daily["2026-09-29"]["views"] == 1 and daily["2026-09-29"]["covered"] is True
    for future in ("2026-10-02", "2026-10-03", "2026-10-04"):
        assert daily[future]["views"] is None and daily[future]["covered"] is False

    # the same week observed on or after its end (2026-10-05 Shanghai) is complete
    complete_now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    later = stats.range_stats(db, date(2026, 9, 28), date(2026, 10, 5), now=complete_now)
    assert later["period"]["is_complete"] is True


# ------------------------------------------------------------------- C6


def test_explore_return_new_vs_returning_ups(db: Session) -> None:
    """C6: baseline is the local saved history. mid 501 is returning (first
    seen 10 days before the range), mid 502 is new (first ever seen in-range)."""
    add_watch(db, 501, "2026-09-04", hour=8)  # first-ever, 10 days before the range
    add_watch(db, 501, "2026-09-15", hour=10)  # returning inside the range
    add_watch(db, 501, "2026-09-16", hour=10)
    add_watch(db, 502, "2026-09-16", hour=20)  # first-ever inside the range
    db.commit()

    payload = stats.range_stats(db, date(2026, 9, 14), date(2026, 9, 21), now=_NOW)
    series = {d["date"]: d for d in payload["explore_return"]}

    assert series["2026-09-15"] == {"date": "2026-09-15", "new_ups": 0, "returning_ups": 1, "covered": True}
    # both active on 09-16: B is new, A returning — categories are exclusive
    assert series["2026-09-16"]["new_ups"] == 1
    assert series["2026-09-16"]["returning_ups"] == 1
    assert series["2026-09-17"] == {"date": "2026-09-17", "new_ups": 0, "returning_ups": 0, "covered": True}
    # every day's two categories sum to exactly that day's distinct UPS
    active_by_day: dict[str, set[int]] = {}
    for row in db.query(WatchHistory).all():
        active_by_day.setdefault(format_date(shanghai_date(row.view_at)), set()).add(row.up_mid)
    for entry in payload["explore_return"]:
        assert entry["new_ups"] + entry["returning_ups"] == len(active_by_day.get(entry["date"], set()))


# ------------------------------------------------------------------- C4


def test_up_delta_aggregates_by_mid_without_up_users(db: Session) -> None:
    """C4: current vs previous week per mid. A mid with watch history but no
    up_users row must still appear (aggregated by mid, name unresolved)."""
    for mid, uname in ((511, "涨粉UP"), (512, "新UP"), (513, "退潮UP")):
        db.add(UpUser(mid=mid, uname=uname))
    for _ in range(5):
        add_watch(db, 511, "2026-09-29", hour=12)
    add_watch(db, 511, "2026-09-23", hour=9)
    add_watch(db, 511, "2026-09-24", hour=9)
    for _ in range(3):
        add_watch(db, 512, "2026-09-30", hour=14)
    add_watch(db, 513, "2026-09-23", hour=15)
    add_watch(db, 513, "2026-09-24", hour=15)
    for _ in range(2):
        add_watch(db, 514, "2026-10-01", hour=16)  # no UpUser row on purpose
    db.commit()

    payload = stats.range_stats(db, date(2026, 9, 28), date(2026, 10, 5), include_prev=True, now=_NOW)

    risers = {item["mid"]: item for item in payload["up_delta"]["risers"]}
    assert risers[511]["delta"] == 3 and risers[511]["change"] == "up"
    assert risers[511]["current"] == 5 and risers[511]["previous"] == 2
    assert risers[512]["change"] == "new" and risers[512]["previous"] == 0
    # history-only mid survives with an unresolved name
    assert risers[514]["uname"] is None and risers[514]["name_source"] is None
    assert risers[514]["delta"] == 2

    fallers = payload["up_delta"]["fallers"]
    assert [f["mid"] for f in fallers] == [513]
    assert fallers[0]["delta"] == -2 and fallers[0]["change"] == "down"


# ------------------------------------------------------------------- C2


def test_previous_period_has_equal_length_and_own_views(db: Session) -> None:
    add_watch(db, 611, "2026-09-29", hour=12)
    add_watch(db, 611, "2026-09-23", hour=12)
    add_watch(db, 611, "2026-09-24", hour=12)
    db.commit()

    payload = stats.range_stats(db, date(2026, 9, 28), date(2026, 10, 5), include_prev=True, now=_NOW)

    prev = payload["previous"]
    assert prev["period"]["start"] == "2026-09-21"
    assert prev["period"]["end_exclusive"] == "2026-09-28"
    span = date(2026, 9, 28) - date(2026, 9, 21)
    assert span == timedelta(days=7)  # equal-length comparable week
    assert prev["views"] == 2
    assert payload["views"] == 1
    assert {d["date"] for d in prev["daily"]} == {f"2026-09-{day}" for day in range(21, 28)}
