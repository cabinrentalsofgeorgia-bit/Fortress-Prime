from __future__ import annotations

import argparse
import asyncio
import json
import os

from dotenv import dotenv_values

for key, value in dotenv_values(".env").items():
    if value is not None:
        os.environ.setdefault(key, value)

from backend.services.competitive_sentinel import competitive_sentinel


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill property OTA metadata using grounded search.")
    parser.add_argument("--slug", dest="slug", help="Limit backfill to a single property slug.")
    parser.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_true",
        help="Overwrite existing ota_metadata provider URLs when discovered again.",
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    result = await competitive_sentinel.backfill_ota_metadata(
        property_slug=args.slug,
        overwrite=bool(args.overwrite),
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_main())
