from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.config import get_settings
from app.errors import bad_request
from app.models import AiSuggestion, UpUser
from app.schemas import ReviewDecideIn, ReviewRunIn, ReviewStatusOut, SuggestionOut
from app.util import utcnow

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/queue", response_model=list[SuggestionOut])
def review_queue(
    admin: CurrentAdmin,
    db: DbSession,
    status: str = "pending",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
) -> list[SuggestionOut]:
    if status not in ("pending", "accepted", "rejected", "all"):
        raise bad_request(f"unknown status: {status}")
    query = db.query(AiSuggestion)
    if status != "all":
        query = query.filter(AiSuggestion.status == status)
    rows = query.order_by(AiSuggestion.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    out = []
    for s in rows:
        data = SuggestionOut.model_validate(s).model_dump()
        up = db.query(UpUser).filter(UpUser.mid == s.up_mid).first()
        data["up_uname"] = up.uname if up else ""
        out.append(SuggestionOut(**data))
    return out


@router.post("/decide")
def decide(payload: ReviewDecideIn, admin: CurrentAdmin, db: DbSession) -> dict:
    if payload.decision not in ("accept", "reject"):
        raise bad_request("decision must be accept or reject")
    rows = (
        db.query(AiSuggestion)
        .filter(AiSuggestion.id.in_(payload.ids), AiSuggestion.status == "pending")
        .all()
    )
    applied = 0
    for s in rows:
        s.status = "accepted" if payload.decision == "accept" else "rejected"
        s.decided_at = utcnow()
        if payload.decision == "accept" and s.suggested_group_id:
            up = db.query(UpUser).filter(UpUser.mid == s.up_mid).first()
            if up is not None:
                up.group_id = s.suggested_group_id
                up.ai_status = "done"
                applied += 1
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
    from app.services.ai_classifier import run_classification
    from app.services.settings_store import get_section_raw

    instruction = payload.instruction.strip()
    if not instruction:
        # fall back to the saved grouping guidance so the review page can send
        # one-off requirements while the settings page keeps a standing one
        instruction = str(get_section_raw(db, "ai").get("grouping_instructions") or "").strip()
    stats = run_classification(db, payload.batch_size, instruction=instruction)
    log_action(db, admin.username, "review.run", detail=stats)
    return stats


@router.get("/status", response_model=ReviewStatusOut)
def review_status(admin: CurrentAdmin, db: DbSession) -> ReviewStatusOut:
    settings = get_settings()
    if settings.demo_mode:
        pending = db.query(AiSuggestion).filter(AiSuggestion.status == "pending").count()
        return ReviewStatusOut(configured=True, model="demo-model", pending_count=pending, last_run=None)
    from app.services.settings_store import get_section_raw

    ai = get_section_raw(db, "ai")
    configured = bool(ai.get("base_url")) and bool(ai.get("api_key")) and bool(ai.get("model"))
    pending = db.query(AiSuggestion).filter(AiSuggestion.status == "pending").count()
    last = db.query(func.max(AiSuggestion.created_at)).scalar()
    return ReviewStatusOut(
        configured=configured, model=str(ai.get("model") or ""), pending_count=pending, last_run=last
    )
