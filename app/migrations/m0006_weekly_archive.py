"""Schema v6: weekly report archive, UP profile cache, history author
snapshots, idempotent history dedup key and stats indexes.

- weekly_reports: persisted natural-week reports with revisions (replaces the
  single "weekly_report:latest" app_settings row, which is migrated as a
  legacy archive row).
- up_profiles: display-name cache for every mid seen (followed or not).
- watch_authors: per-record author snapshot captured at history-sync time.
- uq_watch_history_bvid_viewat: DB-level dedup key matching the application
  upsert key; exact duplicates from older syncs are removed first (same key,
  lowest id wins).
- stats indexes: (up_mid, view_at) and (bvid) for leaderboard/coverage joins.

Pure ORM/schema-object migration — no hand-written SQL anywhere (SQLite
receives the same compiled DDL whether the database is fresh or upgraded).
"""

from __future__ import annotations

import logging

from sqlalchemy import Index, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import (
    AppSetting,
    Base,
    UpProfile,
    WatchAuthor,
    WatchHistory,
    WeeklyReport,
)

log = logging.getLogger(__name__)

_IDX_UP_VIEW = Index("ix_watch_history_up_view", WatchHistory.up_mid, WatchHistory.view_at)
_IDX_BVID = Index("ix_watch_history_bvid", WatchHistory.bvid)
_IDX_WEEKLY_PERIOD = Index("ix_weekly_reports_period", WeeklyReport.period_start)
_UQ_BVID_VIEWAT = Index("uq_watch_history_bvid_viewat", WatchHistory.bvid, WatchHistory.view_at, unique=True)
_LEGACY_KEY = "weekly_report:latest"


def upgrade(engine: Engine) -> None:
    inspector = inspect(engine)
    Base.metadata.create_all(
        engine,
        tables=[WeeklyReport.__table__, UpProfile.__table__, WatchAuthor.__table__],
    )
    existing_wh = {idx["name"] for idx in inspector.get_indexes("watch_history")}
    existing_weekly = {idx["name"] for idx in inspector.get_indexes("weekly_reports")}
    if "ix_watch_history_up_view" not in existing_wh:
        _IDX_UP_VIEW.create(engine)
    if "ix_watch_history_bvid" not in existing_wh:
        _IDX_BVID.create(engine)
    if "ix_weekly_reports_period" not in existing_weekly:
        _IDX_WEEKLY_PERIOD.create(engine)
    if "uq_watch_history_bvid_viewat" not in existing_wh:
        _UQ_BVID_VIEWAT.create(engine)

    with Session(engine) as session:
        # dedup to the unique (bvid, view_at) key: lowest id per pair wins
        min_ids = (
            select(func.min(WatchHistory.id))
            .group_by(WatchHistory.bvid, WatchHistory.view_at)
            .scalar_subquery()
        )
        removed = (
            session.query(WatchHistory)
            .filter(WatchHistory.id.not_in(min_ids))
            .delete(synchronize_session=False)
        )
        if removed:
            log.info("removed %d duplicate watch_history rows (bvid+view_at)", removed)
        session.commit()

    _migrate_legacy_report(engine)


def _migrate_legacy_report(engine: Engine) -> None:
    """Carry "weekly_report:latest" into weekly_reports as a legacy archive.

    The legacy row keeps its original HTML and generation time; its period is
    left NULL because a rolling-7-days snapshot cannot be restated as one
    exact natural week after the fact.
    """
    with Session(engine) as session:
        if session.query(WeeklyReport).filter(WeeklyReport.is_legacy.is_(True)).count():
            return
        stored = session.get(AppSetting, _LEGACY_KEY)
        if stored is None:
            return
        try:
            payload = __import__("json").loads(stored.value)
        except (TypeError, ValueError):
            return
        html = str(payload.get("html") or "")
        if not html:
            return
        generated_at = str(payload.get("generated_at") or "")
        session.add(
            WeeklyReport(
                scope="default",
                period_start=None,
                period_end_exclusive=None,
                timezone="Asia/Shanghai",
                metrics_version="legacy",
                revision=1,
                is_legacy=True,
                status="archived",
                generated_at=generated_at,
                html=html,
            )
        )
        session.delete(stored)
        session.commit()
        log.info("migrated legacy weekly_report:latest (generated_at=%s)", generated_at)
