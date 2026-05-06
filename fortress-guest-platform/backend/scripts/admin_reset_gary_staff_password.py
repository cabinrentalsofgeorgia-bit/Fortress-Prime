#!/usr/bin/env python3
"""Gary-only production staff password reset.

Reads the new password with no terminal echo, hashes it with the same bcrypt
helper used by FastAPI login, and updates only Gary Knight's existing
staff_users row. Plaintext and hash values are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

AUTHORIZED_EMAIL = "gary@cabin-rentals-of-georgia.com"
MIN_PASSWORD_LENGTH = 14

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

for env_file in (REPO_ROOT / ".env", PROJECT_ROOT / ".env", REPO_ROOT / ".env.security"):
    if env_file.exists():
        load_dotenv(env_file, override=True)


def _validate_password(value: str) -> None:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if value.lower() == value or value.upper() == value:
        raise ValueError("Password must include mixed case.")
    if not any(ch.isdigit() for ch in value):
        raise ValueError("Password must include at least one digit.")
    if not any(not ch.isalnum() for ch in value):
        raise ValueError("Password must include at least one symbol.")


def _read_password() -> str:
    first = getpass.getpass("New Gary staff password: ")
    second = getpass.getpass("Confirm Gary staff password: ")
    if first != second:
        raise ValueError("Passwords do not match.")
    _validate_password(first)
    return first


async def _reset_password(email: str, password: str) -> int:
    from backend.core.database import close_db, get_session_factory
    from backend.core.security import hash_password
    from backend.models.staff import StaffUser

    try:
        factory = get_session_factory()
        async with factory() as db:
            result = await db.execute(select(StaffUser).where(StaffUser.email == email))
            user = result.scalar_one_or_none()
            if user is None:
                print("ERROR: Gary staff user was not found; no user was created.", file=sys.stderr)
                return 1

            user.password_hash = hash_password(password)
            user.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(user)

            role = getattr(user.role, "value", str(user.role))
            print(f"email: {user.email}")
            print(f"user_id: {user.id}")
            print(f"role: {role}")
            print(f"updated_at: {user.updated_at.isoformat() if user.updated_at else 'unknown'}")
            print("sessions_revoked: no")
            return 0
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset only Gary Knight's production Command Center staff password."
    )
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    email = args.email.strip().lower()
    if email != AUTHORIZED_EMAIL:
        print(f"ERROR: this command only supports {AUTHORIZED_EMAIL}.", file=sys.stderr)
        raise SystemExit(2)

    if os.environ.get("FORTRESS_ALLOW_STAFF_PASSWORD_RESET") != "1":
        print(
            "ERROR: set FORTRESS_ALLOW_STAFF_PASSWORD_RESET=1 for this authorized reset.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        password = _read_password()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    raise SystemExit(asyncio.run(_reset_password(email, password)))


if __name__ == "__main__":
    main()
