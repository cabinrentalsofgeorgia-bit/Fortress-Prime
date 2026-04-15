from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parents[2]
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

from backend.core.database import close_db
from backend.core.config import settings


# ── Test database isolation (Phase G.1.5) ────────────────────────────────────
# If TEST_DATABASE_URL is set, the test suite uses fortress_shadow_test instead
# of the production fortress_shadow database. When unset, tests run against the
# runtime DB with a warning.
#
# To activate isolation:
#   export TEST_DATABASE_URL="postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow_test"
#
# To create fortress_shadow_test: backend/scripts/setup_test_db.sh
# To update test files that still hardcode fortress_shadow DSNs: see PHASE_G15_REPORT.md §7.

def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    """Warn early if the test suite is targeting the production runtime DB."""
    if settings.test_database_url is None:
        print(
            "\n"
            "⚠️  WARNING: TEST_DATABASE_URL is not set.\n"
            "   Tests will run against fortress_shadow (the PRODUCTION runtime DB).\n"
            "   Fixtures written by these tests will persist and contaminate production.\n"
            "   Run backend/scripts/setup_test_db.sh and set TEST_DATABASE_URL to isolate.\n",
            file=sys.stderr,
        )


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_db_engine_after_test():
    yield
    await close_db()
