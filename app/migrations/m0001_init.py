"""Schema v1: create every table declared in app.models."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from app.models import Base


def upgrade(engine: Engine) -> None:
    Base.metadata.create_all(engine)
