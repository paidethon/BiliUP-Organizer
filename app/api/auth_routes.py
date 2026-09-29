from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.audit import log_action
from app.auth import (
    clear_auth_cookies,
    create_session,
    destroy_session,
    hash_password,
    set_auth_cookies,
    verify_password,
)
from app.config import get_settings
from app.db import get_db
from app.errors import bad_request, forbidden, unauthorized
from app.models import AdminUser
from app.schemas import ChangePasswordIn, LoginIn, MeOut, SetupIn, StatusOut

router = APIRouter(prefix="/auth", tags=["auth"])

_db_dep = Depends(get_db)


def _has_admin(db) -> bool:  # noqa: ANN001
    return db.scalar(select(func.count()).select_from(AdminUser)) > 0


@router.get("/status", response_model=StatusOut)
def status(db: DbSession, request: Request) -> StatusOut:
    from app.auth import resolve_session

    settings = get_settings()
    user = resolve_session(db, request.cookies.get("biliup_session"))
    return StatusOut(
        needs_setup=not _has_admin(db) and not settings.demo_mode,
        demo_mode=settings.demo_mode,
        authenticated=user is not None,
    )


@router.post("/setup")
def setup(payload: SetupIn, db: DbSession, response: Response, request: Request) -> dict:
    settings = get_settings()
    if settings.demo_mode or _has_admin(db):
        raise forbidden("setup is no longer available")
    user = AdminUser(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    token, csrf = create_session(db, user)
    set_auth_cookies(response, token, csrf, secure=settings.is_prod)
    log_action(db, user.username, "auth.setup")
    return {"ok": True, "csrf": csrf}


@router.post("/login")
def login(payload: LoginIn, db: DbSession, response: Response, request: Request) -> dict:
    settings = get_settings()
    if settings.demo_mode:
        from app.auth import _ensure_demo_user

        user = _ensure_demo_user(db)
    else:
        user = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
        if user is None or not verify_password(user.password_hash, payload.password):
            raise unauthorized("invalid username or password")
    token, csrf = create_session(db, user)
    set_auth_cookies(response, token, csrf, secure=settings.is_prod)
    log_action(db, user.username, "auth.login")
    return {"ok": True, "csrf": csrf, "demo_mode": settings.demo_mode}


@router.post("/logout")
def logout(request: Request, db: DbSession, response: Response) -> dict:
    settings = get_settings()
    token = request.cookies.get("biliup_session")
    if token:
        destroy_session(db, token)
    clear_auth_cookies(response, secure=settings.is_prod)
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(admin: CurrentAdmin) -> MeOut:
    return MeOut(username=admin.username, demo_mode=get_settings().demo_mode)


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, admin: CurrentAdmin, db: DbSession) -> dict:
    if not verify_password(admin.password_hash, payload.old_password):
        raise bad_request("old password is incorrect")
    if payload.old_password == payload.new_password:
        raise bad_request("new password must differ from the old one")
    admin.password_hash = hash_password(payload.new_password)
    db.commit()
    log_action(db, admin.username, "auth.change_password")
    return {"ok": True}
