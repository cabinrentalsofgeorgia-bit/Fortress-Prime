#!/usr/bin/env python3
"""
Force-seed the master admin staff account for the Fortress Guest Platform.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

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
from backend.models.property import Property
from backend.models.media import PropertyImage
from backend.models.staff import StaffRole, StaffUser


ADMIN_EMAIL = "cabin.rentals.of.georgia@gmail.com"
ADMIN_PASSWORD = "FortressPrime2026!"
ADMIN_FIRST_NAME = "Gary"
ADMIN_LAST_NAME = "Knight"
CI_FIXTURE_PROPERTY_ID = UUID("11111111-1111-1111-1111-111111111111")
CI_FIXTURE_PROPERTY_SLUG = "aska-escape-lodge"
CI_FIXTURE_PROPERTY_NAME = "Aska Escape Lodge"


def build_admin_permissions() -> dict[str, bool]:
    # `role="super_admin"` is the actual privilege gate in the API. The JSONB
    # permissions field is open-ended, so seed only the documented flags.
    return {
        "can_send_messages": True,
        "can_edit_properties": True,
    }


def _build_ci_rate_card() -> dict[str, object]:
    current_year = datetime.utcnow().year
    return {
        "rates": [
            {
                "start_date": f"{current_year - 1}-01-01",
                "end_date": f"{current_year + 2}-12-31",
                "nightly": "325.00",
            }
        ],
        "fees": [
            {
                "name": "Cleaning Fee",
                "amount": "150.00",
            }
        ],
        "taxes": [
            {
                "name": "Lodging Tax",
                "type": "percent",
                "rate": "0.13",
            }
        ],
    }


async def seed_ci_storefront_fixture(session: AsyncSessionLocal) -> None:
    if not os.getenv("CI"):
        return

    fixture = (
        await session.execute(
            select(Property).where(Property.slug == CI_FIXTURE_PROPERTY_SLUG)
        )
    ).scalar_one_or_none()

    if fixture is None:
        fixture = Property(
            id=CI_FIXTURE_PROPERTY_ID,
            name=CI_FIXTURE_PROPERTY_NAME,
            slug=CI_FIXTURE_PROPERTY_SLUG,
            property_type="cabin",
            bedrooms=3,
            bathrooms=3.0,
            max_guests=8,
            address="Blue Ridge, Georgia",
            parking_instructions="Private driveway parking is available on site.",
            rate_card=_build_ci_rate_card(),
            streamline_property_id="ci-aska-escape-lodge",
            is_active=True,
        )
        session.add(fixture)
        await session.flush()
        print(f"[seed] ci storefront fixture created slug={fixture.slug} id={fixture.id}")
        return

    fixture.name = CI_FIXTURE_PROPERTY_NAME
    fixture.property_type = "cabin"
    fixture.bedrooms = 3
    fixture.bathrooms = 3.0
    fixture.max_guests = 8
    fixture.address = "Blue Ridge, Georgia"
    fixture.parking_instructions = "Private driveway parking is available on site."
    fixture.rate_card = _build_ci_rate_card()
    fixture.streamline_property_id = "ci-aska-escape-lodge"
    fixture.is_active = True
    print(f"[seed] ci storefront fixture reconciled slug={fixture.slug} id={fixture.id}")


async def ensure_master_admin(session: AsyncSessionLocal) -> tuple[StaffUser, bool]:
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
        await session.flush()
        return existing_user, False

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
    await session.flush()
    return user, True


async def seed_master_admin() -> int:
    if not os.getenv("POSTGRES_API_URI", "").strip():
        if not LOADED_ENV_FILES:
            raise RuntimeError(
                "POSTGRES_API_URI is not set and no environment files were loaded."
            )
        raise RuntimeError("POSTGRES_API_URI is not set after loading .env files.")

    # CI uses a disposable Postgres service. Ensure only the core auth table
    # exists before querying so we do not pull in unrelated schema namespaces.
    bootstrap_tables = [StaffUser.__table__]
    if os.getenv("CI"):
        bootstrap_tables.extend(
            [
                Property.__table__,
                PropertyImage.__table__,
            ]
        )

    async with async_engine.begin() as connection:
        await connection.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=bootstrap_tables,
            )
        )

    async with AsyncSessionLocal() as session:
        user, created = await ensure_master_admin(session)
        await seed_ci_storefront_fixture(session)
        await session.commit()
        await session.refresh(user)

        if created:
            print("[seed] master admin created successfully")
        else:
            print(
                "[seed] master admin reconciled "
                f"(id={user.id}, role={user.role}, active={user.is_active})"
            )
        print(f"[seed] user_id={user.id} email={user.email} role={user.role} active={user.is_active}")
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
