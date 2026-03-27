#!/usr/bin/env python3
"""
PHASE 1 — Read-only staff identity audit (sovereign Postgres).

Uses the same SQLAlchemy models as FastAPI auth. Does not modify data.

Usage:
  python backend/scripts/audit_staff_user.py --email cabin.rentals.of.georgia@gmail.com

Exit codes: 0 = user found, 1 = not found or error.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    s = str(candidate)
    if s not in sys.path:
        sys.path.insert(0, s)

for env_file in (REPO_ROOT / ".env", PROJECT_ROOT / ".env", REPO_ROOT / ".env.security"):
    if env_file.exists():
        load_dotenv(env_file, override=True)


async def _run(email: str) -> int:
    from backend.core.database import close_db, get_session_factory
    from backend.models.staff import StaffRole, StaffUser

    try:
        factory = get_session_factory()
        async with factory() as db:
            result = await db.execute(select(StaffUser).where(StaffUser.email == email.lower()))
            user = result.scalar_one_or_none()
            if user is None:
                print(f"NOT_FOUND: no staff_users row for email={email!r}", file=sys.stderr)
                return 1

            role = user.role
            if isinstance(role, StaffRole):
                role_value = role.value
            else:
                role_value = str(role)

            h = user.password_hash or ""
            hash_ok = h.startswith("$2")
            print(f"id:           {user.id}")
            print(f"email:        {user.email}")
            print(f"role:         {role_value}")
            print(f"is_active:    {user.is_active}")
            print(f"last_login:   {user.last_login_at}")
            print(f"bcrypt_hash:  {'yes' if hash_ok else 'NO — login will fail until re-hashed'} (prefix {h[:12]}…)")
            print(
                "zone_b_roles: super_admin | manager | reviewer "
                f"→ {'OK' if role_value in ('super_admin', 'manager', 'reviewer') else 'CHECK ROLE ENUM'}"
            )
            return 0
    finally:
        await close_db()


def main() -> None:
    p = argparse.ArgumentParser(description="Audit staff_users row by email.")
    p.add_argument("--email", required=True)
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args.email.strip())))


if __name__ == "__main__":
    main()
