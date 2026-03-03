"""
Fortress Vault — Centralized Secrets Access
=============================================
Single source of truth for database credentials and sensitive config.
All modules MUST import from here instead of hardcoding fallbacks.

Usage:
    from src.vault import db_conn_params, get_secret

    conn = psycopg2.connect(**db_conn_params())
    api_key = get_secret("NGC_API_KEY")
"""

import os
import sys
import logging
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger("fortress.vault")

# Find and load .env (walk up from this file to project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        pass  # dotenv not installed; env vars must be set externally


# =============================================================================
# REQUIRED SECRETS — fail fast if missing
# =============================================================================

_REQUIRED_DB = ["DB_NAME", "DB_USER"]
_OPTIONAL_DB = ["DB_PASS", "DB_HOST", "DB_PORT"]


def _check_env(name: str, default=None, required=False):
    """Get env var, optionally raising if required and missing."""
    val = os.getenv(name, default)
    if required and not val:
        logger.critical(f"MISSING REQUIRED SECRET: {name}")
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            f"Check your .env file at {_ENV_FILE}"
        )
    return val


# =============================================================================
# DATABASE
# =============================================================================

def db_conn_params(
    host_override: str = None,
    user_override: str = None,
    dbname_override: str = None,
) -> dict:
    """Return psycopg2.connect(**kwargs) dict from env vars.

    No hardcoded passwords. Relies on .env or PG trust auth.
    """
    return {
        "dbname": dbname_override or os.getenv("DB_NAME", "fortress_db"),
        "user": user_override or os.getenv("DB_USER", "admin"),
        "password": os.getenv("DB_PASS", ""),
        "host": host_override or os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
    }


def get_db_url() -> str:
    """Return SQLAlchemy-style database URL from env vars."""
    p = db_conn_params()
    pw = f":{p['password']}" if p["password"] else ""
    return f"postgresql://{p['user']}{pw}@{p['host']}:{p['port']}/{p['dbname']}"


# =============================================================================
# GENERIC SECRET ACCESS
# =============================================================================

def get_secret(name: str, default: str = None) -> str:
    """Get a secret from environment.

    Checks (in order):
      1. Environment variable
      2. Docker secret file at /run/secrets/<name>
      3. Default value
    """
    # Env var first
    val = os.getenv(name)
    if val:
        return val

    # Docker secrets (mounted at /run/secrets/)
    secret_file = Path(f"/run/secrets/{name.lower()}")
    if secret_file.exists():
        return secret_file.read_text().strip()

    if default is not None:
        return default

    return ""


# =============================================================================
# STARTUP VALIDATION
# =============================================================================

def validate_secrets(required: list[str] = None) -> bool:
    """Check that all required secrets are present. Log warnings for missing."""
    if required is None:
        required = _REQUIRED_DB

    missing = []
    for name in required:
        if not os.getenv(name):
            missing.append(name)

    if missing:
        logger.warning(f"Missing secrets: {', '.join(missing)}")
        return False

    logger.info("All required secrets validated")
    return True
