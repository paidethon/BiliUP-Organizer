"""Schema v5: classification model split + full-library AI jobs + undo.

- tags / up_tags: free-form content tags (many per UP, separate from groups)
- up_status_labels: explicit status labels (待整理/吃灰/...), independent of
  content categories; derived states stay computed
- group_aliases: category alias vocabulary so the classifier reuses existing
  categories instead of spawning near-duplicates
- classification_jobs: persistent, pausable full-library classification jobs
- undo_records: revertible bulk-operation log
- ai_suggestions: structured result columns (suggested_tags, previous_group_name,
  evidence, provider, prompt_version); status gains "unclassifiable"

Existing local groups keep their meaning — they ARE the primary categories.
No data is rewritten: old rows simply gain NULL/empty new columns.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import (
    AiSuggestion,
    Base,
    ClassificationJob,
    GroupAlias,
    GroupLocal,
    Tag,
    UndoRecord,
    UpStatusLabel,
    UpTag,
    UpUser,
)

log = logging.getLogger(__name__)

_NEW_TABLES = (
    Tag.__table__,
    UpTag.__table__,
    UpStatusLabel.__table__,
    GroupAlias.__table__,
    ClassificationJob.__table__,
    UndoRecord.__table__,
)

# Fully literal DDL: names fixed by this migration, never derived from input.
_ADD_COLUMNS: list[tuple[str, str, str]] = [
    (
        "ai_suggestions",
        "suggested_tags",
        "ALTER TABLE ai_suggestions ADD COLUMN suggested_tags TEXT DEFAULT '[]'",
    ),
    (
        "ai_suggestions",
        "previous_group_name",
        "ALTER TABLE ai_suggestions ADD COLUMN previous_group_name TEXT",
    ),
    ("ai_suggestions", "evidence", "ALTER TABLE ai_suggestions ADD COLUMN evidence TEXT DEFAULT '{}'"),
    ("ai_suggestions", "provider", "ALTER TABLE ai_suggestions ADD COLUMN provider TEXT DEFAULT ''"),
    (
        "ai_suggestions",
        "prompt_version",
        "ALTER TABLE ai_suggestions ADD COLUMN prompt_version TEXT DEFAULT ''",
    ),
]


def upgrade(engine: Engine) -> None:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    for table in _NEW_TABLES:
        if table.name in existing:
            continue
        log.info("creating table %s", table.name)
        Base.metadata.create_all(engine, tables=[table])

    with engine.begin() as connection:
        for table, column, ddl in _ADD_COLUMNS:
            if table not in existing:
                continue  # fresh DB: m0001 already created the full shape
            columns = {col["name"] for col in inspector.get_columns(table)}
            if column in columns:
                continue
            log.info("adding %s.%s", table, column)
            connection.exec_driver_sql(ddl)

    # Backfill previous_group_name for pre-existing pending suggestions so the
    # review UI can always show old -> new. Pure ORM, no string-built SQL.
    if "ai_suggestions" in existing and "up_users" in existing:
        with Session(engine) as session:
            rows = (
                session.query(AiSuggestion, UpUser.group_id)
                .outerjoin(UpUser, UpUser.mid == AiSuggestion.up_mid)
                .filter(AiSuggestion.previous_group_name.is_(None))
                .all()
            )
            group_names = dict(session.query(GroupLocal.id, GroupLocal.name).all())
            changed = 0
            for suggestion, group_id in rows:
                suggestion.previous_group_name = group_names.get(group_id) if group_id is not None else None
                changed += 1
            session.commit()
        log.info("backfilled previous_group_name on %s suggestions", changed)
