"""Database engine helpers and schema bootstrap."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from .config import PROJECT_ROOT, get_settings

SQL_DIR = PROJECT_ROOT / "sql"


@lru_cache(maxsize=8)
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url, pool_pre_ping=True, future=True)


def init_db(engine: Engine) -> None:
    """Apply schema.sql then views.sql. Both are idempotent."""
    with engine.begin() as conn:
        for name in ("schema.sql", "views.sql"):
            conn.exec_driver_sql((SQL_DIR / name).read_text())
