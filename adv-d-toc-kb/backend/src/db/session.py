"""Async database session management.

The engine and session factory are created lazily and cached at module
level (process-local). ``get_session`` is the FastAPI dependency used
by route handlers; workers call ``_init()`` directly.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import Settings, get_settings
from src.observability.logging import get_logger

logger = get_logger(__name__)


def build_engine(settings: Settings | None = None) -> AsyncEngine:
    """Construct an ``AsyncEngine`` from settings.

    Pool settings are tuned for a typical small-to-medium deployment:
    ``pool_size=10`` with ``max_overflow=20`` handles ~30 concurrent
    requests comfortably.
    """
    s = settings or get_settings()
    return create_async_engine(
        str(s.database_url),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _init() -> async_sessionmaker[AsyncSession]:
    """Lazily build the process-local session factory.

    Called by both the FastAPI dependency and Celery workers. Each process
    (Uvicorn worker, Celery worker) gets its own engine + factory.
    """
    global _engine, _session_factory
    if _session_factory is None:
        _engine = build_engine()
        _session_factory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
        logger.info("Database session factory initialised")
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session with auto-commit/rollback.

    Yields:
        An ``AsyncSession``. On exit, commits if no exception was raised;
        rolls back otherwise.
    """
    factory = _init()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the process-local engine (used in tests and shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed")
    _engine = None
    _session_factory = None
