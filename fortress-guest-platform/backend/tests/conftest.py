from __future__ import annotations

import sys
from pathlib import Path

import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parents[2]
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

from backend.core.database import close_db


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_db_engine_after_test():
    yield
    await close_db()
