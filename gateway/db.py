"""
Gateway Database — Shared Connection Pool
============================================
Single ThreadedConnectionPool for all gateway services.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("gateway.db")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

POOL_MIN = int(os.getenv("GW_POOL_MIN", "2"))
POOL_MAX = int(os.getenv("GW_POOL_MAX", "20"))

# ---------------------------------------------------------------------------
# Pool singleton
# ---------------------------------------------------------------------------

_pool: ThreadedConnectionPool | None = None


def get_pool() -> ThreadedConnectionPool:
    """Get or create the shared connection pool."""
    global _pool
    if _pool is None or _pool.closed:
        logger.info(
            f"Creating DB pool ({POOL_MIN}-{POOL_MAX}) "
            f"→ {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
        _pool = ThreadedConnectionPool(
            POOL_MIN, POOL_MAX,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
    return _pool


def close_pool():
    """Close the shared connection pool (call on shutdown)."""
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
        logger.info("DB pool closed.")
        _pool = None


@contextmanager
def get_conn():
    """Context manager: borrow a connection from the pool, auto-return."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit: bool = False):
    """Context manager: borrow a RealDictCursor, optionally commit."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def ping() -> bool:
    """Quick DB health check."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            return True
    except Exception as e:
        logger.error(f"DB ping failed: {e}")
        return False
