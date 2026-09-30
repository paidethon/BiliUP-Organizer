"""Schema v3: many-to-many UP ↔ group memberships.

Creates the group_members table from the ORM metadata and seeds it from the
existing single-group column (up_users.group_id), which keeps its meaning as
the PRIMARY group. Pure ORM — no raw SQL anywhere.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Base, GroupMember, UpUser

log = logging.getLogger(__name__)


def upgrade(engine: Engine) -> None:
    inspector = inspect(engine)
    if "group_members" in inspector.get_table_names():
        log.info("group_members already exists; skipping")
        return

    log.info("creating group_members table")
    Base.metadata.create_all(engine, tables=[GroupMember.__table__])

    seeded = 0
    with Session(engine) as session:
        pairs = session.query(UpUser.mid, UpUser.group_id).filter(UpUser.group_id.isnot(None)).all()
        for mid, group_id in pairs:
            session.add(GroupMember(up_mid=mid, group_id=group_id))
            seeded += 1
        session.commit()
    log.info("seeded %s memberships from up_users.group_id", seeded)
