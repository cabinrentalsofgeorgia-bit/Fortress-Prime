"""Database module contract tests."""
from __future__ import annotations

import pytest

import backend.core.database as database


def test_database_import_does_not_create_runtime_engine() -> None:
    assert database.async_engine is None


def test_backward_compatible_session_aliases_share_factory() -> None:
    assert database.async_session_factory is database.AsyncSessionLocal
    assert database.async_session_maker is database.AsyncSessionLocal


@pytest.mark.asyncio
async def test_close_db_disposes_and_resets_cached_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEngine:
        def __init__(self) -> None:
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    fake_engine = FakeEngine()
    monkeypatch.setattr(database, "async_engine", fake_engine)
    monkeypatch.setattr(database, "_session_factory", object())

    await database.close_db()

    assert fake_engine.disposed is True
    assert database.async_engine is None
    assert database._session_factory is None
