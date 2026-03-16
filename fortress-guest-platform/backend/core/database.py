"""
Async database engine, session factory, and FastAPI dependency.
"""
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from backend.core.config import settings

logger = structlog.get_logger()

Base = declarative_base()

def _async_url(url: str) -> str:
    """Ensure the database URL uses the asyncpg driver."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url

async_engine = create_async_engine(
    _async_url(settings.database_url),
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI dependency that yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create tables if they don't exist (development convenience)."""
    # Ensure legal model metadata is registered before create_all.
    from backend.models.legal_base import LegalBase
    from backend.models import legal_graph, legal_phase2  # noqa: F401

    async with async_engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS legal"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(LegalBase.metadata.create_all)
    logger.info("database_tables_ensured")


async def close_db():
    """Dispose of the engine connection pool."""
    await async_engine.dispose()
    logger.info("database_connections_closed")
