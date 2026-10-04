from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-jobs-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.db import get_session_factory  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AiSuggestion, ClassificationJob, UpUser  # noqa: E402
from app.schemas import ClassificationJobCreateIn  # noqa: E402
from app.services import classification_jobs, taxonomy  # noqa: E402


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


def _wait_status(
    db,
    job_id: int,
    statuses: tuple[str, ...],
    timeout: float = 15.0,  # noqa: ANN001
) -> ClassificationJob:
    deadline = time.monotonic() + timeout
    job: ClassificationJob | None = None
    while time.monotonic() < deadline:
        db.expire_all()
        job = db.get(ClassificationJob, job_id)
        if job is not None and job.status in statuses:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} stuck in status {job.status if job else None}, wanted {statuses}")


def _fast_demo(db, mids, auto_apply=False, threshold=0.9):  # noqa: ANN001, ARG001
    """Deterministic stand-in for demo_classify_batch: no DB writes."""
    applied = len(mids) if auto_apply else 0
    return {
        "classified": len(mids),
        "auto_applied": applied,
        "needs_review": len(mids) - applied,
        "unclassifiable": 0,
        "failed": 0,
        "created_groups": [],
    }


def test_demo_classify_batch_three_tiers(db) -> None:  # noqa: ANN001
    from app.demo import demo_classify_batch

    base = 920_000_000

    def with_mod(mod: int) -> int:
        return base + ((mod - base % mod) % mod)

    mid_fail = with_mod(17)  # %17 == 0 -> failure path
    mid_unc = with_mod(5)  # %5 == 0 -> unclassifiable
    mid_pend = with_mod(3)  # %3 == 0 -> pending review
    mid_apply = base
    while mid_apply % 17 == 0 or mid_apply % 5 == 0 or mid_apply % 3 == 0:
        mid_apply += 1  # no hit -> high confidence
    mids = [mid_fail, mid_unc, mid_pend, mid_apply]
    for i, mid in enumerate(mids):
        # watched_count=1 keeps these UPs out of the weekly-report test's
        # top-10 never-watched cutoff (the database is shared module-wide)
        db.add(UpUser(mid=mid, uname=f"任务UP{i}", followed_at="2001-01-01 00:00:00", watched_count=1))
    db.commit()

    result = demo_classify_batch(db, mids, auto_apply=True, threshold=0.9)
    assert result["failed"] == 1
    assert result["unclassifiable"] == 1
    assert result["needs_review"] == 1
    assert result["auto_applied"] == 1
    assert result["classified"] == 2

    db.expire_all()
    assert db.query(UpUser).filter(UpUser.mid == mid_fail).first().ai_status == "error"
    assert db.query(UpUser).filter(UpUser.mid == mid_unc).first().ai_status == "done"
    assert "待整理" in taxonomy.status_labels_of(db, mid_unc)
    assert db.query(UpUser).filter(UpUser.mid == mid_pend).first().ai_status == "pending"

    applied_up = db.query(UpUser).filter(UpUser.mid == mid_apply).first()
    assert applied_up.ai_status == "done" and applied_up.group_id is not None
    suggestion = (
        db.query(AiSuggestion)
        .filter(AiSuggestion.up_mid == mid_apply)
        .order_by(AiSuggestion.id.desc())
        .first()
    )
    assert suggestion.status == "accepted"
    assert suggestion.provider == "demo" and suggestion.prompt_version == "v2"
    assert json.loads(suggestion.evidence)["video_count"] == 0


def test_full_job_completes(db, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("app.demo.demo_classify_batch", _fast_demo)
    total = db.query(UpUser.mid).filter(UpUser.missing.is_(False)).count()
    assert total > 0
    job = classification_jobs.create_job(db, ClassificationJobCreateIn(kind="full", batch_size=100))
    assert job.total == total
    classification_jobs.start_thread(job.id)
    job = _wait_status(db, job.id, ("completed",))
    assert job.processed == total
    assert job.classified == total
    assert job.needs_review == total
    assert job.auto_applied == 0
    assert job.failed == 0
    assert job.finished_at is not None


def test_cancel_job(db) -> None:  # noqa: ANN001
    job = classification_jobs.create_job(db, ClassificationJobCreateIn(kind="pending", batch_size=5))
    cancelled = classification_jobs.cancel_job(db, job.id)
    assert cancelled.status == "cancelled" and cancelled.finished_at is not None
    with pytest.raises(ApiError):
        classification_jobs.cancel_job(db, job.id)


def test_create_conflicts_with_active_job(db) -> None:  # noqa: ANN001
    job = classification_jobs.create_job(db, ClassificationJobCreateIn(kind="pending", batch_size=5))
    with pytest.raises(ApiError) as excinfo:
        classification_jobs.create_job(db, ClassificationJobCreateIn(kind="full", batch_size=5))
    assert excinfo.value.status_code == 400
    classification_jobs.cancel_job(db, job.id)


def test_pause_and_resume(db, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("app.demo.demo_classify_batch", _fast_demo)
    job = classification_jobs.create_job(db, ClassificationJobCreateIn(kind="pending", batch_size=50))
    assert job.status == "running"
    paused = classification_jobs.pause_job(db, job.id)
    assert paused.status == "paused"
    with pytest.raises(ApiError):
        classification_jobs.pause_job(db, job.id)  # only running jobs pause
    resumed = classification_jobs.resume_job(db, job.id)
    assert resumed.status == "running"
    job = _wait_status(db, job.id, ("completed", "failed"))
    assert job.status == "completed"


def test_recover_interrupted_jobs_marks_paused(db) -> None:  # noqa: ANN001
    job = classification_jobs.create_job(db, ClassificationJobCreateIn(kind="pending", batch_size=5))
    assert job.status == "running"
    recovered = classification_jobs.recover_interrupted_jobs()
    assert recovered >= 1
    db.expire_all()
    assert db.get(ClassificationJob, job.id).status == "paused"
    classification_jobs.cancel_job(db, job.id)


def test_retry_failures_requeues_failed_mids(db) -> None:  # noqa: ANN001
    job = classification_jobs.create_job(db, ClassificationJobCreateIn(kind="pending", batch_size=5))
    mids = [930000001, 930000002, 930000003]
    job.cursor_json = json.dumps({"mids": mids, "index": 3, "failed": mids})
    job.processed = 3
    job.failed = 3
    job.status = "completed"
    db.commit()

    retried = classification_jobs.retry_failures(db, job.id)
    assert retried.status == "running"
    assert retried.failed == 0
    assert retried.processed == 0
    cursor = json.loads(retried.cursor_json)
    assert cursor["mids"] == mids
    assert cursor["index"] == 0
    assert cursor["failed"] == []

    # the runner thread reruns the (nonexistent) mids: each counts as failed
    # but the job itself still completes
    job = _wait_status(db, job.id, ("completed", "failed"))
    assert job.status == "completed"
    assert job.processed == 3
    assert job.failed == 3
