"""
Canonical Legal database target helpers.

Legal runtime still spans the shared API database plus the operational
fortress_db / fortress_prod pair. These helpers make target selection explicit
and avoid ad hoc path replacement in session factories.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import SplitResult, urlsplit, urlunsplit

LEGAL_CANONICAL_DB: Final = "fortress_db"
LEGAL_PROD_DB: Final = "fortress_prod"
LEGAL_RUNTIME_DBS: Final = frozenset({LEGAL_CANONICAL_DB, LEGAL_PROD_DB})

_ASYNC_SCHEME = "postgresql+asyncpg"
_SYNC_SCHEME = "postgresql"
_POSTGRES_SCHEMES = frozenset({"postgres", "postgresql", "postgresql+asyncpg"})


def _target_url(base_url: str, target_db: str, *, async_driver: bool) -> str:
    if target_db not in LEGAL_RUNTIME_DBS:
        raise ValueError(f"unsupported Legal database target: {target_db!r}")

    parsed = urlsplit(base_url)
    if parsed.scheme not in _POSTGRES_SCHEMES:
        raise ValueError("Legal database targets require a PostgreSQL URL")
    if not parsed.netloc:
        raise ValueError("Legal database target URL is missing host credentials")

    scheme = _ASYNC_SCHEME if async_driver else _SYNC_SCHEME
    return urlunsplit(
        SplitResult(
            scheme=scheme,
            netloc=parsed.netloc,
            path=f"/{target_db}",
            query=parsed.query,
            fragment=parsed.fragment,
        )
    )


def legal_async_database_url(target_db: str, base_url: str | None = None) -> str:
    """Return an async SQLAlchemy URL for a Legal runtime target DB."""
    if base_url is None:
        from backend.core.config import settings

        base_url = settings.database_url
    return _target_url(base_url, target_db, async_driver=True)


def legal_sync_database_url(target_db: str, base_url: str | None = None) -> str:
    """Return a sync PostgreSQL URL for scripts or psycopg-style clients."""
    if base_url is None:
        from backend.core.config import settings

        base_url = settings.alembic_database_url
    return _target_url(base_url, target_db, async_driver=False)
