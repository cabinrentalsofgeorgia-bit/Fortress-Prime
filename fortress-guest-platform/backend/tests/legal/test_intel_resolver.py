"""Unit tests for ``fortress.legal.intel_resolver``.

Fixtures live at ``tests/legal/fixtures/intel-mini/`` — minimal intel tree
mirroring the production NAS structure with one judge, one firm (plus a
PLACEHOLDER variant), and one attorney.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

# Make the `fortress.legal` package importable when pytest is invoked from the
# repo root or from `fortress-guest-platform/backend/`.
_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from fortress.legal.intel_resolver import (  # noqa: E402
    IntelResolver,
    ResolutionError,
)

FIXTURE_ROOT = _HERE.parent / "fixtures" / "intel-mini"


@pytest.fixture
def resolver() -> IntelResolver:
    return IntelResolver(intel_root=FIXTURE_ROOT)


@pytest.fixture
def isolated_intel(tmp_path: Path) -> Path:
    """Copy of the fixture tree mutable per test (collision/schema tests)."""
    target = tmp_path / "intel"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def test_basic_token_resolution(resolver: IntelResolver) -> None:
    text = "{{ judge:test-judge }}"
    out = resolver.resolve_tokens(text)
    assert "Operator-relevant context" in out
    assert "Strategic implications" in out
    # Standing-order section is not in the default set
    assert "Standing order summary" not in out


def test_section_anchor_token(resolver: IntelResolver) -> None:
    text = "{{ judge:test-judge#strategic_implications }}"
    out = resolver.resolve_tokens(text)
    assert "Strategic implications" in out
    assert "Operator-relevant context" not in out


def test_multi_section_token(resolver: IntelResolver) -> None:
    text = "{{ judge:test-judge#strategic_implications,operator_relevance }}"
    out = resolver.resolve_tokens(text)
    # Order respects the token's anchor list
    strategic_idx = out.index("Strategic implications")
    operator_idx = out.index("Operator-relevant context")
    assert strategic_idx < operator_idx


def test_section_alias_resolves_judge_operator_relevance(
    resolver: IntelResolver,
) -> None:
    """`#operator_relevance` aliases to the judge body's actual H2 slug."""
    out = resolver.resolve_tokens("{{ judge:test-judge#operator_relevance }}")
    assert "Operator-relevant context" in out
    assert "Strategic implications" not in out


def test_frontmatter_field_token(resolver: IntelResolver) -> None:
    text = "{{ judge:test-judge@operator_relevance.critical_context }}"
    out = resolver.resolve_tokens(text)
    assert "SAME JUDGE for fixture matters I and II" in out
    # Body markdown should NOT appear when only frontmatter is requested
    assert "Standing order summary" not in out


def test_firm_default_sections(resolver: IntelResolver) -> None:
    out = resolver.resolve_tokens("{{ firm:test-firm }}")
    assert "Operator-relevance" in out
    assert "Conflict screening notes" in out
    # `Sources` is auto-generated and not in the default set
    assert "Auto-generated section" not in out


def test_attorney_default_section(resolver: IntelResolver) -> None:
    out = resolver.resolve_tokens("{{ attorney:test-attorney }}")
    assert "Operator-relevance" in out
    assert "Practice profile" not in out


def test_missing_slug_halts(resolver: IntelResolver) -> None:
    with pytest.raises(ResolutionError, match="No intel file"):
        resolver.resolve_tokens("{{ judge:does-not-exist }}")


def test_missing_slug_placeholder_mode(resolver: IntelResolver) -> None:
    out = resolver.resolve_tokens(
        "before {{ judge:does-not-exist }} after",
        on_missing="placeholder",
    )
    assert "intel-resolver: missing judge:does-not-exist" in out
    assert "before" in out and "after" in out


def test_missing_slug_omit_mode(resolver: IntelResolver) -> None:
    out = resolver.resolve_tokens(
        "before {{ judge:does-not-exist }} after",
        on_missing="omit",
    )
    assert out.replace(" ", "") == "beforeafter"


def test_slug_collision_halts(isolated_intel: Path) -> None:
    # Drop a duplicate slug into a sibling directory
    duplicate = isolated_intel / "judges" / "duplicate-court" / "test-judge.md"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text(
        (isolated_intel / "judges" / "test" / "test-judge.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    resolver = IntelResolver(intel_root=isolated_intel)
    with pytest.raises(ResolutionError, match="Slug collision"):
        resolver.resolve_token("judge", "test-judge")


def test_schema_validation_halts_on_missing_required(
    isolated_intel: Path,
) -> None:
    target = isolated_intel / "judges" / "test" / "test-judge.md"
    text = target.read_text(encoding="utf-8")
    # Strip the required `display_name` field
    mutated = "\n".join(
        line for line in text.splitlines() if not line.startswith("display_name:")
    )
    target.write_text(mutated, encoding="utf-8")
    resolver = IntelResolver(intel_root=isolated_intel)
    with pytest.raises(ResolutionError, match="required field 'display_name' missing"):
        resolver.resolve_token("judge", "test-judge")


def test_placeholder_content_tolerated(resolver: IntelResolver) -> None:
    """A frontmatter packed with literal PLACEHOLDER values still resolves."""
    out = resolver.resolve_tokens("{{ firm:placeholder-firm }}")
    assert "PLACEHOLDER prose" in out
    assert "PLACEHOLDER conflict screening notes" in out


def test_authoring_comments_stripped(resolver: IntelResolver) -> None:
    out = resolver.resolve_tokens("{{ judge:test-judge#operator_relevance }}")
    assert "<!-- authoring:" not in out
    assert "authoring: manual" not in out


def test_nested_directory_resolution(resolver: IntelResolver) -> None:
    """`judges/test/test-judge.md` is found via `judge:test-judge`."""
    out = resolver.resolve_token("judge", "test-judge")
    assert "Operator-relevant context" in out


def test_unknown_section_anchor_halts(resolver: IntelResolver) -> None:
    with pytest.raises(ResolutionError, match="not found"):
        resolver.resolve_tokens("{{ judge:test-judge#never_existed }}")


def test_no_tokens_passthrough(resolver: IntelResolver) -> None:
    text = "Plain prose with no tokens — should pass through unchanged."
    assert resolver.resolve_tokens(text) == text


def test_resolve_tokens_is_idempotent_when_no_tokens(
    resolver: IntelResolver,
) -> None:
    once = resolver.resolve_tokens("{{ firm:test-firm }}")
    # Re-running over already-resolved text (which has no tokens) must be a no-op
    assert resolver.resolve_tokens(once) == once


def test_dotted_lookup_failure_message(resolver: IntelResolver) -> None:
    with pytest.raises(ResolutionError, match="not resolvable"):
        resolver.resolve_frontmatter_field(
            "judge", "test-judge", "operator_relevance.does_not_exist"
        )
