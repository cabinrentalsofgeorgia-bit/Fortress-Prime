#!/usr/bin/env python3
"""
Mint a local staff JWT from the sovereign auth database.
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlsplit
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import select


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

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, close_db
from backend.core.security import create_access_token
from backend.models.staff import StaffRole, StaffUser


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mint a local Command Center JWT for a staff user.",
    )
    parser.add_argument(
        "staff_ref",
        help="Staff UUID or email address.",
    )
    parser.add_argument(
        "--path",
        default="/command/sovereign-pulse",
        help="Frontend path to target. Defaults to /command/sovereign-pulse",
    )
    parser.add_argument(
        "--frontend-base-url",
        default="",
        help="Override the frontend base URL used in the tactical link.",
    )
    parser.add_argument(
        "--min-stale-minutes",
        type=int,
        default=0,
        help="Recovery HQ stale threshold for the tactical URL.",
    )
    return parser.parse_args()


def _coerce_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _role_value(role: StaffRole | str) -> str:
    return role.value if isinstance(role, StaffRole) else str(role)


def _can_connect(base_url: str) -> bool:
    parsed = urlsplit(base_url)
    hostname = parsed.hostname
    if not hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((hostname, port), timeout=1.5):
            return True
    except OSError:
        return False


def _resolve_frontend_base_url(frontend_base_url: str) -> str:
    requested = _normalize_text(frontend_base_url).rstrip("/")
    candidates = [
        requested,
        _normalize_text(settings.frontend_url).rstrip("/"),
        "http://localhost:3000",
    ]

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if _can_connect(candidate):
            return candidate

    return requested or _normalize_text(settings.frontend_url).rstrip("/") or "http://localhost:3000"


def _build_tactical_url(token: str, base_url: str, path: str, min_stale_minutes: int) -> str:
    base = base_url.rstrip("/")
    normalized_path = "/" + path.lstrip("/")
    return (
        f"{base}{normalized_path}"
        f"?min_stale_minutes={min_stale_minutes}"
        f"&token={quote(token, safe='')}"
    )


async def _load_staff_user(staff_ref: str) -> StaffUser | None:
    staff_uuid = _coerce_uuid(staff_ref)
    normalized_email = _normalize_text(staff_ref).lower()

    async with AsyncSessionLocal() as session:
        if staff_uuid is not None:
            result = await session.execute(select(StaffUser).where(StaffUser.id == staff_uuid))
            user = result.scalar_one_or_none()
            if user is not None:
                return user

        result = await session.execute(
            select(StaffUser).where(StaffUser.email == normalized_email)
        )
        return result.scalar_one_or_none()


async def _run() -> int:
    args = _parse_args()
    user = await _load_staff_user(args.staff_ref)
    if user is None:
        print(f"[error] staff user not found for {args.staff_ref}")
        return 1
    if not user.is_active:
        print(f"[error] staff user is inactive: id={user.id} email={user.email}")
        return 1

    token = create_access_token(
        user_id=str(user.id),
        role=_role_value(user.role),
        email=user.email,
    )
    frontend_base_url = _resolve_frontend_base_url(str(args.frontend_base_url))
    tactical_url = _build_tactical_url(
        token=token,
        base_url=frontend_base_url,
        path=str(args.path),
        min_stale_minutes=int(args.min_stale_minutes),
    )

    print("[ok] local staff jwt minted")
    print(f"user_id={user.id}")
    print(f"email={user.email}")
    print(f"role={_role_value(user.role)}")
    print(f"frontend_base_url={frontend_base_url}")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"token={token}")
    print(f"tactical_url={tactical_url}")
    return 0


async def amain() -> int:
    try:
        return await _run()
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
