from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job(name: str, fn):  # noqa: ANN001, ANN202
    def _wrapped() -> None:
        from app.db import get_session_factory

        session = get_session_factory()()
        try:
            fn(session)
        except Exception:  # noqa: BLE001 — scheduled jobs must never crash the process
            log.exception("scheduled job %s failed", name)
        finally:
            session.close()

    return _wrapped


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.enable_scheduler or settings.app_env == "test":
        return None
    if _scheduler is not None:
        return _scheduler

    from app.services import sync as sync_service
    from app.services import weekly_report
    from app.services.lumirss import push_pending
    from app.services.reminders import run_scan

    def _weekly(db):  # noqa: ANN001
        from app.api.weekly_routes import store_report

        html = weekly_report.build_report(db)
        store_report(db, html)
        weekly_report.send_weekly(db)

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _job("followings_sync", lambda db: sync_service.run_sync_kind(db, "followings")),
        "interval",
        hours=6,
        id="followings_sync",
        max_instances=1,
        coalesce=True,
        next_run_time=None,
    )
    _scheduler.add_job(
        _job("watch_history_sync", lambda db: sync_service.run_sync_kind(db, "watch_history")),
        "interval",
        hours=2,
        id="watch_history_sync",
        max_instances=1,
        coalesce=True,
        next_run_time=None,
    )
    _scheduler.add_job(
        _job("reminder_scan", run_scan),
        "interval",
        minutes=30,
        id="reminder_scan",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _job("lumirss_push", push_pending),
        "interval",
        minutes=5,
        id="lumirss_push",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _job("weekly_report", _weekly),
        "cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        id="weekly_report",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _job("scheduled_backup", lambda db: _backup(db)),
        "cron",
        hour=3,
        minute=0,
        id="scheduled_backup",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("scheduler started with %d jobs", len(_scheduler.get_jobs()))
    return _scheduler


def _backup(db) -> None:  # noqa: ANN001
    from app.api.system_routes import create_backup_file

    create_backup_file(db, note="scheduled daily backup", kind="scheduled")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
