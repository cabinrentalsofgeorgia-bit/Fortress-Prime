from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("LITELLM_MASTER_KEY", "test-litellm-master-key")

import backend.core.database as database
from backend.scripts import backfill_vector_ids
from backend.scripts import email_backfill_legal
from backend.scripts import reprocess_failed_qdrant_uploads
from backend.scripts import vault_ingest_legal_case
from backend.services import legal_council
from backend.services import legal_ediscovery
from backend.services.legal import db_targets
from backend.services.legal import qdrant_contract


def test_database_module_has_one_session_contract() -> None:
    source = Path(database.__file__).read_text()

    assert source.count("async def get_db(") == 1
    assert source.count("async def init_db(") == 1
    assert source.count("async def close_db(") == 1
    assert source.count("AsyncSessionLocal =") == 1
    assert "declarative_base" not in source


def test_get_async_engine_is_lazy_and_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, object]] = []

    class DummyEngine:
        async def dispose(self) -> None:
            return None

    class DummySettings:
        database_url = "postgresql+asyncpg://fortress_api:test@127.0.0.1:5432/fortress_shadow_test"

    def fake_create_async_engine(url: str, **kwargs: object) -> DummyEngine:
        created.append({"url": url, **kwargs})
        return DummyEngine()

    monkeypatch.setattr(database, "async_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(database, "settings", DummySettings())

    assert database.async_engine is None

    first = database.get_async_engine()
    second = database.get_async_engine()

    assert first is second
    assert len(created) == 1
    assert created[0]["url"] == DummySettings.database_url
    assert created[0]["pool_pre_ping"] is True
    assert created[0]["pool_size"] == 20
    assert created[0]["max_overflow"] == 10


def test_session_factory_uses_lazy_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_engine = object()
    calls: list[dict[str, object]] = []

    class DummySessionFactory:
        def __call__(self) -> str:
            return "session"

    def fake_sessionmaker(bind: object, **kwargs: object) -> DummySessionFactory:
        calls.append({"bind": bind, **kwargs})
        return DummySessionFactory()

    lazy_factory = database._LazySessionFactory()
    monkeypatch.setattr(database, "AsyncSessionLocal", lazy_factory)
    monkeypatch.setattr(database, "async_session_factory", lazy_factory)
    monkeypatch.setattr(database, "async_session_maker", lazy_factory)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(database, "get_async_engine", lambda: dummy_engine)
    monkeypatch.setattr(database, "async_sessionmaker", fake_sessionmaker)

    factory = database.get_session_factory()

    assert factory is database.get_session_factory()
    assert calls == [
        {
            "bind": dummy_engine,
            "class_": database.AsyncSession,
            "autoflush": False,
            "expire_on_commit": False,
        }
    ]
    assert database._LazySessionFactory()() == "session"
    assert database.async_session_factory is database.AsyncSessionLocal
    assert database.async_session_maker is database.AsyncSessionLocal


def test_session_factory_respects_test_or_runtime_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    class PatchedFactory:
        pass

    patched_factory = PatchedFactory()

    monkeypatch.setattr(database, "AsyncSessionLocal", patched_factory)
    monkeypatch.setattr(database, "_session_factory", None)

    assert database.get_session_factory() is patched_factory


def test_legal_qdrant_runtime_callers_share_contract() -> None:
    assert qdrant_contract.LEGAL_WORK_PRODUCT_COLLECTION == "legal_ediscovery"
    assert (
        qdrant_contract.LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION
        == "legal_privileged_communications"
    )
    assert qdrant_contract.LEGAL_LEGACY_VECTOR_SIZE == 768
    assert (
        qdrant_contract.LEGAL_EDISCOVERY_ACTIVE_ALIAS
        in qdrant_contract.LEGAL_COLLECTIONS_UNSAFE_FOR_7IL
    )

    assert legal_ediscovery.QDRANT_COLLECTION == qdrant_contract.LEGAL_WORK_PRODUCT_COLLECTION
    assert (
        legal_ediscovery.QDRANT_PRIVILEGED_COLLECTION
        == qdrant_contract.LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION
    )
    assert vault_ingest_legal_case.QDRANT_COLLECTION == qdrant_contract.LEGAL_WORK_PRODUCT_COLLECTION
    assert vault_ingest_legal_case.EXPECTED_VECTOR_SIZE == qdrant_contract.LEGAL_LEGACY_VECTOR_SIZE
    assert (
        reprocess_failed_qdrant_uploads.QDRANT_WORK_PRODUCT_COLLECTION
        == qdrant_contract.LEGAL_WORK_PRODUCT_COLLECTION
    )
    assert (
        reprocess_failed_qdrant_uploads.QDRANT_PRIVILEGED_COLLECTION
        == qdrant_contract.LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION
    )
    assert (
        email_backfill_legal.QDRANT_COLLECTION_WORK_PRODUCT
        == qdrant_contract.LEGAL_WORK_PRODUCT_COLLECTION
    )
    assert (
        email_backfill_legal.QDRANT_COLLECTION_PRIVILEGED
        == qdrant_contract.LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION
    )
    assert email_backfill_legal.EXPECTED_VECTOR_SIZE == qdrant_contract.LEGAL_LEGACY_VECTOR_SIZE
    assert (
        backfill_vector_ids.QDRANT_WORK_PRODUCT_COLLECTION
        == qdrant_contract.LEGAL_WORK_PRODUCT_COLLECTION
    )
    assert (
        backfill_vector_ids.QDRANT_PRIVILEGED_COLLECTION
        == qdrant_contract.LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION
    )
    assert legal_council.LEGAL_COLLECTION == qdrant_contract.LEGAL_WORK_PRODUCT_COLLECTION
    assert (
        legal_council.PRIVILEGED_COLLECTION
        == qdrant_contract.LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION
    )


def test_legal_db_target_urls_are_explicit_and_parsed() -> None:
    base = (
        "postgresql://fortress_api:p%40ss@127.0.0.1:5432/"
        "fortress_shadow_test?sslmode=disable"
    )

    assert db_targets.legal_async_database_url(db_targets.LEGAL_CANONICAL_DB, base) == (
        "postgresql+asyncpg://fortress_api:p%40ss@127.0.0.1:5432/"
        "fortress_db?sslmode=disable"
    )
    assert db_targets.legal_async_database_url(db_targets.LEGAL_PROD_DB, base) == (
        "postgresql+asyncpg://fortress_api:p%40ss@127.0.0.1:5432/"
        "fortress_prod?sslmode=disable"
    )
    assert db_targets.legal_sync_database_url(db_targets.LEGAL_PROD_DB, base) == (
        "postgresql://fortress_api:p%40ss@127.0.0.1:5432/"
        "fortress_prod?sslmode=disable"
    )

    with pytest.raises(ValueError, match="unsupported Legal database target"):
        db_targets.legal_async_database_url("fortress_shadow", base)
