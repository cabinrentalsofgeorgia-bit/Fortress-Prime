"""CLI entry point for ``IntelResolver``.

Examples:

    # Resolve default sections for a judge
    python -m fortress.legal.intel_resolver_cli \
        --token "judge:richard-w-story" \
        --intel-root /mnt/fortress_nas/intel

    # Resolve a single named section
    python -m fortress.legal.intel_resolver_cli \
        --token "judge:richard-w-story" \
        --section operator_relevance \
        --intel-root /mnt/fortress_nas/intel

    # Resolve a frontmatter field via dotted path
    python -m fortress.legal.intel_resolver_cli \
        --token "judge:richard-w-story@operator_relevance.critical_context" \
        --intel-root /mnt/fortress_nas/intel

    # Resolve every token in a markdown file
    python -m fortress.legal.intel_resolver_cli \
        --file /home/admin/case-ii-section-09-prompt-augmentation-2026-05-01.md \
        --intel-root /mnt/fortress_nas/intel

Exit code 0 on success, 1 on ``ResolutionError``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fortress.legal.intel_resolver import IntelResolver, ResolutionError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intel-resolver",
        description="Resolve intel-layer tokens to markdown content.",
    )
    parser.add_argument(
        "--intel-root",
        type=Path,
        default=Path("/mnt/fortress_nas/intel"),
        help="Path to intel layer root (default: /mnt/fortress_nas/intel)",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--token",
        help='Single token, e.g. "judge:richard-w-story" or '
        '"judge:richard-w-story#operator_relevance,strategic_implications" or '
        '"judge:richard-w-story@operator_relevance.critical_context"',
    )
    src.add_argument(
        "--file",
        type=Path,
        help="Path to a markdown file; resolves every token inside it.",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        help="(With --token, no anchor) override section anchor(s); repeatable",
    )
    parser.add_argument(
        "--on-missing",
        choices=("halt", "placeholder", "omit"),
        default="halt",
        help="Behaviour when a token cannot resolve (default: halt)",
    )
    return parser


def _resolve_single_token(
    resolver: IntelResolver, token: str, section_overrides: list[str]
) -> str:
    raw = token.strip()
    if raw.startswith("{{"):
        wrapped = raw
    else:
        wrapped = "{{ " + raw + " }}"
    # If user passed --section but token has no anchor, splice them in.
    if section_overrides and "#" not in raw and "@" not in raw:
        wrapped = "{{ " + raw + "#" + ",".join(section_overrides) + " }}"
    return resolver.resolve_tokens(wrapped, on_missing="halt")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    resolver = IntelResolver(intel_root=args.intel_root)
    try:
        if args.token is not None:
            output = _resolve_single_token(resolver, args.token, args.section)
        else:
            file_path: Path = args.file
            output = resolver.resolve_tokens(
                file_path.read_text(encoding="utf-8"),
                on_missing=args.on_missing,
            )
    except ResolutionError as exc:
        print(f"intel-resolver: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
