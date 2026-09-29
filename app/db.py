from __future__ import annotations

import importlib
import logging
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

log = logging.getLogger(__name__)

_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _make_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


def get_engine() -> Engine:
    global _engine, SessionLocal
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = _make_engine(settings.db_path)
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert SessionLocal is not None
    return SessionLocal


def get_db() -> Iterator[Session]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _migration_modules() -> list[tuple[int, str]]:
    """Migration modules are trusted files shipped with the app: m0001_init.py ..."""
    pkg = Path(__file__).parent / "migrations"
    result: list[tuple[int, str]] = []
    for path in sorted(pkg.glob("m*_*.py")):
        if path.name == "__init__.py":
            continue
        version = int(path.name[1:].split("_", 1)[0])
        result.append((version, f"app.migrations.{path.stem}"))
    return result


def run_migrations() -> None:
    engine = get_engine()
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )  # noqa: E501
        cur.execute("SELECT version FROM schema_version")
        applied = {row[0] for row in cur.fetchall()}
        raw.commit()
        cur.close()
    finally:
        raw.close()

    for version, module_name in _migration_modules():
        if version in applied:
            continue
        log.info("applying migration v%s (%s)", version, module_name)
        module = importlib.import_module(module_name)
        module.upgrade(engine)
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
            raw.commit()
            cur.close()
        finally:
            raw.close()


def checkpoint_wal() -> None:
    if _engine is not None:
        raw = _engine.raw_connection()
        try:
            raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            raw.commit()
        finally:
            raw.close()
