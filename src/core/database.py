"""Compatibility exports for the unified database entrypoint.

Runtime code should import database sessions and lifecycle helpers from
``src.database``. This module is kept only for older imports that still point
at ``src.core.database``.
"""
from src.database import (
    close_database,
    get_async_engine,
    get_async_session_factory,
    get_db,
    get_db_context,
    init_database,
)

__all__ = [
    "close_database",
    "get_async_engine",
    "get_async_session_factory",
    "get_db",
    "get_db_context",
    "init_database",
]
