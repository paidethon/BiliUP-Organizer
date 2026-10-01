from __future__ import annotations

import json

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.errors import bad_request
from app.models import AiSuggestion, ClassificationJob, GroupLocal, UpUser, Video
from app.schemas import (
    ClassificationJobCreateIn,
    ClassificationJobListOut,
    ClassificationJobOut,
    ReviewDecideIn,
    ReviewRunIn,
    ReviewStatusOut,
    SuggestionOut,
)
from app.services import memberships, taxonomy
from app.util import utcnow

router = APIRouter(prefix="/review", tags=["review"])


def _recent_videos_by_mid(db: DbSession, mids: list[int]) -> dict[int, list[dict]]:
    """Latest 3 uploads per UP from a single IN query."""
    if not mids:
        return {}
    rows = (
        db.query(Video.up_mid, Video.bvid, Video.title, Video.pubdate)
        .filter(Video.up_mid.in_(mids))
        .order_by(Video.up_mid.asc(), Video.pubdate.desc())
        .all()
    )
    out: dict[int, list[dict]] = {}
    for up_mid, bvid, title, pubdate in rows:
        bucket = out.setdefault(up_mid, [])
        if len(bucket) >= 3:
            continue
        bucket.append({"bvid": bvid, "title": title, "pubdate": pubdate})
    return out


