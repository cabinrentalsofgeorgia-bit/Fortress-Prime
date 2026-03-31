"""
Async database engine and session factory.
"""
from sqlalchemy import text
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.core.config import settings

logger = structlog.get_logger()


class Base(DeclarativeBase):
    """Shared declarative base for Fortress Prime models."""

# Backward-compatible alias for legacy service imports.
async_session_maker = AsyncSessionLocal


def get_session_factory():
    """Backward-compatible accessor for legacy async session callers."""
    return AsyncSessionLocal


async_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db():
    """Validate connectivity and optionally create tables in opt-in dev mode."""
    async with async_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        if settings.db_auto_create_tables:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("database_tables_ensured")
        else:
            logger.info("database_connection_verified", auto_create_tables=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared async session factory for runtime DB access."""
    global _session_factory

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_async_engine(),
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


class _LazySessionFactory:
    """Proxy that preserves `AsyncSessionLocal()` call sites across the codebase."""

    def __call__(self) -> AsyncSession:
        return get_session_factory()()


class LazyAsyncSessionProxy:
    """Delay real session construction until a database operation is requested."""

    def __init__(self) -> None:
        self._session: AsyncSession | None = None

    def _ensure_session(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSessionLocal()
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._ensure_session(), item)


AsyncSessionLocal = _LazySessionFactory()

# Backward-compatible alias used by older background services.
async_session_factory = AsyncSessionLocal

# Callable that returns an :class:`~sqlalchemy.ext.asyncio.AsyncSession` for ``async with`` blocks.
async_session_maker = AsyncSessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a transactional async database session per request."""
    session = LazyAsyncSessionProxy()
    try:
        yield session  # type: ignore[misc]
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Verify the runtime database contract and prime the connection pool."""
    async with get_async_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))
    logger.info("database_connection_verified", database=settings.database_name)


async def close_db() -> None:
    """Dispose of the engine connection pool."""
    global async_engine, _session_factory

    if async_engine is not None:
        await async_engine.dispose()
        async_engine = None
        _session_factory = None
        logger.info("database_connections_closed")
