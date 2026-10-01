"""Large-library performance: 5000 synthetic UPs.

Verifies the "all results" mode and filtered listing stay flat (no per-row
queries) as the library grows. Synthetic data lives only in a throwaway DB —
never committed as seed data, never leaked into other tests (the shared
app engine is swapped out for the module and restored afterwards).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

_tmp = Path(tempfile.mkdtemp(prefix="biliup-perf-"))
os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
os.environ.setdefault("DATA_DIR", str(_tmp))

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.main import app  # noqa: E402

TOTAL_UPS = 5000
STALE_COUNT = len([i for i in range(TOTAL_UPS) if i % 7 == 0])  # 715
NS = "压测UP"  # every synthetic UP carries this namespace in its name


@pytest.fixture(scope="module")
def large_client():
    """Run this module against its own DATA_DIR, then restore the shared engine."""
    import app.db as appdb

    old_engine = appdb._engine
    old_factory = appdb.SessionLocal
    old_env = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(_tmp)
    reset_settings_cache()
    appdb._engine = None
    appdb.SessionLocal = None
    try:
        _seed_large_library()
        with TestClient(app) as c:
            login = c.post("/api/v1/auth/login", json={"username": "demo", "password": "demo"})
            assert login.status_code == 200
            c.headers.update({"X-CSRF-Token": c.cookies.get("biliup_csrf", "")})
            yield c
    finally:
        if old_env is not None:
            os.environ["DATA_DIR"] = old_env
        reset_settings_cache()
        appdb._engine = old_engine
        appdb.SessionLocal = old_factory


def _seed_large_library() -> None:
    """Insert synthetic UPs straight through the ORM (bulk, fast)."""
    from app.db import get_engine
    from app.models import Base, GroupLocal, GroupMember, UpStatusLabel, UpUser

    engine = get_engine()
    Base.metadata.create_all(engine)
    groups = [GroupLocal(name=f"压测分类{i:02d}", sort_order=10_000 + i) for i in range(8)]
    with Session(engine) as session:
        existing = session.query(GroupLocal).filter(GroupLocal.name == groups[0].name).first()
        if existing is not None:
            return  # already seeded (module re-run in the same process)
        session.add_all(groups)
        session.commit()
        ups = []
        members = []
        labels = []
        for i in range(TOTAL_UPS):
            mid = 9_000_000 + i
            ups.append(
                UpUser(
                    mid=mid,
                    uname=f"{NS}{i:05d}",
                    sign="synthetic",
                    watched_count=i % 5,
                    group_id=groups[i % len(groups)].id,
                )
            )
            members.append(GroupMember(up_mid=mid, group_id=groups[i % len(groups)].id))
            if i % 7 == 0:
                labels.append(UpStatusLabel(up_mid=mid, label="吃灰", source="manual"))
        session.bulk_save_objects(ups)
        session.bulk_save_objects(members)
        session.bulk_save_objects(labels)
        session.commit()


def _count_queries(fn):  # type: ignore[no-untyped-def]
    from app.db import get_engine

    count = {"n": 0}

    def _before_cursor(*args, **kwargs):  # noqa: ANN002, ANN003
        count["n"] += 1

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", _before_cursor)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor)
    return result, count["n"]


def test_all_mode_returns_everything_fast(large_client: TestClient) -> None:
    import time

    def _fetch():  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        res = large_client.get("/api/v1/followings", params={"all": "true", "q": NS})
        elapsed = time.perf_counter() - started
        assert res.status_code == 200
        return res.json(), elapsed

    (body, elapsed), queries = _count_queries(_fetch)
    assert body["total"] == TOTAL_UPS
    assert len(body["items"]) == TOTAL_UPS
    assert body["page_size"] == TOTAL_UPS
    # generous wall-clock bound; the point is "not minutes and not per-row"
    assert elapsed < 10, f"all mode took {elapsed:.2f}s"
    # per-row group/tag/status lookups would explode past this immediately
    assert queries < 50, f"all mode issued {queries} queries (N+1?)"


def test_pagination_and_filters_still_work(large_client: TestClient) -> None:
    res = large_client.get("/api/v1/followings", params={"q": NS, "page": 3, "page_size": 100})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == TOTAL_UPS
    assert len(body["items"]) == 100
    assert body["page"] == 3

    res = large_client.get("/api/v1/followings", params={"q": NS, "status": "吃灰", "all": "true"})
    assert res.status_code == 200
    assert res.json()["total"] == STALE_COUNT

    res = large_client.get("/api/v1/followings", params={"q": f"{NS}04999", "all": "true"})
    assert res.json()["total"] == 1


def test_bulk_by_query_handles_thousands(large_client: TestClient) -> None:
    res = large_client.post(
        "/api/v1/followings/bulk",
        json={
            "query": {"q": f"{NS}04999"},
            "action": "add_tags",
            "params": {"tags": ["压力测试"]},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["changed"] == 1
    assert body["undo_id"]