@router.get("/queue")
def review_queue(
    admin: CurrentAdmin,
    db: DbSession,
    status: str = "pending",
    min_confidence: float | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
    changed_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
) -> dict:
    if status not in ("pending", "accepted", "rejected", "unclassifiable", "all"):
        raise bad_request(f"unknown status: {status}")
    query = db.query(AiSuggestion)
    if status != "all":
        query = query.filter(AiSuggestion.status == status)
    if min_confidence is not None:
        query = query.filter(AiSuggestion.confidence >= min_confidence)
    if max_confidence is not None:
        query = query.filter(AiSuggestion.confidence <= max_confidence)
    if changed_only:
        query = query.filter(
            AiSuggestion.previous_group_name.is_not(None),
            AiSuggestion.previous_group_name != AiSuggestion.suggested_group_name,
        )
    total = query.count()
    rows = query.order_by(AiSuggestion.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    mids = [row.up_mid for row in rows]
    ups: dict[int, UpUser] = {}
    if mids:
        ups = {up.mid: up for up in db.query(UpUser).filter(UpUser.mid.in_(mids)).all()}
    group_ids = {up.group_id for up in ups.values() if up.group_id is not None}
    group_names: dict[int, str] = {}
    if group_ids:
        rows_ = db.query(GroupLocal.id, GroupLocal.name).filter(GroupLocal.id.in_(group_ids)).all()
        group_names = {gid: name for gid, name in rows_}
    labels = taxonomy.status_labels_of_many(db, mids)
    videos = _recent_videos_by_mid(db, mids)

    items: list[SuggestionOut] = []
    for s in rows:
        data = SuggestionOut.model_validate(s).model_dump()
        up = ups.get(s.up_mid)
        data["up_uname"] = up.uname if up else ""
        data["up_face"] = up.face if up else ""
        data["current_group_name"] = group_names.get(up.group_id) if up is not None else None
        data["status_labels"] = labels.get(s.up_mid, [])
        data["recent_videos"] = videos.get(s.up_mid, [])
        items.append(SuggestionOut(**data))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/decide")
def decide(payload: ReviewDecideIn, admin: CurrentAdmin, db: DbSession) -> dict:
    if payload.decision not in ("accept", "reject", "unclassifiable"):
        raise bad_request("decision must be accept, reject or unclassifiable")
    rows = (
        db.query(AiSuggestion)
        .filter(AiSuggestion.id.in_(payload.ids), AiSuggestion.status == "pending")
        .all()
    )
    applied = 0
    for s in rows:
        s.decided_at = utcnow()
        up = db.query(UpUser).filter(UpUser.mid == s.up_mid).first()
        if payload.decision == "accept":
            s.status = "accepted"
            group = db.get(GroupLocal, s.suggested_group_id) if s.suggested_group_id else None
            if group is None and s.suggested_group_name:
                # the suggested name is the contract; creation stays allowed
                # even when the classifier was not allowed to create groups
                group, _created = taxonomy.ensure_group(db, s.suggested_group_name, allow_create=True)
            if group is not None and up is not None:
                up.group_id = group.id  # primary
                memberships.add_membership(db, up, group.id)
                try:
                    tags = json.loads(s.suggested_tags or "[]")
                except json.JSONDecodeError:
                    tags = []
                if isinstance(tags, list) and tags:
                    taxonomy.set_up_tags(db, up.mid, [str(t) for t in tags], source="ai")
                taxonomy.clear_status_labels(db, up.mid, ["待整理", "无法确定"])
                up.ai_status = "done"
                applied += 1
        elif payload.decision == "reject":
            s.status = "rejected"
        else:  # unclassifiable
            s.status = "unclassifiable"
            if up is not None:
                taxonomy.set_status_labels(db, up.mid, ["待整理"], source="ai")
                up.ai_status = "done"
    db.commit()
    log_action(
        db,
        admin.username,
        "review.decide",
        detail={"decision": payload.decision, "ids": payload.ids, "applied": applied},
    )
    return {"ok": True, "decided": len(rows), "applied": applied}


@router.post("/run")
def run_review(payload: ReviewRunIn, admin: CurrentAdmin, db: DbSession) -> dict:
    settings = get_settings()
    if settings.demo_mode:
        from app.demo import review_run

        return review_run(payload.batch_size)
    from app.services.ai_classifier import classify_batch, pick_up_mids
    from app.services.settings_store import get_section_raw

    ai = get_section_raw(db, "ai")
    instruction = payload.instruction.strip()
    if not instruction:
        # fall back to the saved grouping guidance so the review page can send
        # one-off requirements while the settings page keeps a standing one
        instruction = str(ai.get("grouping_instructions") or "").strip()
    auto_apply = payload.auto_apply if payload.auto_apply is not None else bool(ai.get("auto_apply_enabled"))
    threshold = (
        payload.threshold if payload.threshold is not None else float(ai.get("auto_apply_threshold") or 0.9)
    )
    mids = pick_up_mids(db, payload.batch_size)
    stats = classify_batch(db, mids, instruction=instruction, auto_apply=auto_apply, threshold=threshold)
    log_action(db, admin.username, "review.run", detail=stats)
    return stats


@router.get("/status", response_model=ReviewStatusOut)
def review_status(admin: CurrentAdmin, db: DbSession) -> ReviewStatusOut:
    settings = get_settings()
    pending = db.query(AiSuggestion).filter(AiSuggestion.status == "pending").count()
    unclassifiable = db.query(AiSuggestion).filter(AiSuggestion.status == "unclassifiable").count()
    if settings.demo_mode:
        return ReviewStatusOut(
            configured=True, model="demo-model", pending_count=pending, unclassifiable_count=unclassifiable
        )
    from app.services.settings_store import get_section_raw

    ai = get_section_raw(db, "ai")
    configured = bool(ai.get("base_url")) and bool(ai.get("api_key")) and bool(ai.get("model"))
    last = db.query(func.max(AiSuggestion.created_at)).scalar()
    return ReviewStatusOut(
        configured=configured,
        model=str(ai.get("model") or ""),
        pending_count=pending,
        last_run=last,
        unclassifiable_count=unclassifiable,
    )


@router.post("/jobs", response_model=ClassificationJobOut)
def create_classification_job(
    payload: ClassificationJobCreateIn, admin: CurrentAdmin, db: DbSession
) -> ClassificationJobOut:
    from app.services import classification_jobs

    job = classification_jobs.create_job(db, payload)
    classification_jobs.start_thread(job.id)
    log_action(
        db,
        admin.username,
        "review.job_create",
        entity_type="classification_job",
        entity_id=job.id,
        detail={
            "kind": job.kind,
            "total": job.total,
            "auto_apply": job.auto_apply,
            "threshold": job.threshold,
        },
    )
    return ClassificationJobOut.model_validate(job)


@router.get("/jobs/current")
def current_classification_job(admin: CurrentAdmin, db: DbSession) -> dict | None:
    from app.services import classification_jobs

    job = classification_jobs.get_current_job(db)
    if job is None:
        return None
    return ClassificationJobOut.model_validate(job).model_dump()


@router.get("/jobs", response_model=ClassificationJobListOut)
def list_classification_jobs(admin: CurrentAdmin, db: DbSession) -> ClassificationJobListOut:
    from app.services import classification_jobs

    rows = classification_jobs.list_jobs(db)
    return ClassificationJobListOut(items=[ClassificationJobOut.model_validate(j) for j in rows])


def _job_action(
    job_id: int, admin: CurrentAdmin, db: DbSession, action: str, audit: str
) -> ClassificationJob:
    from app.services import classification_jobs

    job: ClassificationJob = getattr(classification_jobs, action)(db, job_id)
    log_action(
        db,
        admin.username,
        audit,
        entity_type="classification_job",
        entity_id=job_id,
        detail={"status": job.status},
    )
    return job


@router.post("/jobs/{job_id}/pause", response_model=ClassificationJobOut)
def pause_classification_job(job_id: int, admin: CurrentAdmin, db: DbSession) -> ClassificationJobOut:
    return ClassificationJobOut.model_validate(
        _job_action(job_id, admin, db, "pause_job", "review.job_pause")
    )


@router.post("/jobs/{job_id}/resume", response_model=ClassificationJobOut)
def resume_classification_job(job_id: int, admin: CurrentAdmin, db: DbSession) -> ClassificationJobOut:
    return ClassificationJobOut.model_validate(
        _job_action(job_id, admin, db, "resume_job", "review.job_resume")
    )


@router.post("/jobs/{job_id}/cancel", response_model=ClassificationJobOut)
def cancel_classification_job(job_id: int, admin: CurrentAdmin, db: DbSession) -> ClassificationJobOut:
    return ClassificationJobOut.model_validate(
        _job_action(job_id, admin, db, "cancel_job", "review.job_cancel")
    )


@router.post("/jobs/{job_id}/retry-failures", response_model=ClassificationJobOut)
def retry_classification_job(job_id: int, admin: CurrentAdmin, db: DbSession) -> ClassificationJobOut:
    return ClassificationJobOut.model_validate(
        _job_action(job_id, admin, db, "retry_failures", "review.job_retry")
    )
