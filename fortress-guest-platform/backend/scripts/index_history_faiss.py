#!/usr/bin/env python3
"""
Build or refresh the persisted history index for the Librarian lane.

Usage:
  cd fortress-guest-platform
  python3 -m backend.scripts.index_history_faiss --history-path /mnt/history
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.history_query_tool import HistoryLibrarian


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild the Synology history index.")
    parser.add_argument("--history-path", default=os.getenv("FORTRESS_HISTORY_PATH", "/mnt/history"))
    parser.add_argument("--index-path", default=os.getenv("FORTRESS_HISTORY_INDEX_PATH"))
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    librarian = HistoryLibrarian(
        history_path=args.history_path,
        index_path=args.index_path or str(Path(args.history_path) / ".history_index"),
    )
    result = await librarian.rebuild_persistent_index()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
