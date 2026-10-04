"""Performance validation for the shared stats service (task §11).

Seeds a fixed-seed synthetic dataset (100k watch-history rows, multi-group
memberships, synced videos) into an isolated SQLite database, verifies the
stats indexes exist in the catalog, and times the main aggregation surfaces.
Deterministic values are derived from a SHA-256 counter instead of the random
module so repeated runs are comparable.

Run from the repo root:
    DATA_DIR=$(mktemp -d) uv run python scripts/perf_stats.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="biliup-perf-")

from sqlalchemy import inspect  # noqa: E402

from app.db import get_engine, get_session_factory, run_migrations  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    GroupLocal,
    GroupMember,
    UpUser,
    Video,
    WatchHistory,
)
from app.services.stats import range_stats  # noqa: E402
from app.timeutil import shanghai_today, week_bounds  # noqa: E402

ROWS = int(os.environ.get("PERF_ROWS", "100_000").replace("_", ""))
UPS = 800
GROUPS = 12
VIDEOS_PER_UP = 30
INSERT_CHUNK = 5000


class Deterministic:
    """Counter-mode SHA-256 value stream: reproducible, no RNG module."""

    def __init__(self, seed: str) -> None:
        self._seed = seed
        self._counter = 0

    def _next_int(self, modulus: int) -> int:
        digest = hashlib.sha256(f"{self._seed}:{self._counter}".encode()).digest()
        self._counter += 1
        return int.from_bytes(digest[:8], "big") % modulus

    def pick(self, seq: list) -> object:  # noqa: ANN201
        return seq[self._next_int(len(seq))]

    def below(self, bound: int) -> int:
        return self._next_int(bound)


def seed(db) -> None:  # noqa: ANN001
    stream = Deterministic("biliup-perf-20261004")
    now = datetime.now(UTC).replace(tzinfo=None)

    groups = [GroupLocal(name=f"分组{i}", sort_order=i) for i in range(GROUPS)]
    db.add_all(groups)
    db.flush()

    ups = [UpUser(mid=10_000_000 + i, uname=f"UP_{i}", group_id=groups[i % GROUPS].id) for i in range(UPS)]
    db.add_all(ups)
    db.flush()

    memberships: list[GroupMember] = []
    for i, up in enumerate(ups):
        memberships.append(GroupMember(up_mid=up.mid, group_id=groups[i % GROUPS].id))
        if stream.below(2) == 0:  # multi-group: ~half the UPs belong to two groups
            memberships.append(GroupMember(up_mid=up.mid, group_id=groups[(i + 3) % GROUPS].id))
    db.add_all(memberships)

    videos: list[Video] = []
    for i, up in enumerate(ups):
        for k in range(VIDEOS_PER_UP):
            videos.append(
                Video(
                    bvid=f"BV1p{i:05d}{k:04d}",
                    up_mid=up.mid,
                    title=f"视频 {i}-{k}",
                    tname=f"分区{k % 8}",
                    pubdate=(now - timedelta(days=stream.below(400) + 1)).strftime("%Y-%m-%d %H:%M:%S"),
                )
            )
    db.add_all(videos)

    bulk: list[WatchHistory] = []
    for n in range(ROWS):
        up = stream.pick(ups)
        moment = now - timedelta(
            days=stream.below(60),
            hours=stream.below(24),
            minutes=stream.below(60),
            seconds=stream.below(60),
        )
        progress = stream.pick([-1, -1, 0, 1])  # 1 expands to a real partial watch
        bulk.append(
            WatchHistory(
                bvid=f"BV1h{n:08d}",
                up_mid=up.mid,
                title=f"观看 {n}",
                view_at=moment.strftime("%Y-%m-%d %H:%M:%S"),
                progress=progress if progress in (-1, 0) else stream.below(1200) + 1,
                duration_seconds=None if stream.below(4) == 0 else stream.below(2400) + 30,
            )
        )
    for start in range(0, len(bulk), INSERT_CHUNK):
        db.add_all(bulk[start : start + INSERT_CHUNK])
        db.commit()
    db.commit()


def verify_indexes() -> None:
    inspector = inspect(get_engine())
    wh = {idx["name"] for idx in inspector.get_indexes("watch_history")}
    required = (
        "ix_watch_history_view_at",
        "ix_watch_history_up_view",
        "ix_watch_history_bvid",
        "uq_watch_history_bvid_viewat",
    )
    for name in required:
        assert name in wh, f"missing stats index: {name}"
    print("[index] watch_history stats indexes present:", sorted(wh))


def main() -> int:
    run_migrations()
    Base.metadata.create_all(get_engine())
    db = get_session_factory()()

    t0 = time.perf_counter()
    seed(db)
    print(f"seeded {ROWS} history rows, {UPS} ups, {GROUPS} groups in {time.perf_counter() - t0:.1f}s")

    verify_indexes()

    today = shanghai_today()
    start, end = week_bounds(today)

    def timed(label: str, fn) -> object:  # noqa: ANN001
        t = time.perf_counter()
        result = fn()
        print(f"[time] {label}: {(time.perf_counter() - t) * 1000:.0f} ms")
        return result

    timed("range_stats(extras, prev) current week", lambda: range_stats(db, start, end))
    timed(
        "range_stats(core only) 30d",
        lambda: range_stats(db, end - timedelta(days=30), end, extras=False),
    )

    from app.services.weekly_report import generate_report

    timed("generate_report(save)", lambda: generate_report(db, start, save=True))

    db_path = db.get_bind().url.database
    if db_path and Path(db_path).exists():
        print(f"[size] db: {Path(db_path).stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
