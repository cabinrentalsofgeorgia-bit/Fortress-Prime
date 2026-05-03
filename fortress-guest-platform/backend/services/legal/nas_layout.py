"""Shared Fortress Legal NAS layout normalization.

legal.cases.nas_layout exists in two supported shapes:

* legacy/API shape: {"root": "...", "subdirs": {logical: relative}, "recursive": bool}
* Wave 7 ingest shape: {"primary_root": "...", "include_subdirs": [...], "exclude_subdirs": [...]}

This module keeps the interpretation in one place so the command-center API
and vault ingest pipeline walk the same curated source paths.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_LEGAL_NAS_ROOT = "/mnt/fortress_nas/sectors/legal"

DEFAULT_CASE_SUBDIR_MAP: dict[str, str] = {
    "certified_mail": "certified_mail",
    "correspondence": "correspondence",
    "evidence": "evidence",
    "receipts": "receipts",
    "filings_incoming": "filings/incoming",
    "filings_outgoing": "filings/outgoing",
}


class LayoutNormalizationError(ValueError):
    """Raised when a required nas_layout value cannot be normalized."""


@dataclass(frozen=True)
class NormalizedCaseLayout:
    root: Path
    subdirs: dict[str, str]
    recursive: bool
    exclude_subdirs: frozenset[str]
    custom_layout: bool

    def as_ingest_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "subdirs": dict(self.subdirs),
            "recursive": self.recursive,
            "exclude_subdirs": set(self.exclude_subdirs),
        }


def _coerce_layout(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception as exc:  # pragma: no cover - message path is tested via caller
            raise LayoutNormalizationError("nas_layout is not valid JSON") from exc
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise LayoutNormalizationError("nas_layout must be a JSON object")
    return raw


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(v) for v in value if v not in (None, "")]


def _clean_excludes(value: Any) -> frozenset[str]:
    excludes = []
    for item in _as_string_list(value):
        cleaned = item.strip().strip("/")
        if cleaned:
            excludes.append(cleaned)
    return frozenset(excludes)


def normalize_case_layout(
    slug: str,
    nas_layout: Any,
    *,
    default_root: str | Path = DEFAULT_LEGAL_NAS_ROOT,
    require_layout: bool = False,
) -> NormalizedCaseLayout:
    """Return the canonical runtime interpretation of legal.cases.nas_layout.

    When ``require_layout`` is false, empty layouts fall back to the legacy
    canonical case directory under ``default_root``. Vault ingest passes
    ``require_layout=True`` because non-canonical ingest must be explicitly
    scoped to curated source paths.
    """
    raw = _coerce_layout(nas_layout)
    if raw is None:
        if require_layout:
            raise LayoutNormalizationError("nas_layout is empty after normalize")
        return NormalizedCaseLayout(
            root=Path(default_root) / slug,
            subdirs=dict(DEFAULT_CASE_SUBDIR_MAP),
            recursive=False,
            exclude_subdirs=frozenset(),
            custom_layout=False,
        )

    if raw.get("primary_root") or raw.get("include_subdirs"):
        root = Path(str(raw.get("primary_root") or raw.get("root") or "")).expanduser()
        include_subdirs = _as_string_list(raw.get("include_subdirs") or [])
        subdirs = {value: value for value in include_subdirs}
        recursive_raw = raw.get("recursive")
        recursive = True if recursive_raw is None else bool(recursive_raw)
    else:
        root = Path(str(raw.get("root") or "")).expanduser()
        raw_subdirs = raw.get("subdirs") or {}
        if not isinstance(raw_subdirs, dict):
            raw_subdirs = {}
        subdirs = {
            str(key): str(value)
            for key, value in raw_subdirs.items()
            if value not in (None, "")
        }
        recursive = bool(raw.get("recursive"))

    return NormalizedCaseLayout(
        root=root,
        subdirs=subdirs,
        recursive=recursive,
        exclude_subdirs=_clean_excludes(raw.get("exclude_subdirs") or []),
        custom_layout=True,
    )
