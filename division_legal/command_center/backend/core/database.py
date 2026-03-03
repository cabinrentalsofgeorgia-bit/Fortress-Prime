"""
Database connection and session management for the Legal Command Center.
"""
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator

from backend.core.config import settings

logger = structlog.get_logger()
Base = declarative_base()


def _async_url(url: str) -> str:
    if "+asyncpg" in url:
        return url
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async_engine = create_async_engine(
    _async_url(settings.database_url),
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("database_session_error", error=str(e))
            raise
        finally:
            await session.close()


async def init_db():
    async with async_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("legal_cmd_database_initialized")


async def close_db():
    await async_engine.dispose()
    logger.info("legal_cmd_database_closed")
