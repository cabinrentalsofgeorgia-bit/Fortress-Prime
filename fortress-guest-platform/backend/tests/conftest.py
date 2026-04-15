from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

from backend.core.database import close_db
from backend.core.config import settings


# ── Test database isolation (Phase G.1.5 / G.1.8) ───────────────────────────
# If TEST_DATABASE_URL is set the test suite uses fortress_shadow_test instead
# of the production fortress_shadow database. When unset, tests run against the
# runtime DB with a warning.
#
# G.1.8 approach: monkey-patch backend.core.database session factory names in
# pytest_configure (runs before any test file is imported). This redirects both:
#   (a) Route handlers via Depends(get_db) — get_db() calls AsyncSessionLocal()
#   (b) Services that import AsyncSessionLocal / async_session_factory directly
#
# Not covered: code that imports the engine object (async_engine) directly.
# See PHASE_G18_REPORT.md §8 for the complete list of residual bypass paths.
#
# To activate isolation:
#   export TEST_DATABASE_URL=postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow_test
# To create fortress_shadow_test: backend/scripts/setup_test_db.sh


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    """
    Warn if TEST_DATABASE_URL is unset.

    When set, monkey-patches backend.core.database so that every subsequent
    import of AsyncSessionLocal, async_session_factory, or async_session_maker
    resolves to a session factory bound to fortress_shadow_test.

    Must run in pytest_configure (not in a fixture) so the patch is in place
    before test files are imported during the collection phase. Any service
    module that does 'from backend.core.database import AsyncSessionLocal'
    during collection will get the patched version.
    """
    test_url = os.environ.get("TEST_DATABASE_URL", "").strip()

    if not test_url:
        print(
            "\n"
            "⚠️  WARNING: TEST_DATABASE_URL is not set.\n"
            "   Tests will run against fortress_shadow (the PRODUCTION runtime DB).\n"
            "   Fixtures written by these tests will persist and contaminate production.\n"
            "   Run backend/scripts/setup_test_db.sh and set TEST_DATABASE_URL to isolate.\n",
            file=sys.stderr,
        )
        return

    # Ensure asyncpg driver prefix for SQLAlchemy async
    if test_url.startswith("postgresql://"):
        test_url = test_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Create the isolated test engine and session factory once per process.
    test_engine = create_async_engine(test_url, echo=False, pool_pre_ping=True, future=True)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Patch backend.core.database so all callers use fortress_shadow_test.
    # We import the module (which may already be cached from the module-level
    # 'from backend.core.database import close_db' above) and replace the
    # session-factory names in its namespace.
    import backend.core.database as _db_module
    _db_module.AsyncSessionLocal = test_factory      # get_db() + direct callers
    _db_module.async_session_factory = test_factory  # dispute_defense, others
    _db_module.async_session_maker = test_factory    # competitive_sentinel, others

    # Note: we do NOT patch _db_module.async_engine because close_db() uses it
    # to dispose the production engine on teardown. Leaving the engine alone
    # means teardown still works correctly and the test engine (which is not
    # registered there) stays alive through the full session.


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_db_engine_after_test():
    yield
    await close_db()
