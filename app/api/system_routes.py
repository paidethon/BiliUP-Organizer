from __future__ import annotations

import shutil
import sqlite3

from fastapi import APIRouter, UploadFile
from fastapi.responses import FileResponse

from app import __version__
from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.db import checkpoint_wal, get_engine
from app.errors import bad_request, not_found
from app.models import (
    AiSuggestion,
    AuditLog,
    Backup,
    GroupLocal,
    Reminder,
    SyncRun,
    UpUser,
    Video,
)
from app.schemas import AuditOut, BackupOut, StatsOut, SystemInfoOut
from app.util import utcnow

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/stats", response_model=StatsOut)
def stats(admin: CurrentAdmin, db: DbSession) -> StatsOut:
    from app.auth import get_bilibili_account

    total = db.query(UpUser).count()
    grouped = db.query(UpUser).filter(UpUser.group_id.isnot(None)).count()
    missing = db.query(UpUser).filter(UpUser.missing.is_(True)).count()
    last_sync = db.query(SyncRun).filter(SyncRun.status == "success").order_by(SyncRun.id.desc()).first()
    return StatsOut(
        total_ups=total,
        grouped_ups=grouped,
        ungrouped_ups=total - grouped,
        missing_ups=missing,
        groups=db.query(GroupLocal).count(),
        open_reminders=db.query(Reminder).filter(Reminder.status == "open").count(),
        pending_suggestions=db.query(AiSuggestion).filter(AiSuggestion.status == "pending").count(),
        videos_tracked=db.query(Video).count(),
        last_sync=last_sync.finished_at if last_sync else None,
        login_status=get_bilibili_account(db).login_status,
    )


@router.get("/audit", response_model=list[AuditOut])
def audit_list(admin: CurrentAdmin, db: DbSession, page: int = 1, page_size: int = 50) -> list[AuditOut]:
    rows = (
        db.query(AuditLog).order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    )
    return [AuditOut.model_validate(r) for r in rows]


@router.get("/backups", response_model=list[BackupOut])
def list_backups(admin: CurrentAdmin, db: DbSession) -> list[BackupOut]:
    rows = db.query(Backup).order_by(Backup.id.desc()).all()
    return [BackupOut.model_validate(r) for r in rows]


@router.post("/backups", response_model=BackupOut)
def create_backup(admin: CurrentAdmin, db: DbSession, note: str = "") -> BackupOut:
    row = create_backup_file(db, note=note)
    log_action(db, admin.username, "system.backup_create", entity_type="backup", entity_id=row.id)
    return BackupOut.model_validate(row)


def create_backup_file(db, note: str = "", kind: str = "manual"):  # noqa: ANN001
    settings = get_settings()
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    filename = f"biliup-{utcnow().replace(' ', '_').replace(':', '')}.db"
    target = settings.backups_dir / filename
    checkpoint_wal()
    src = sqlite3.connect(str(settings.db_path))
    dst = sqlite3.connect(str(target))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    row = Backup(filename=filename, size_bytes=target.stat().st_size, kind=kind, note=note)
    db.add(row)
    db.commit()
    return row


@router.get("/backups/{backup_id}/download")
def download_backup(backup_id: int, admin: CurrentAdmin, db: DbSession) -> FileResponse:
    row = db.get(Backup, backup_id)
    if row is None:
        raise not_found(f"backup {backup_id} not found")
    path = get_settings().backups_dir / row.filename
    if not path.exists():
        raise not_found("backup file missing on disk")
    return FileResponse(path, filename=row.filename, media_type="application/octet-stream")


@router.post("/backups/restore")
def restore_backup(admin: CurrentAdmin, db: DbSession, file: UploadFile) -> dict:
    """Restore from an uploaded .db file. The DB is replaced on disk; a restart
    is required afterwards (container restart reopens the file cleanly)."""
    settings = get_settings()
    data = file.file.read()
    if not data.startswith(b"SQLite format 3"):
        raise bad_request("uploaded file is not a SQLite database")
    tmp_path = settings.backups_dir / "restore-incoming.db"
    tmp_path.write_bytes(data)
    check = sqlite3.connect(str(tmp_path))
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise bad_request("uploaded database failed integrity check")
    finally:
        check.close()

    checkpoint_wal()
    engine = get_engine()
    engine.dispose()
    target = settings.db_path
    backup_before = target.with_suffix(".before-restore.db")
    if target.exists():
        shutil.copy2(target, backup_before)
    shutil.move(str(tmp_path), str(target))
    log_action(
        db,
        admin.username,
        "system.backup_restore",
        detail={"uploaded_bytes": len(data), "previous_saved": backup_before.name},
    )
    return {
        "ok": True,
        "message": "database restored; restart the app to reconnect",
        "previous_saved_as": backup_before.name,
    }


@router.get("/info", response_model=SystemInfoOut)
def info(admin: CurrentAdmin) -> SystemInfoOut:
    settings = get_settings()
    return SystemInfoOut(
        version=__version__,
        app_env=settings.app_env,
        demo_mode=settings.demo_mode,
        scheduler_enabled=settings.enable_scheduler,
    )
