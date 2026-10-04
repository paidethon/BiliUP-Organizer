from __future__ import annotations

import json
import threading
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.auth import get_bilibili_account
from app.config import get_settings
from app.db import get_session_factory
from app.demo import bilibili_account_stub
from app.demo import qr_poll as demo_qr_poll
from app.demo import qr_start as demo_qr_start
from app.errors import bad_request
from app.models import BilibiliAccount, NativeGroupMap, SyncRun
from app.schemas import (
    BilibiliAccountOut,
    CookieIn,
    NativeGroupOut,
    NativeOverwriteIn,
    NativePushIn,
    QrPollOut,
    QrStartOut,
    SyncRunIn,
    SyncRunOut,
)
from app.util import utcnow

router = APIRouter(prefix="/bilibili", tags=["bilibili"])


def _account_out(account: BilibiliAccount) -> BilibiliAccountOut:
    masked = ""
    if account.cookie_json:
        try:
            cookie: dict = json.loads(account.cookie_json)
            masked = "; ".join(f"{k}=••••" for k in cookie)
        except json.JSONDecodeError:
            masked = "••••"
    return BilibiliAccountOut(
        login_status=account.login_status,
        mid=account.mid,
        uname=account.uname,
        avatar=account.avatar,
        cookie_updated_at=account.cookie_updated_at,
        risk_flag=account.risk_flag,
        cookie_masked=masked,
    )


@router.get("/account", response_model=BilibiliAccountOut)
def get_account(db: DbSession) -> BilibiliAccountOut:
    if get_settings().demo_mode:
        return bilibili_account_stub()
    return _account_out(get_bilibili_account(db))


@router.post("/qr/start", response_model=QrStartOut)
def qr_start(admin: CurrentAdmin, db: DbSession) -> QrStartOut:
    settings = get_settings()
    if settings.demo_mode:
        return QrStartOut(**demo_qr_start())
    from app.services.bilibili.qrlogin import start_login

    data = start_login(db)
    log_action(db, admin.username, "bilibili.qr_start")
    return QrStartOut(**data)


@router.get("/qr/poll", response_model=QrPollOut)
def qr_poll(admin: CurrentAdmin, qrcode_key: str = Query(min_length=1), db: DbSession = None) -> QrPollOut:  # type: ignore[assignment]
    settings = get_settings()
    if settings.demo_mode:
        return QrPollOut(**demo_qr_poll())
    from app.services.bilibili.qrlogin import poll_login

    result = poll_login(db, qrcode_key)
    if result["status"] == "confirmed":
        log_action(db, admin.username, "bilibili.qr_confirmed")
    return QrPollOut(**result)


@router.post("/cookie", response_model=BilibiliAccountOut)
def set_cookie(payload: CookieIn, admin: CurrentAdmin, db: DbSession) -> BilibiliAccountOut:
    cookie: dict[str, str] = {}
    for part in payload.cookie.replace("\n", "; ").split(";"):
        if "=" in part:
            k, _, v = part.strip().partition("=")
            if k:
                cookie[k] = v
    if not cookie.get("SESSDATA"):
        raise bad_request("cookie must contain SESSDATA")
    account = get_bilibili_account(db)
    account.cookie_json = json.dumps(cookie)
    account.cookie_updated_at = utcnow()
    account.login_status = "active"
    account.risk_flag = False
    if cookie.get("DedeUserID"):
        account.mid = int(cookie["DedeUserID"])
    db.commit()
    log_action(db, admin.username, "bilibili.cookie_set", entity_type="bilibili_account")
    return _account_out(account)


@router.post("/logout", response_model=BilibiliAccountOut)
def bilibili_logout(admin: CurrentAdmin, db: DbSession) -> BilibiliAccountOut:
    account = get_bilibili_account(db)
    account.cookie_json = None
    account.cookie_updated_at = None
    account.login_status = "none"
    db.commit()
    log_action(db, admin.username, "bilibili.logout")
    return _account_out(account)


