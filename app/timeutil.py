"""Canonical time handling for BiliUP Organizer.

Storage convention (unchanged): all DB timestamps are naive UTC strings
``YYYY-MM-DD HH:MM:SS``. The business timezone is fixed to Asia/Shanghai:
day/week boundaries, chart bucketing and API output are defined there, never
by the server host, container or browser timezone. Week = Monday..Sunday,
half-open interval [Mon 00:00, next Mon 00:00) in Shanghai wall clock.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
TZ_NAME = "Asia/Shanghai"
METRICS_VERSION = "2026-10-shanghai-v1"

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
_DATE_FORMAT = "%Y-%m-%d"


def utcnow_naive() -> str:
    """Canonical stored stamp: naive UTC string (matches all existing rows)."""
    return datetime.now(UTC).replace(tzinfo=None).strftime(_TS_FORMAT)


def parse_utc(value: str | None) -> datetime | None:
    """Parse a stored naive-UTC stamp into an aware UTC datetime."""
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for suffix in ("Z", "+00:00"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    try:
        return datetime.strptime(text[:19], _TS_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def to_shanghai(value: str | None) -> datetime | None:
    """Stored naive-UTC stamp -> aware Asia/Shanghai datetime."""
    utc = parse_utc(value)
    return utc.astimezone(SHANGHAI) if utc else None


def shanghai_iso(value: str | None) -> str | None:
    """Stored naive-UTC stamp -> ISO 8601 with explicit +08:00 offset.

    API output contract: consumers must never guess the offset from the
    server host timezone, so every timestamp leaving the API carries one.
    """
    sh = to_shanghai(value)
    return sh.isoformat() if sh else None


def shanghai_date(value: str | None) -> date | None:
    """Stored naive-UTC stamp -> the Asia/Shanghai calendar date it falls on."""
    sh = to_shanghai(value)
    return sh.date() if sh else None


def week_start(day: date) -> date:
    """Monday of the week containing ``day`` (Shanghai calendar)."""
    return day - timedelta(days=day.weekday())


def week_bounds(day: date) -> tuple[date, date]:
    """(Monday, next Monday) of ``day``'s week; end is exclusive."""
    start = week_start(day)
    return start, start + timedelta(days=7)


def week_range_utc(start: date) -> tuple[str, str]:
    """Week starting Shanghai ``start`` (Monday) as naive-UTC string bounds.

    Returns (start_utc, end_utc) such that the SQL predicate
    ``view_at >= start_utc AND view_at < end_utc`` selects exactly the
    records whose Shanghai wall clock falls inside [Mon 00:00, next Mon 00:00).
    """
    begin = datetime(start.year, start.month, start.day, tzinfo=SHANGHAI)
    end = begin + timedelta(days=7)
    return begin.astimezone(UTC).strftime(_TS_FORMAT), end.astimezone(UTC).strftime(_TS_FORMAT)


def day_range_utc(day: date) -> tuple[str, str]:
    """Shanghai calendar day -> naive-UTC [start, end) bounds, same contract
    as week_range_utc."""
    begin = datetime(day.year, day.month, day.day, tzinfo=SHANGHAI)
    end = begin + timedelta(days=1)
    return begin.astimezone(UTC).strftime(_TS_FORMAT), end.astimezone(UTC).strftime(_TS_FORMAT)


def shanghai_today() -> date:
    """Today's date on the Shanghai calendar (never the host's)."""
    return datetime.now(SHANGHAI).date()


def shanghai_hour() -> int:
    return datetime.now(SHANGHAI).hour


def date_range_utc(start: date, end: date) -> tuple[str, str]:
    """Shanghai half-open [start 00:00, end 00:00) -> naive-UTC bounds."""
    begin = datetime(start.year, start.month, start.day, tzinfo=SHANGHAI)
    stop = datetime(end.year, end.month, end.day, tzinfo=SHANGHAI)
    return begin.astimezone(UTC).strftime(_TS_FORMAT), stop.astimezone(UTC).strftime(_TS_FORMAT)


def format_date(day: date) -> str:
    return day.strftime(_DATE_FORMAT)


def parse_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(str(value or "").strip(), _DATE_FORMAT).date()
    except ValueError:
        return None


# Shanghai wall-clock bucketing inside SQL: view_at is naive UTC, so shifting
# +8 hours yields the Shanghai wall clock of each record.
SQL_SHANGHAI_DT = "datetime(view_at, '+8 hours')"
