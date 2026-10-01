from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.errors import ApiError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("biliup")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    settings = get_settings()
    from app.db import run_migrations

    run_migrations()
    _bootstrap_admin()
    if settings.demo_mode:
        from app.db import get_session_factory
        from app.demo import seed

        seed(get_session_factory()())
    from app.services.classification_jobs import recover_interrupted_jobs

    recover_interrupted_jobs()
    from app.scheduler import start_scheduler

    start_scheduler()
    yield
    from app.scheduler import stop_scheduler

    stop_scheduler()


def _bootstrap_admin() -> None:
    settings = get_settings()
    if settings.demo_mode or not settings.bootstrap_admin_username:
        return
    from sqlalchemy import func, select

    from app.auth import hash_password
    from app.db import get_session_factory
    from app.models import AdminUser

    db = get_session_factory()()
    try:
        if db.scalar(select(func.count()).select_from(AdminUser)) == 0:
            db.add(
                AdminUser(
                    username=settings.bootstrap_admin_username,
                    password_hash=hash_password(settings.bootstrap_admin_password or "changeme-please"),
                )
            )
            db.commit()
            log.info("bootstrap admin created: %s", settings.bootstrap_admin_username)
    finally:
        db.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="BiliUP Organizer",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(
            status_code=500, content={"error": {"code": "internal_error", "message": "internal server error"}}
        )

    from app.api import (
        auth_routes,
        bilibili_routes,
        feeds_routes,
        followings_routes,
        groups_routes,
        history_routes,
        reminders_routes,
        review_routes,
        settings_routes,
        system_routes,
        tags_routes,
        weekly_routes,
    )

    app.include_router(auth_routes.router, prefix="/api/v1")
    app.include_router(bilibili_routes.router, prefix="/api/v1")
    app.include_router(followings_routes.router, prefix="/api/v1")
    app.include_router(groups_routes.router, prefix="/api/v1")
    app.include_router(review_routes.router, prefix="/api/v1")
    app.include_router(reminders_routes.router, prefix="/api/v1")
    app.include_router(settings_routes.router, prefix="/api/v1")
    app.include_router(history_routes.router, prefix="/api/v1")
    app.include_router(weekly_routes.router, prefix="/api/v1")
    app.include_router(feeds_routes.router, prefix="/api/v1")
    app.include_router(system_routes.router, prefix="/api/v1")
    app.include_router(tags_routes.router, prefix="/api/v1")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    def readyz() -> dict:
        from app.db import get_engine

        raw = get_engine().raw_connection()
        try:
            raw.cursor().execute("SELECT 1")
        finally:
            raw.close()
        return {"status": "ready"}

    @app.get("/feed/{token}", response_class=Response)
    @app.get("/feed/{token}.xml", response_class=Response)
    def public_feed(token: str, request: Request) -> Response:
        from app.api.feeds_routes import public_feed_response
        from app.db import get_session_factory

        base_url = str(request.base_url).rstrip("/")
        db = get_session_factory()()
        try:
            return public_feed_response(token, base_url, db)
        except NotImplementedError:
            if get_settings().demo_mode:
                from xml.sax.saxutils import escape

                body = escape("BiliUP Organizer 演示源")
                xml = (
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<feed xmlns="http://www.w3.org/2005/Atom">'
                    f"<title>{body}</title><id>urn:biliup-organizer:demo</id>"
                    "<updated>2026-09-29T00:00:00Z</updated></feed>"
                )
                return Response(content=xml, media_type="application/atom+xml")
            from app.errors import ApiError

            raise ApiError(503, "service_not_implemented", "feed service is not available yet") from None
        finally:
            db.close()

    _mount_spa(app)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # noqa: ANN202
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
            )
        return response

    return app


def _web_dist() -> Path | None:
    settings = get_settings()
    candidates = []
    if settings.web_dist:
        candidates.append(Path(settings.web_dist))
    candidates.append(Path(__file__).parent.parent / "apps" / "web" / "dist")
    candidates.append(Path("/app/web"))
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return None


def _mount_spa(app: FastAPI) -> None:
    dist = _web_dist()
    if dist is None:

        @app.get("/")
        def _no_frontend() -> dict:
            return {"app": "BiliUP Organizer", "frontend": "not built; run make web-build"}

        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path.startswith(("api/", "feed/", "healthz", "readyz")):
            from app.errors import not_found

            raise not_found()
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app", host=settings.app_host, port=settings.app_port, log_level=settings.log_level.lower()
    )


if __name__ == "__main__":
    main()
