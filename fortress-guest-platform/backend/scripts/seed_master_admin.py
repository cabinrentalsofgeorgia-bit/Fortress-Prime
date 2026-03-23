#!/usr/bin/env python3
"""
Force-seed the master admin staff account for the Fortress Guest Platform.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def load_environment() -> list[Path]:
    loaded_files: list[Path] = []
    env_files = [
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ]

    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file, override=True)
            loaded_files.append(env_file)

    return loaded_files


LOADED_ENV_FILES = load_environment()

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal, Base, async_engine, close_db
from backend.core.security import hash_password
from backend.models.staff import StaffRole, StaffUser


ADMIN_EMAIL = "cabin.rentals.of.georgia@gmail.com"
ADMIN_PASSWORD = "FortressPrime2026!"
ADMIN_FIRST_NAME = "Gary"
ADMIN_LAST_NAME = "Knight"


def build_admin_permissions() -> dict[str, bool]:
    # `role="super_admin"` is the actual privilege gate in the API. The JSONB
    # permissions field is open-ended, so seed only the documented flags.
    return {
        "can_send_messages": True,
        "can_edit_properties": True,
    }


async def seed_master_admin() -> int:
    if not os.getenv("POSTGRES_API_URI", "").strip():
        if not LOADED_ENV_FILES:
            raise RuntimeError(
                "POSTGRES_API_URI is not set and no environment files were loaded."
            )
        raise RuntimeError("POSTGRES_API_URI is not set after loading .env files.")

    # CI uses a disposable Postgres service. Ensure the core auth table exists
    # before querying so the deterministic admin bootstrap can run on a blank DB.
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(StaffUser).where(StaffUser.email == ADMIN_EMAIL.lower())
        )
        existing_user = result.scalar_one_or_none()

        if existing_user is not None:
            existing_user.password_hash = hash_password(ADMIN_PASSWORD)
            existing_user.first_name = ADMIN_FIRST_NAME
            existing_user.last_name = ADMIN_LAST_NAME
            existing_user.role = StaffRole.SUPER_ADMIN
            existing_user.permissions = build_admin_permissions()
            existing_user.is_active = True
            existing_user.notification_email = ADMIN_EMAIL.lower()
            existing_user.notify_urgent = True
            existing_user.notify_workorders = True
            await session.commit()
            print(
                "[seed] master admin reconciled "
                f"(id={existing_user.id}, role={existing_user.role}, active={existing_user.is_active})"
            )
            return 0

        user = StaffUser(
            email=ADMIN_EMAIL.lower(),
            password_hash=hash_password(ADMIN_PASSWORD),
            first_name=ADMIN_FIRST_NAME,
            last_name=ADMIN_LAST_NAME,
            role=StaffRole.SUPER_ADMIN,
            permissions=build_admin_permissions(),
            is_active=True,
            notification_email=ADMIN_EMAIL.lower(),
            notify_urgent=True,
            notify_workorders=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        print("[seed] master admin created successfully")
        print(
            f"[seed] user_id={user.id} email={user.email} role={user.role} active={user.is_active}"
        )
        return 0


async def amain() -> int:
    try:
        return await seed_master_admin()
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
