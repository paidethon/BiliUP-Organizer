from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import unauthorized
from app.models import AdminUser, BilibiliAccount
from app.util import utcnow

SESSION_COOKIE = "biliup_session"
CSRF_COOKIE = "biliup_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL_DAYS = 14


def get_bilibili_account(db: Session) -> BilibiliAccount:
    row = db.get(BilibiliAccount, 1)
    if row is None:
        row = BilibiliAccount(id=1)
        db.add(row)
        db.commit()
    return row


def _utc_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_session(db: Session, user: AdminUser) -> tuple[str, str]:
    import secrets

    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    from app.models import Session as DbSession

    db.add(
        DbSession(
            token=token,
            user_id=user.id,
            created_at=utcnow(),
            expires_at=_utc_str(now + timedelta(days=SESSION_TTL_DAYS)),
        )
    )
    db.commit()
    return token, csrf


def destroy_session(db: Session, token: str) -> None:
    from app.models import Session as DbSession

    row = db.scalar(select(DbSession).where(DbSession.token == token))
    if row:
        db.delete(row)
        db.commit()


def hash_password(password: str) -> str:
    from argon2 import PasswordHasher

    return PasswordHasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    try:
        return PasswordHasher().verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def resolve_session(db: Session, token: str | None) -> AdminUser | None:
    if not token:
        return None
    from app.models import Session as DbSession

    row = db.scalar(select(DbSession).where(DbSession.token == token))
    if row is None or row.expires_at <= utcnow():
        return None
    return db.get(AdminUser, row.user_id)


def require_admin(request: Request, db: Session = Depends(get_db)) -> Any:
    settings = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    user = resolve_session(db, token)
    if user is None:
        if settings.demo_mode:
            user = _ensure_demo_user(db)
        else:
            raise unauthorized()
    # CSRF double-submit for mutating verbs (demo mode included; e2e reads the cookie).
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        cookie_csrf = request.cookies.get(CSRF_COOKIE)
        header_csrf = request.headers.get(CSRF_HEADER)
        if not cookie_csrf or header_csrf != cookie_csrf:
            raise unauthorized("CSRF token missing or invalid")
    request.state.actor = user.username
    return user


def _ensure_demo_user(db: Session) -> AdminUser:
    user = db.scalar(select(AdminUser).where(AdminUser.username == "demo"))
    if user is None:
        user = AdminUser(username="demo", password_hash=hash_password("demo"))
        db.add(user)
        db.commit()
    return user


def set_auth_cookies(response: Any, token: str, csrf: str, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=SESSION_TTL_DAYS * 86400,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        samesite="lax",
        secure=secure,
        max_age=SESSION_TTL_DAYS * 86400,
        path="/",
    )


def clear_auth_cookies(response: Any, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
