"""
Gateway Schema — Auth Tables & Seeding
=========================================
Creates fortress_users and fortress_api_keys tables.
Seeds the admin user and a service API key on first run.

Usage:
    python -m gateway.schema          # Create tables + seed
    python -m gateway.schema --reset  # Drop and recreate (DANGER)
"""

import os
import sys
import secrets
import logging
import argparse

from gateway.auth import bcrypt  # Uses _BcryptCompat (raw bcrypt, no passlib)

logger = logging.getLogger("gateway.schema")

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS fortress_users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(50) UNIQUE NOT NULL,
    email           VARCHAR(255),
    password        VARCHAR(255) NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('admin', 'operator', 'viewer')),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    last_login      TIMESTAMP,
    full_name       VARCHAR(100),
    web_ui_access   BOOLEAN NOT NULL DEFAULT FALSE,
    vrs_access      BOOLEAN NOT NULL DEFAULT FALSE
);
"""

ENSURE_ACCESS_COLUMNS = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fortress_users' AND column_name = 'web_ui_access'
    ) THEN
        ALTER TABLE fortress_users ADD COLUMN web_ui_access BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fortress_users' AND column_name = 'vrs_access'
    ) THEN
        ALTER TABLE fortress_users ADD COLUMN vrs_access BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fortress_users' AND column_name = 'full_name'
    ) THEN
        ALTER TABLE fortress_users ADD COLUMN full_name VARCHAR(100);
    END IF;
END $$;
"""

CREATE_API_KEYS = """
CREATE TABLE IF NOT EXISTS fortress_api_keys (
    id          SERIAL PRIMARY KEY,
    key_prefix  VARCHAR(12) NOT NULL,
    key_hash    VARCHAR(255) UNIQUE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    scopes      TEXT[] DEFAULT '{}',
    owner_id    INTEGER REFERENCES fortress_users(id),
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW(),
    last_used   TIMESTAMP
);
"""

DROP_TABLES = """
DROP TABLE IF EXISTS fortress_api_keys CASCADE;
DROP TABLE IF EXISTS fortress_users CASCADE;
"""


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def _generate_api_key() -> str:
    """Generate a prefixed API key: frt_<32 hex chars>."""
    return f"frt_{secrets.token_hex(16)}"


def seed(conn):
    """Seed admin user and service API key if they don't exist."""
    cur = conn.cursor()

    # --- Admin user ---
    cur.execute("SELECT id FROM fortress_users WHERE username = 'admin'")
    if cur.fetchone() is None:
        password = os.getenv("GATEWAY_ADMIN_PASSWORD", "")
        if not password:
            password = secrets.token_urlsafe(16)
            print(f"\n  ** GENERATED ADMIN PASSWORD (save this): {password}\n")

        hashed = bcrypt.hash(password)
        cur.execute(
            """INSERT INTO fortress_users (username, email, password, role)
               VALUES ('admin', 'admin@fortress.local', %s, 'admin')
               RETURNING id""",
            (hashed,),
        )
        admin_id = cur.fetchone()[0]
        logger.info(f"Seeded admin user (id={admin_id})")
    else:
        cur.execute("SELECT id FROM fortress_users WHERE username = 'admin'")
        admin_id = cur.fetchone()[0]
        logger.info("Admin user already exists, skipping.")

    # --- Operator user (Gary) ---
    cur.execute("SELECT id FROM fortress_users WHERE username = 'gary'")
    if cur.fetchone() is None:
        gary_pass = os.getenv("GATEWAY_GARY_PASSWORD", "")
        if not gary_pass:
            gary_pass = secrets.token_urlsafe(12)
            print(f"  ** GENERATED OPERATOR PASSWORD for 'gary': {gary_pass}\n")
        hashed = bcrypt.hash(gary_pass)
        cur.execute(
            """INSERT INTO fortress_users (username, email, password, role)
               VALUES ('gary', 'gary@garyknight.com', %s, 'operator')""",
            (hashed,),
        )
        logger.info("Seeded operator user 'gary'")

    # --- Service API key (for cron jobs) ---
    cur.execute(
        "SELECT id FROM fortress_api_keys WHERE name = 'cron-service'"
    )
    if cur.fetchone() is None:
        raw_key = _generate_api_key()
        key_hash = bcrypt.hash(raw_key)
        prefix = raw_key[:12]  # "frt_XXXXXXXX"
        cur.execute(
            """INSERT INTO fortress_api_keys
                   (key_prefix, key_hash, name, scopes, owner_id)
               VALUES (%s, %s, 'cron-service',
                       %s, %s)""",
            (prefix, key_hash,
             ["ops:read", "ops:write", "finance:read", "sovereign:read"],
             admin_id),
        )
        print(f"  ** SERVICE API KEY (save this — shown once): {raw_key}\n")
        logger.info("Seeded cron-service API key")
    else:
        logger.info("cron-service API key already exists, skipping.")

    # Ensure all admin accounts have web_ui_access and vrs_access
    cur.execute(
        "UPDATE fortress_users SET web_ui_access = TRUE, vrs_access = TRUE "
        "WHERE role = 'admin' AND (web_ui_access = FALSE OR vrs_access = FALSE)"
    )

    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_schema(conn, reset: bool = False):
    """Create auth tables, run migrations, and seed initial data."""
    cur = conn.cursor()

    if reset:
        logger.warning("DROPPING auth tables!")
        cur.execute(DROP_TABLES)
        conn.commit()

    cur.execute(CREATE_USERS)
    cur.execute(CREATE_API_KEYS)
    cur.execute(ENSURE_ACCESS_COLUMNS)
    conn.commit()
    cur.close()

    logger.info("Auth tables ready (access columns verified).")
    seed(conn)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Gateway Schema Init")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate auth tables (DANGER)")
    args = parser.parse_args()

    # Import here to avoid circular deps
    from gateway.db import get_conn

    print("=" * 60)
    print("  FORTRESS PRIME — GATEWAY SCHEMA INIT")
    print("=" * 60)

    with get_conn() as conn:
        init_schema(conn, reset=args.reset)

    print("  Done.")
    print("=" * 60)


if __name__ == "__main__":
    main()
