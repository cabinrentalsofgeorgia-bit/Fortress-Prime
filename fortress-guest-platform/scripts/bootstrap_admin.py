#!/usr/bin/env python3
"""Bootstrap the sovereign root admin account in fortress_prod."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT.parent / ".env.security")

from backend.core.database import AsyncSessionLocal, close_db  # noqa: E402
from backend.core.security import hash_password  # noqa: E402
from backend.models.staff import StaffUser  # noqa: E402


DEFAULT_ADMIN_EMAIL = "cabin.rentals.of.georgia@gmail.com"
DEFAULT_FIRST_NAME = "Gary"
DEFAULT_LAST_NAME = "Knight"


@dataclass(frozen=True)
class BootstrapConfig:
    email: str
    first_name: str
    last_name: str
    notification_email: str
    rotate_existing: bool


def _require_sovereign_postgres_contract() -> None:
    postgres_api_uri = os.getenv("POSTGRES_API_URI", "").strip()
    postgres_admin_uri = os.getenv("POSTGRES_ADMIN_URI", "").strip()

    if not postgres_api_uri or not postgres_admin_uri:
        raise RuntimeError(
            "POSTGRES_API_URI and POSTGRES_ADMIN_URI must be set for fortress_prod."
        )

    if "127.0.0.1:5432/fortress_prod" not in postgres_api_uri:
        raise RuntimeError("POSTGRES_API_URI must target fortress_prod on 127.0.0.1:5432.")
    if "127.0.0.1:5432/fortress_prod" not in postgres_admin_uri:
        raise RuntimeError(
            "POSTGRES_ADMIN_URI must target fortress_prod on 127.0.0.1:5432."
        )


def _read_password_pair() -> str:
    # Default path is interactive and never echoes the secret.
    env_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    env_confirm = os.getenv("BOOTSTRAP_ADMIN_CONFIRM_PASSWORD", env_password)
    if env_password:
        if env_password != env_confirm:
            raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD and confirmation do not match.")
        if len(env_password) < 12:
            raise RuntimeError("Password must be at least 12 characters.")
        return env_password

    password = getpass.getpass("New root admin password: ")
    confirm = getpass.getpass("Confirm root admin password: ")
    if password != confirm:
        raise RuntimeError("Passwords did not match.")
    if len(password) < 12:
        raise RuntimeError("Password must be at least 12 characters.")
    return password


def _build_permissions() -> dict[str, bool]:
    return {
        "can_send_messages": True,
        "can_edit_properties": True,
    }


async def _bootstrap_admin(config: BootstrapConfig, password: str) -> None:
    normalized_email = config.email.strip().lower()

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(StaffUser).where(StaffUser.email == normalized_email)
            )
        ).scalar_one_or_none()

        if existing is not None:
            if not config.rotate_existing:
                print(
                    "[bootstrap] admin already exists "
                    f"(id={existing.id}, email={existing.email}, active={existing.is_active})"
                )
                return

            existing.password_hash = hash_password(password)
            existing.first_name = config.first_name
            existing.last_name = config.last_name
            existing.role = "admin"
            existing.permissions = _build_permissions()
            existing.notification_email = config.notification_email
            existing.is_active = True
            await session.commit()
            print(f"[bootstrap] rotated password for existing admin {existing.email}")
            return

        session.add(
            StaffUser(
                email=normalized_email,
                password_hash=hash_password(password),
                first_name=config.first_name,
                last_name=config.last_name,
                role="admin",
                permissions=_build_permissions(),
                is_active=True,
                notification_email=config.notification_email,
                notify_urgent=True,
                notify_workorders=True,
            )
        )
        await session.commit()
        print(f"[bootstrap] created root admin {normalized_email}")


def _parse_args() -> BootstrapConfig:
    parser = argparse.ArgumentParser(
        description="Create or rotate the sovereign root admin account."
    )
    parser.add_argument("--email", default=DEFAULT_ADMIN_EMAIL)
    parser.add_argument("--first-name", default=DEFAULT_FIRST_NAME)
    parser.add_argument("--last-name", default=DEFAULT_LAST_NAME)
    parser.add_argument("--notification-email", default=DEFAULT_ADMIN_EMAIL)
    parser.add_argument(
        "--rotate-existing",
        action="store_true",
        help="Rotate password and restore admin role if the account already exists.",
    )
    args = parser.parse_args()
    return BootstrapConfig(
        email=str(args.email),
        first_name=str(args.first_name),
        last_name=str(args.last_name),
        notification_email=str(args.notification_email).strip().lower(),
        rotate_existing=bool(args.rotate_existing),
    )


async def amain() -> int:
    _require_sovereign_postgres_contract()
    config = _parse_args()
    password = _read_password_pair()
    try:
        await _bootstrap_admin(config, password)
        return 0
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
