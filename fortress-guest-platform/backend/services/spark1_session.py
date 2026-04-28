"""
Spark-1 fortress_prod mirror session factory.

Used by M3 trilateral write pattern as the third (catchup) write target.
Reads from this session are NOT supported — write-only during M3.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

SPARK1_DATABASE_URL = os.environ.get("SPARK1_DATABASE_URL", "")

_engine = None
_session_maker = None

def _ensure_engine():
    global _engine, _session_maker
    if _engine is None:
        if not SPARK1_DATABASE_URL:
            raise RuntimeError(
                "SPARK1_DATABASE_URL not set; Spark1Session cannot be created. "
                "If M3 mirror is intentionally disabled, do not call Spark1Session()."
            )
        _engine = create_async_engine(
            SPARK1_DATABASE_URL,
            pool_size=5,
            max_overflow=2,
            pool_timeout=10,
            pool_pre_ping=True,
        )
        _session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_maker

def Spark1Session() -> AsyncSession:
    """Returns an async session bound to spark-1 fortress_prod."""
    maker = _ensure_engine()
    return maker()