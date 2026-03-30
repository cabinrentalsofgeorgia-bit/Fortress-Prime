#!/usr/bin/env python3
"""
One-shot sync: all deployed SEO patch cabin slugs → Cloudflare KV.

Run on DGX with Fortress API env (CLOUDFLARE_* vars):

  cd fortress-guest-platform && PYTHONPATH=. python3 backend/scripts/sync_redirect_vanguard_kv.py
"""

from __future__ import annotations

import asyncio
import argparse
import os
import subprocess
import sys
from pathlib import Path

# Repo layout: fortress-guest-platform/backend/scripts/this_file.py — package root is fortress-guest-platform/
_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.services.redirect_vanguard_kv import (
    cabin_slug_from_patch_targets,
    redirect_vanguard_kv_configured,
    upsert_deployed_cabin_slug,
)


def _wrangler_config_path() -> Path:
    return _REPO_ROOT / "gateway" / "wrangler.redirect-vanguard.toml"


def _wrangler_working_directory() -> Path:
    return _REPO_ROOT / "gateway"


def _wrangler_fallback_available() -> bool:
    return _wrangler_config_path().exists() and _wrangler_working_directory().exists()


def _upsert_slug_with_wrangler(slug: str) -> bool:
    command = [
        "npx",
        "wrangler",
        "kv",
        "key",
        "put",
        slug,
        "1",
        "--config",
        str(_wrangler_config_path()),
        "--binding",
        "DEPLOYED_SLUGS",
        "--remote",
    ]
    result = subprocess.run(
        command,
        cwd=str(_wrangler_working_directory()),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode == 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Redirect Vanguard slugs to Cloudflare KV.")
    parser.add_argument(
        "--slug",
        action="append",
        default=[],
        help="Specific cabin slug to push. Repeatable. Requires deployed SEO patch unless --force is set.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow explicit --slug values even if no deployed SEO patch currently resolves to that slug.",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    async with AsyncSessionLocal() as db:
        stmt = (
            select(SEOPatch.page_path, Property.slug)
            .select_from(SEOPatch)
            .outerjoin(Property, SEOPatch.property_id == Property.id)
            .where(SEOPatch.status == "deployed")
        )
        result = await db.execute(stmt)
        slugs: set[str] = set()
        skipped = 0
        for page_path, prop_slug in result.all():
            s = cabin_slug_from_patch_targets(property_slug=prop_slug, page_path=str(page_path or ""))
            if s:
                slugs.add(s)
            else:
                skipped += 1

    explicit_slugs = {s.strip().lower() for s in args.slug if s and s.strip()}
    if explicit_slugs:
        if not args.force:
            missing = sorted(explicit_slugs - slugs)
            if missing:
                print(
                    "Refusing non-deployed slug(s) without --force: "
                    + ", ".join(missing)
                )
                return 2
        slugs = explicit_slugs

    use_wrangler_fallback = not redirect_vanguard_kv_configured() and _wrangler_fallback_available()
    if not redirect_vanguard_kv_configured() and not use_wrangler_fallback:
        print("CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_KV_NAMESPACE_DEPLOYED_SLUGS required.")
        return 2

    ok = 0
    if use_wrangler_fallback:
        print(f"sync_mode=wrangler_fallback config={_wrangler_config_path()}")
    for s in sorted(slugs):
        if use_wrangler_fallback:
            wrote = _upsert_slug_with_wrangler(s)
        else:
            wrote = await upsert_deployed_cabin_slug(s)
        if wrote:
            ok += 1
        print(f"upsert {s}")

    print(f"done: upserted={ok}/{len(slugs)} skipped_rows={skipped}")
    return 0 if ok == len(slugs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
