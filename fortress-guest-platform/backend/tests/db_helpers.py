"""
Test database helpers (Phase G.1.7).

Centralizes the test DSN so we don't have to edit 23 test files every time
it changes. The DSN comes from the TEST_DATABASE_URL environment variable,
with no fallback — if unset, tests fail loudly rather than fall back to
fortress_shadow and contaminate it.
"""
from __future__ import annotations

import os


class TestDatabaseURLNotSetError(RuntimeError):
    """Raised when TEST_DATABASE_URL is not set in the environment.

    Tests must run against a dedicated test database (fortress_shadow_test).
    Falling back to the runtime DB (fortress_shadow) would re-pollute
    production with test fixtures.

    To fix: run backend/scripts/setup_test_db.sh and set:
      export TEST_DATABASE_URL=postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow_test
    See backend/.env.example for the full documentation.
    """


def get_test_dsn() -> str:
    """Return the TEST_DATABASE_URL, raising if unset.

    Use this in every test that needs a direct psycopg2 or asyncpg connection.
    Do NOT hardcode fortress_shadow.
    """
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        raise TestDatabaseURLNotSetError(
            "TEST_DATABASE_URL is not set. "
            "See backend/.env.example. "
            "Run backend/scripts/setup_test_db.sh to create the test DB."
        )
    return dsn
