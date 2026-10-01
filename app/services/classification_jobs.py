"""Persistent full-library classification jobs, driven by a daemon thread.

The runner re-reads the job row from a fresh session every batch, so pause /
cancel take effect between batches and the cursor ({"mids", "index",
"failed"}) survives restarts. Batch-level failures are recorded per mid and
never abort the job; only unexpected errors flip it to "failed".
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session_factory
from app.errors import bad_request, not_found
from app.models import ClassificationJob, UpUser
from app.schemas import ClassificationJobCreateIn
from app.util import utcnow

log = logging.getLogger(__name__)

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_JOBS: set[int] = set()


def _load_cursor(raw: str | None) -> dict[str, Any]:
    try:
        cursor = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"mids": [], "index": 0, "failed": []}
    if not isinstance(cursor, dict):
        return {"mids": [], "index": 0, "failed": []}
    cursor.setdefault("mids", [])
    cursor.setdefault("index", 0)
    cursor.setdefault("failed", [])
    return cursor


def _target_mids(db: Session, kind: str) -> list[int]:
    query = db.query(UpUser.mid).filter(UpUser.missing.is_(False))
    if kind == "pending":
        query = query.filter(UpUser.ai_status.in_(("none", "error")))
    elif kind != "full":
        raise bad_request(f"unknown job kind: {kind}")
    rows = query.order_by(UpUser.followed_at.asc(), UpUser.mid.asc()).all()
    return [row[0] for row in rows]


def create_job(db: Session, payload: ClassificationJobCreateIn) -> ClassificationJob:
    """Create a job row; at most one running/paused job may exist so repeated
    clicks cannot double-classify the library."""
    active = db.query(ClassificationJob).filter(ClassificationJob.status.in_(("running", "paused"))).first()
    if active is not None:
        raise bad_request("classification_job_active")
    mids = _target_mids(db, payload.kind)
    job = ClassificationJob(
        kind=payload.kind,
        status="running",
        batch_size=payload.batch_size,
        auto_apply=payload.auto_apply,
        threshold=payload.threshold,
        total=len(mids),
        cursor_json=json.dumps({"mids": mids, "index": 0, "failed": []}, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    return job


def start_thread(job_id: int) -> None:
    """Spawn the runner thread; a module-level registry keeps one thread per
    job even when callers race (create/resume/retry)."""
    with _ACTIVE_LOCK:
        if job_id in _ACTIVE_JOBS:
            return
        _ACTIVE_JOBS.add(job_id)
    threading.Thread(target=_run_job, args=(job_id,), daemon=True, name=f"classify-{job_id}").start()


def _classify_batch(db: Session, mids: list[int], job: ClassificationJob) -> dict:
    """Dispatch to the demo simulator or the real classifier."""
    if get_settings().demo_mode:
        from app.demo import demo_classify_batch

        return demo_classify_batch(db, mids, auto_apply=job.auto_apply, threshold=job.threshold)
    from app.services.ai_classifier import classify_batch

    return classify_batch(db, mids, auto_apply=job.auto_apply, threshold=job.threshold)


def _run_job(job_id: int) -> None:
    try:
        _run_job_inner(job_id)
    except Exception:  # noqa: BLE001 - a job must never take the process down
        log.exception("classification job %s crashed", job_id)
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_JOBS.discard(job_id)


def _run_job_inner(job_id: int) -> None:
    db = get_session_factory()()
    try:
        while True:
            # re-read with a fresh SELECT every batch so pauses/cancels from
            # other sessions are seen immediately
            db.expire_all()
            job = db.get(ClassificationJob, job_id)
            if job is None or job.status != "running":
                return
            cursor = _load_cursor(job.cursor_json)
            mids: list[int] = list(cursor["mids"])
            index: int = int(cursor["index"])
            failed_mids: list[int] = list(cursor["failed"])
            batch = mids[index : index + job.batch_size]
            if not batch:
                job.status = "completed"
                job.finished_at = utcnow()
                db.commit()
                return
            try:
                result = _classify_batch(db, batch, job)
            except Exception:  # noqa: BLE001 - batch failure never stops the job
                db.rollback()
                for mid in batch:
                    if mid not in failed_mids:
                        failed_mids.append(mid)
                    up = db.query(UpUser).filter(UpUser.mid == mid).first()
                    if up is not None:
                        up.ai_status = "error"
                result = {
                    "classified": 0,
                    "auto_applied": 0,
                    "needs_review": 0,
                    "unclassifiable": 0,
                    "failed": len(batch),
                    "created_groups": [],
                }
                db.commit()
            db.expire_all()
            job = db.get(ClassificationJob, job_id)
            if job is None or job.status != "running":
                return
            errored = {
                row[0]
                for row in db.query(UpUser.mid)
                .filter(UpUser.mid.in_(batch), UpUser.ai_status == "error")
                .all()
            }
            for mid in batch:
                if mid in errored and mid not in failed_mids:
                    failed_mids.append(mid)
            job.processed += len(batch)
            job.classified += int(result.get("classified", 0))
            job.auto_applied += int(result.get("auto_applied", 0))
            job.needs_review += int(result.get("needs_review", 0))
            job.unclassifiable += int(result.get("unclassifiable", 0))
            job.failed += int(result.get("failed", 0))
            job.cursor_json = json.dumps(
                {"mids": mids, "index": index + len(batch), "failed": failed_mids},
                ensure_ascii=False,
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - unexpected: mark the job failed
        db.rollback()
        job = db.get(ClassificationJob, job_id)
        if job is not None and job.status == "running":
            job.status = "failed"
            job.error = str(exc)[:2000]
            job.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def _get_job(db: Session, job_id: int) -> ClassificationJob:
    job = db.get(ClassificationJob, job_id)
    if job is None:
        raise not_found(f"classification job {job_id} not found")
    return job


def pause_job(db: Session, job_id: int) -> ClassificationJob:
    job = _get_job(db, job_id)
    if job.status != "running":
        raise bad_request("classification_job_not_running")
    job.status = "paused"
    db.commit()
    return job


def resume_job(db: Session, job_id: int) -> ClassificationJob:
    job = _get_job(db, job_id)
    if job.status != "paused":
        raise bad_request("classification_job_not_paused")
    job.status = "running"
    db.commit()
    start_thread(job_id)
    return job


def cancel_job(db: Session, job_id: int) -> ClassificationJob:
    job = _get_job(db, job_id)
    if job.status not in ("running", "paused"):
        raise bad_request("classification_job_not_active")
    job.status = "cancelled"
    job.finished_at = utcnow()
    db.commit()
    return job


def retry_failures(db: Session, job_id: int) -> ClassificationJob:
    """Requeue only the failed mids; counters for them are rolled back so the
    retried batches count towards the same totals."""
    job = _get_job(db, job_id)
    if job.status not in ("completed", "failed", "paused"):
        raise bad_request("classification_job_not_retryable")
    cursor = _load_cursor(job.cursor_json)
    failed_mids = list(cursor["failed"])
    if job.failed <= 0 or not failed_mids:
        raise bad_request("classification_job_no_failures")
    job.cursor_json = json.dumps({"mids": failed_mids, "index": 0, "failed": []}, ensure_ascii=False)
    job.processed = max(0, job.processed - len(failed_mids))
    job.failed = 0
    job.status = "running"
    job.error = None
    job.finished_at = None
    db.commit()
    start_thread(job_id)
    return job


def get_current_job(db: Session) -> ClassificationJob | None:
    return db.query(ClassificationJob).order_by(ClassificationJob.id.desc()).first()


def list_jobs(db: Session, limit: int = 10) -> list[ClassificationJob]:
    return db.query(ClassificationJob).order_by(ClassificationJob.id.desc()).limit(limit).all()


def recover_interrupted_jobs() -> int:
    """Startup hook: a job still marked running belongs to a dead process, so
    it becomes paused and can be resumed by the user."""
    db = get_session_factory()()
    try:
        rows = db.query(ClassificationJob).filter(ClassificationJob.status == "running").all()
        for job in rows:
            job.status = "paused"
        if rows:
            db.commit()
        return len(rows)
    finally:
        db.close()
