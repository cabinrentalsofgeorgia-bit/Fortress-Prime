#!/usr/bin/env python3
"""Verify Gary Knight's staff password without mutating data.

The command reads the password using a no-echo prompt and checks it with the
same verify_password() helper used by the FastAPI login endpoint. It never
prints the password or stored hash.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

AUTHORIZED_EMAIL = "gary@cabin-rentals-of-georgia.com"
LOGIN_BACKEND_TABLE = "public.staff_users"

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


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


async def _verify(email: str, password: str) -> int:
    from backend.core.database import close_db, get_session_factory
    from backend.core.security import verify_password
    from backend.models.staff import StaffUser

    normalized_email = email.lower()

    try:
        factory = get_session_factory()
        async with factory() as db:
            result = await db.execute(
                select(StaffUser).where(StaffUser.email == normalized_email)
            )
            user = result.scalar_one_or_none()

            print(f"LOGIN_BACKEND_TABLE {LOGIN_BACKEND_TABLE}")
            print("EMAIL_NORMALIZATION_USED lower(email)")
            print(f"USER_FOUND {_yes_no(user is not None)}")

            if user is None:
                print("ACTIVE no")
                print("ROLE none")
                print("HASH_ALGORITHM_MATCH no")
                print("PASSWORD_MATCH no")
                return 1

            password_hash = user.password_hash or ""
            hash_algorithm_match = password_hash.startswith(("$2a$", "$2b$", "$2y$"))
            password_match = hash_algorithm_match and verify_password(password, password_hash)
            role = getattr(user.role, "value", str(user.role))

            print(f"ACTIVE {_yes_no(bool(user.is_active))}")
            print(f"ROLE {role}")
            print(f"HASH_ALGORITHM_MATCH {_yes_no(hash_algorithm_match)}")
            print(f"PASSWORD_MATCH {_yes_no(password_match)}")
            return 0 if password_match and user.is_active else 1
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Gary Knight's Command Center staff password without database writes."
    )
    parser.add_argument("--email", default=AUTHORIZED_EMAIL)
    args = parser.parse_args()

    email = args.email.strip().lower()
    if email != AUTHORIZED_EMAIL:
        print(f"ERROR this command only supports {AUTHORIZED_EMAIL}", file=sys.stderr)
        raise SystemExit(2)

    if os.environ.get("FORTRESS_ALLOW_STAFF_PASSWORD_VERIFY") != "1":
        print(
            "ERROR set FORTRESS_ALLOW_STAFF_PASSWORD_VERIFY=1 for this verify-only check",
            file=sys.stderr,
        )
        raise SystemExit(2)

    password = getpass.getpass("Gary staff password to verify: ")
    raise SystemExit(asyncio.run(_verify(email, password)))


if __name__ == "__main__":
    main()
