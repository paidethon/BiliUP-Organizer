"""Schema v4: drop legacy groups_local.created_at.

Old deployments created groups_local with a created_at TEXT NOT NULL column;
the current model no longer defines it, so ORM inserts omit it and any group
creation fails with a NOT NULL violation. Fresh installs never had it.
Purely structural — no data is touched.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

_DDL = "ALTER TABLE groups_local DROP COLUMN created_at"


def upgrade(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("groups_local")}
    if "created_at" not in columns:
        log.info("groups_local.created_at not present; skipping")
        return
    log.info("dropping legacy column groups_local.created_at")
    with engine.begin() as connection:
        connection.exec_driver_sql(_DDL)
