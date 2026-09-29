from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.errors import bad_request, not_found
from app.models import Reminder
from app.schemas import ReminderOut, ReminderScanOut

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("", response_model=list[ReminderOut])
def list_reminders(
    admin: CurrentAdmin,
    db: DbSession,
    status: str = "open",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, le=500),
) -> list[ReminderOut]:
    if status not in ("open", "acknowledged", "resolved", "all"):
        raise bad_request(f"unknown status: {status}")
    query = db.query(Reminder)
    if status != "all":
        query = query.filter(Reminder.status == status)
    rows = query.order_by(Reminder.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [ReminderOut.model_validate(r) for r in rows]


@router.post("/{reminder_id}/ack")
def ack_reminder(reminder_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    row = db.get(Reminder, reminder_id)
    if row is None:
        raise not_found(f"reminder {reminder_id} not found")
    row.status = "acknowledged"
    db.commit()
    return {"ok": True}


@router.post("/ack-all")
def ack_all(admin: CurrentAdmin, db: DbSession) -> dict:
    count = db.query(Reminder).filter(Reminder.status == "open").update({"status": "acknowledged"})
    db.commit()
    log_action(db, admin.username, "reminders.ack_all", detail={"count": count})
    return {"ok": True, "acknowledged": count}


@router.post("/scan", response_model=ReminderScanOut)
def scan(admin: CurrentAdmin, db: DbSession) -> ReminderScanOut:
    from app.services.reminders import run_scan

    result = run_scan(db)
    log_action(db, admin.username, "reminders.scan", detail=result)
    return ReminderScanOut(**result)
