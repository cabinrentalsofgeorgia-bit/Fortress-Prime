"""§9 (and other) prompt-augmentation loader for case-briefing orchestration.

The augmentation files live alongside the operator's case briefs and contain
intel-layer tokens (``{{ judge:richard-w-story#operator_relevance }}`` etc.)
that the resolver substitutes from ``/mnt/fortress_nas/intel/``.

The `case_briefing_synthesizers.operator_written_placeholder` path leaves §9
as a static placeholder. To switch §9 over to live-augmentation, route its
``SectionResult.content`` through ``load_section_9_augmentation`` instead.
The brief calls for one-line integration; this module is that one line plus
file lookup.

See: section-9-intel-resolver-brief-2026-05-01.md §8.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fortress.legal.intel_resolver import (
    IntelResolver,
    OnMissing,
    ResolutionError,
)


logger = logging.getLogger("case_briefing_augmentation")


DEFAULT_INTEL_ROOT = Path("/mnt/fortress_nas/intel")

# Search order for augmentation file given a case slug. First match wins.
_AUGMENTATION_SEARCH_TEMPLATES: tuple[str, ...] = (
    "section_prompts/{case_slug}/section_09.md",
    "section_prompts/case_ii_section_09_augmentation.md",
)


class AugmentationNotFoundError(FileNotFoundError):
    """Raised when no augmentation file can be located for a case slug."""


def locate_augmentation_file(
    case_slug: str,
    *,
    services_root: Path | None = None,
    explicit_path: Path | None = None,
) -> Path:
    """Find the §9 augmentation file for ``case_slug``.

    ``explicit_path`` (if given) wins; otherwise the conventional locations
    under ``backend/services/`` are searched.
    """
    if explicit_path is not None:
        if not explicit_path.exists():
            raise AugmentationNotFoundError(
                f"Augmentation file not found at explicit path: {explicit_path}"
            )
        return explicit_path

    if services_root is None:
        services_root = Path(__file__).resolve().parent

    tried: list[Path] = []
    for template in _AUGMENTATION_SEARCH_TEMPLATES:
        candidate = services_root / template.format(case_slug=case_slug)
        tried.append(candidate)
        if candidate.exists():
            return candidate
    raise AugmentationNotFoundError(
        f"No §9 augmentation file found for case_slug={case_slug!r}. "
        f"Searched: {[str(p) for p in tried]}"
    )


def load_section_9_augmentation(
    case_slug: str,
    *,
    intel_root: Path = DEFAULT_INTEL_ROOT,
    explicit_path: Path | None = None,
    on_missing: OnMissing = "halt",
) -> str:
    """Load the §9 augmentation file and substitute every intel-layer token.

    Halts orchestration on the first ``ResolutionError`` unless
    ``on_missing != "halt"``. The resolver itself enforces schema validity
    and slug-collision guards (intel_resolver brief §2 hard stops).
    """
    aug_path = locate_augmentation_file(case_slug, explicit_path=explicit_path)
    raw_text = aug_path.read_text(encoding="utf-8")
    resolver = IntelResolver(intel_root=intel_root)
    try:
        resolved = resolver.resolve_tokens(raw_text, on_missing=on_missing)
    except ResolutionError:
        logger.exception(
            "intel-resolver halt while loading §9 augmentation for %s (file: %s)",
            case_slug,
            aug_path,
        )
        raise
    return resolved


__all__ = [
    "AugmentationNotFoundError",
    "DEFAULT_INTEL_ROOT",
    "load_section_9_augmentation",
    "locate_augmentation_file",
]
