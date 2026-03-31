#!/usr/bin/env python3
"""Fireclaw decontamination guest: extract PDF text and emit a sanitized JSON line."""

from __future__ import annotations

import hashlib
import json
import os
import string
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent
VENDOR_ROOT = AGENT_ROOT / "vendor"
if VENDOR_ROOT.exists():
    sys.path.insert(0, str(VENDOR_ROOT))

from pypdf import PdfReader  # type: ignore[import-not-found]

MAX_PAGES = 250
MAX_SANITIZED_CHARS = 250_000


def sanitize_text(text: str) -> str:
    printable = set(string.printable)
    cleaned = "".join(ch if ch in printable else " " for ch in text)
    compact = " ".join(cleaned.split())
    ascii_safe = compact.encode("ascii", "ignore").decode("ascii")
    return ascii_safe[:MAX_SANITIZED_CHARS]


def _extract_pdf_text(target_file: str) -> tuple[str, int]:
    reader = PdfReader(target_file)
    pages = min(len(reader.pages), MAX_PAGES)
    parts: list[str] = []
    for idx in range(pages):
        text = reader.pages[idx].extract_text() or ""
        parts.append(text)
    return "\n".join(parts), len(reader.pages)


def interrogate(payload_dir: str) -> None:
    try:
        files = sorted(
            name
            for name in os.listdir(payload_dir)
            if not name.startswith(".") and os.path.isfile(os.path.join(payload_dir, name))
        )
        if not files:
            raise RuntimeError("No payload found in mounted drive.")

        target_file = os.path.join(payload_dir, files[0])
        file_size = os.path.getsize(target_file)
        raw_text, page_count = _extract_pdf_text(target_file)
        clean_text = sanitize_text(raw_text)
        payload_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

        result = {
            "status": "success",
            "metadata": {
                "file_name": os.path.basename(target_file),
                "file_size_bytes": file_size,
                "pages": page_count,
                "sha256_hash": payload_hash,
                "sanitized_chars": len(clean_text),
            },
            "sanitized_content": clean_text,
        }
    except Exception as e:  # noqa: BLE001
        result = {"status": "error", "message": str(e)}
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        interrogate(sys.argv[1])
    else:
        print(json.dumps({"status": "error", "message": "missing payload dir"}), flush=True)
