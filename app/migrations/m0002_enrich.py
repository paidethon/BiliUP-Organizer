"""Schema v2: enrich data accuracy for classification and watch-time analysis.

- videos.tname: bilibili video category (分区) used by the AI classifier
- watch_history.duration_seconds: real video length for watch-time stats
- up_users.native_tag_id: last pushed bilibili native tag, for incremental
  group sync diffs
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

# Fully literal DDL: the table/column names are fixed by this migration,
# never derived from input.
_PLAN: list[tuple[str, str, str]] = [
    ("videos", "tname", "ALTER TABLE videos ADD COLUMN tname TEXT"),
    ("watch_history", "duration_seconds", "ALTER TABLE watch_history ADD COLUMN duration_seconds INTEGER"),
    ("up_users", "native_tag_id", "ALTER TABLE up_users ADD COLUMN native_tag_id INTEGER"),
]


def upgrade(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, column, ddl in _PLAN:
            columns = {col["name"] for col in inspector.get_columns(table)}
            if column in columns:
                continue
            log.info("adding %s.%s", table, column)
            connection.exec_driver_sql(ddl)
