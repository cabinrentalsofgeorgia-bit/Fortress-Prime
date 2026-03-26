#!/usr/bin/env python3
"""
One-shot staff password reset (sovereign Postgres). Uses the same bcrypt hasher as FastAPI login.

Non-interactive (DGX / automation):
  FGP_STAFF_PASSWORD_RESET='your-secure-secret' \\
    python backend/scripts/reset_staff_password.py --email user@example.com

Interactive:
  python backend/scripts/reset_staff_password.py --email user@example.com
  (prompts twice; nothing sent on argv)

Delete this file after use if policy requires.
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


async def _run(
    email: str,
    plain: str,
    *,
    create_if_missing: bool,
    first_name: str,
    last_name: str,
    role_value: str,
) -> int:
    from backend.core.database import close_db, get_session_factory
    from backend.core.security import hash_password
    from backend.models.staff import StaffRole, StaffUser

    try:
        factory = get_session_factory()
        async with factory() as db:
            result = await db.execute(select(StaffUser).where(StaffUser.email == email.lower()))
            user = result.scalar_one_or_none()
            if user is None:
                if not create_if_missing:
                    print(f"No staff_users row for email={email!r}", file=sys.stderr)
                    print(
                        "Hint: re-run with --create-if-missing (and optional --first-name / --last-name / --role).",
                        file=sys.stderr,
                    )
                    return 1
                try:
                    role = StaffRole(role_value.strip().lower())
                except ValueError:
                    print(
                        f"Invalid --role {role_value!r}; use one of: "
                        f"{', '.join(r.value for r in StaffRole)}",
                        file=sys.stderr,
                    )
                    return 1
                user = StaffUser(
                    email=email.lower(),
                    password_hash=hash_password(plain),
                    first_name=first_name.strip() or "Staff",
                    last_name=last_name.strip() or "User",
                    role=role,
                    is_active=True,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                print(f"Created staff user id={user.id} email={user.email!r} role={user.role.value}")
                return 0

            user.password_hash = hash_password(plain)
            await db.commit()
            print(f"Password updated for staff user id={user.id} email={user.email!r}")
            return 0
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset staff_users.password_hash (bcrypt).")
    parser.add_argument("--email", required=True, help="Staff email (matched case-insensitively in DB).")
    parser.add_argument(
        "--min-length",
        type=int,
        default=8,
        help="Minimum password length (default 8).",
    )
    parser.add_argument(
        "--create-if-missing",
        action="store_true",
        help="If no row exists for --email, insert a new staff_users row (break-glass).",
    )
    parser.add_argument("--first-name", default="Admin", help="With --create-if-missing (default Admin).")
    parser.add_argument("--last-name", default="User", help="With --create-if-missing (default User).")
    parser.add_argument(
        "--role",
        default="super_admin",
        help="With --create-if-missing (default super_admin).",
    )
    args = parser.parse_args()
    email = args.email.strip()

    plain = os.environ.get("FGP_STAFF_PASSWORD_RESET", "").strip()
    if not plain:
        a = getpass.getpass("New password: ")
        b = getpass.getpass("Confirm new password: ")
        if a != b:
            print("Passwords do not match.", file=sys.stderr)
            sys.exit(1)
        plain = a

    if len(plain) < args.min_length:
        print(f"Password must be at least {args.min_length} characters.", file=sys.stderr)
        sys.exit(1)

    code = asyncio.run(
        _run(
            email,
            plain,
            create_if_missing=args.create_if_missing,
            first_name=args.first_name,
            last_name=args.last_name,
            role_value=args.role,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
