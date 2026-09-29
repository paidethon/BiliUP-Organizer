"""Migration modules: m0001_init.py, m0002_xxx.py, ... Applied in version order.

Each module exposes ``upgrade(engine: Engine) -> None`` and must be idempotent
per recorded version. Schema changes are declared with SQLAlchemy DDL so no
SQL string is ever assembled at runtime.
"""