@router.post("/sync/run", response_model=SyncRunOut)
def run_sync(payload: SyncRunIn, admin: CurrentAdmin, db: DbSession) -> SyncRunOut:
    if payload.kind not in (
        "followings",
        "watch_history",
        "full",
        "native_groups",
        "native_overwrite",
        "native_incremental",
        "native_push",
    ):
        raise bad_request("unknown sync kind")
    settings = get_settings()
    if settings.demo_mode:
        run = SyncRun(
            kind=payload.kind,
            status="success",
            finished_at=utcnow(),
            stats_json='{"total": 24, "new": 1, "demo": true}',
        )
        db.add(run)
        db.commit()
        return SyncRunOut(
            id=run.id,
            kind=run.kind,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
    run = SyncRun(kind=payload.kind, status="running")
    db.add(run)
    db.commit()
    log_action(
        db,
        admin.username,
        "sync.run",
        entity_type="sync_run",
        entity_id=run.id,
        detail={"kind": payload.kind},
    )

    def _worker(run_id: int) -> None:
        from app.services import sync as sync_service

        session = get_session_factory()()
        try:
            run_row = session.get(SyncRun, run_id)
            stats = sync_service.run_sync_kind(
                session, payload.kind, run=run_row, mode=getattr(payload, "mode", None)
            )
            if run_row is not None:
                run_row.status = "success"
                run_row.stats_json = json.dumps(stats, ensure_ascii=False)
                run_row.finished_at = utcnow()
                session.commit()
        except Exception as exc:
            session.rollback()
            run_row = session.get(SyncRun, run_id)
            if run_row is not None:
                run_row.status = "failed"
                run_row.error = str(exc)[:2000]
                run_row.finished_at = utcnow()
                session.commit()
        finally:
            session.close()

    threading.Thread(target=_worker, args=(run.id,), daemon=True, name=f"sync-{run.id}").start()
    return SyncRunOut(id=run.id, kind=run.kind, status=run.status, started_at=run.started_at)


@router.get("/sync/runs", response_model=list[SyncRunOut])
def list_runs(
    admin: CurrentAdmin, limit: int = Query(default=20, le=100), db: DbSession = None
) -> list[SyncRunOut]:  # type: ignore[assignment]
    rows = db.query(SyncRun).order_by(SyncRun.id.desc()).limit(limit).all()
    out = []
    for r in rows:
        stats = None
        if r.stats_json:
            try:
                stats = json.loads(r.stats_json)
            except json.JSONDecodeError:
                stats = None
        out.append(
            SyncRunOut(
                id=r.id,
                kind=r.kind,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                stats=stats,
                error=r.error,
            )
        )
    return out


@router.get("/native-groups", response_model=list[NativeGroupOut])
def list_native_groups(db: DbSession) -> list[NativeGroupOut]:
    rows = db.query(NativeGroupMap).order_by(NativeGroupMap.bili_tag_name).all()
    return [NativeGroupOut.model_validate(r) for r in rows]


@router.post("/native-groups/sync", response_model=list[NativeGroupOut])
def sync_native_groups(admin: CurrentAdmin, db: DbSession) -> list[NativeGroupOut]:
    if get_settings().demo_mode:
        return [
            NativeGroupOut(bili_tag_id=1, bili_tag_name="默认分组", local_group_id=None, synced_at=utcnow())
        ]
    from app.services import sync as sync_service

    sync_service.run_sync_kind(db, "native_groups")
    log_action(db, admin.username, "bilibili.native_groups_sync")
    return list_native_groups(db)


@router.post("/native-groups/push")
def push_native_groups(
    payload: NativePushIn,
    admin: CurrentAdmin,
    db: DbSession,
    dry_run: bool = Query(default=False),
) -> dict:
    """Add members to a native tag. dry_run=true previews without writing."""
    if dry_run:
        plan = {
            "mode": "push",
            "dry_run": True,
            "would_move": len(payload.mids),
            "tag_id": payload.tag_id,
            "notes": ["dry run：只读预览，不产生任何远端写操作"],
        }
        log_action(db, admin.username, "bilibili.native_groups_dry_run", detail={"mode": "push"})
        return plan
    if get_settings().demo_mode:
        return {"ok": True, "added": len(payload.mids), "demo": True}
    from app.services.bilibili.native_groups import add_users_to_tag

    added = add_users_to_tag(db, payload.tag_id, payload.mids)
    log_action(
        db,
        admin.username,
        "bilibili.native_groups_push",
        detail={"tag_id": payload.tag_id, "count": len(payload.mids)},
    )
    return {"ok": True, "added": added}


@router.post("/native-groups/push-overwrite")
def push_native_groups_overwrite(
    admin: CurrentAdmin,
    db: DbSession,
    payload: NativeOverwriteIn | None = None,
) -> dict:
    """Explicit destructive rebuild, managed scope only (see native_sync).

    Preview first: dry_run=true returns the plan (remote reads only) and must
    be confirmed by a second call with dry_run=false.
    """
    dry_run = bool(payload.dry_run) if payload is not None else False
    if get_settings().demo_mode:
        if dry_run:
            return {
                "mode": "overwrite",
                "dry_run": True,
                "scope": "managed_tags_only",
                "managed_tags": {"科技数码": 101, "影像创作": 102},
                "protected_remote_tags": ["手动远端组"],
                "would_place": 12,
                "notes": ["demo 预览：真实环境将先备份再仅重建托管标签"],
            }
        return {"ok": True, "mode": "overwrite", "demo": True}
    from app.services import native_sync

    result = native_sync.push_overwrite(db, dry_run=dry_run)
    if dry_run:
        log_action(db, admin.username, "bilibili.native_groups_dry_run", detail={"mode": "overwrite"})
        return result
    log_action(db, admin.username, "bilibili.native_groups_overwrite", detail={"mode": result.get("mode")})
    return {"ok": True, **result}


class NativePushPlanIn(BaseModel):
    mode: Literal["append", "replace"] = "append"


@router.post("/native-groups/push-plan")
def push_native_groups_plan(admin: CurrentAdmin, db: DbSession, payload: NativePushPlanIn) -> dict:
    """Read-only preview of the append/replace convergence (remote GETs only)."""
    if get_settings().demo_mode:
        return {
            "mode": payload.mode,
            "dry_run": True,
            "managed_tags": {"科技数码": 101},
            "unmapped_local_groups": [],
            "to_add": {"101": [42]},
            "to_remove": {},
            "batches": [{"tagids": [101], "mids": [42]}],
            "planned_up_writes": 1,
            "tag_reads_complete": True,
            "notes": ["demo 预览：只读，不产生任何远端写操作"],
        }
    from app.services import native_sync

    plan = native_sync.plan_push(db, mode=payload.mode)
    log_action(db, admin.username, "bilibili.native_groups_plan", detail={"mode": payload.mode})
    return plan


@router.post("/native-groups/push-run")
def push_native_groups_run(admin: CurrentAdmin, db: DbSession, payload: NativePushPlanIn) -> SyncRunOut:
    """Start a converging native-group push (append default / replace) as a
    tracked background task; poll /bilibili/sync/runs for live progress."""
    if get_settings().demo_mode:
        run = SyncRun(
            kind="native_push",
            status="success",
            finished_at=utcnow(),
            stats_json=json.dumps({"mode": payload.mode, "demo": True, "written_ups": 0}, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        return SyncRunOut(id=run.id, kind=run.kind, status=run.status, started_at=run.started_at)

    from app.services import sync as sync_service
    from app.services.settings_store import get_section_raw

    if not bool(get_section_raw(db, "sync").get("native_push_enabled")):
        raise bad_request("native_push_disabled: 在「设置 → 同步」中开启原生分组推送后再试")

    run = SyncRun(kind="native_push", status="running")
    db.add(run)
    db.commit()
    log_action(
        db,
        admin.username,
        "bilibili.native_push_run",
        entity_type="sync_run",
        entity_id=run.id,
        detail={"mode": payload.mode},
    )

    def _worker(run_id: int, mode: str) -> None:
        from app.services.bilibili.errors import BiliError

        session = get_session_factory()()
        try:
            run_row = session.get(SyncRun, run_id)
            stats = sync_service.run_sync_kind(session, "native_push", mode=mode, run=run_row)
            if run_row is not None:
                run_row.status = "success"
                run_row.stats_json = json.dumps(stats, ensure_ascii=False)
                run_row.finished_at = utcnow()
                session.commit()
        except BiliError as exc:
            session.rollback()
            run_row = session.get(SyncRun, run_id)
            if run_row is not None:
                run_row.status = "failed"
                run_row.error = f"bili_{exc.kind}: {exc.message}"[:2000]
                run_row.finished_at = utcnow()
                session.commit()
        except Exception as exc:
            session.rollback()
            run_row = session.get(SyncRun, run_id)
            if run_row is not None:
                run_row.status = "failed"
                run_row.error = str(exc)[:2000]
                run_row.finished_at = utcnow()
                session.commit()
        finally:
            session.close()

    threading.Thread(
        target=_worker, args=(run.id, payload.mode), daemon=True, name=f"native-push-{run.id}"
    ).start()
    return SyncRunOut(id=run.id, kind=run.kind, status=run.status, started_at=run.started_at)
