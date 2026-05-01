"""Tests for ``backend.services.case_briefing_augmentation``.

Covers acceptance gate 3 of the section-9 intel resolver brief:

  > Existing Track A v3 Case I §9 augmentation file resolves identically to
  > its pre-resolver text (because no tokens exist yet — null-op pass-through).
  > Validates the integration didn't break the existing path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]
_PROJECT_ROOT = _BACKEND_ROOT.parent
for p in (str(_BACKEND_ROOT), str(_PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.services.case_briefing_augmentation import (  # noqa: E402
    AugmentationNotFoundError,
    load_section_9_augmentation,
    locate_augmentation_file,
)
from fortress.legal.intel_resolver import ResolutionError  # noqa: E402

FIXTURE_INTEL = _HERE.parent / "fixtures" / "intel-mini"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_no_tokens_is_null_op(tmp_path: Path) -> None:
    services_root = tmp_path / "services"
    aug = services_root / "section_prompts" / "test-case" / "section_09.md"
    text = "# §9\n\nPlain prose with no intel tokens — must pass through unchanged.\n"
    _write(aug, text)

    aug_path = locate_augmentation_file("test-case", services_root=services_root)
    out = aug_path.read_text(encoding="utf-8")
    assert out == text


def test_explicit_path_resolution(tmp_path: Path) -> None:
    aug = tmp_path / "alt_location.md"
    aug.write_text(
        "Resolved: {{ judge:test-judge#strategic_implications }}\n",
        encoding="utf-8",
    )
    out = load_section_9_augmentation(
        case_slug="ignored-when-explicit",
        intel_root=FIXTURE_INTEL,
        explicit_path=aug,
    )
    assert "Strategic implications" in out


def test_missing_augmentation_raises(tmp_path: Path) -> None:
    services_root = tmp_path / "services"
    services_root.mkdir()
    with pytest.raises(AugmentationNotFoundError):
        locate_augmentation_file("nonexistent-case", services_root=services_root)


def test_load_with_tokens_resolves(tmp_path: Path) -> None:
    aug = tmp_path / "section_09.md"
    aug.write_text(
        "Critical context:\n\n"
        "{{ judge:test-judge@operator_relevance.critical_context }}\n\n"
        "Conflict screening:\n"
        "- {{ firm:test-firm#conflict_screening_notes }}\n",
        encoding="utf-8",
    )
    out = load_section_9_augmentation(
        case_slug="any",
        intel_root=FIXTURE_INTEL,
        explicit_path=aug,
    )
    assert "SAME JUDGE for fixture matters" in out
    assert "screen against ACME" in out


def test_halts_on_missing_intel_token(tmp_path: Path) -> None:
    aug = tmp_path / "section_09.md"
    aug.write_text("{{ judge:never-existed }}\n", encoding="utf-8")
    with pytest.raises(ResolutionError):
        load_section_9_augmentation(
            case_slug="any",
            intel_root=FIXTURE_INTEL,
            explicit_path=aug,
        )
