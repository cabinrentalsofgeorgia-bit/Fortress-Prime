"""Intel layer resolver for §9 (and other) prompt augmentation.

Reads tokens of the form ``{{ entity_type:slug }}``,
``{{ entity_type:slug#section_anchor }}``, and
``{{ entity_type:slug@frontmatter.dotted.path }}`` from text and substitutes
content drawn from the intel-layer markdown files at
``/mnt/fortress_nas/intel/<entity_type>/<...>/<slug>.md``.

The resolver is read-only against the intel layer. It validates each resolved
file against the schema declared at ``_schemas/<entity_type>.schema.yaml``
(``required_fields`` only — PLACEHOLDER values are tolerated). Schema files
also declare:

  * ``default_resolution_sections``: list of section anchors injected when a
    token has no ``#`` anchor.
  * ``section_aliases`` (optional): mapping of friendly alias →
    actual-slugified-H2-anchor. Lets schemas expose stable token names even
    when underlying H2 wording is verbose.

See ``docs/operational/intel-layer-resolver.md`` for the integration guide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml


class ResolutionError(Exception):
    """Raised when a token cannot be safely resolved.

    Halts orchestration — the brief's hard-stop policy is that silently
    swallowing schema or slug errors poisons the §9 brief.
    """


OnMissing = Literal["halt", "placeholder", "omit"]


_TOKEN_RE = re.compile(
    r"\{\{\s*"
    r"(?P<entity_type>judge|firm|attorney|party)"
    # Slugs are *meant* to be lowercase + hyphen (per intel layer schema), but
    # the layer was just seeded and PLACEHOLDER markers like
    # `goldberg-PLACEHOLDER-firm` exist on disk. Acceptance gate 2 in the
    # implementation brief explicitly requires those to resolve, so the slug
    # class allows uppercase too. Filename matching is case-sensitive at the
    # filesystem layer, which is the actual identity check.
    r":(?P<slug>[A-Za-z0-9][A-Za-z0-9_\-]*)"
    r"(?:(?P<separator>[#@])(?P<anchor>[A-Za-z0-9_,.\-]+))?"
    r"\s*\}\}"
)


_AUTHORING_COMMENT_RE = re.compile(r"<!--\s*authoring:[^>]*-->\s*\n?")


_ENTITY_TYPE_PATHS: dict[str, str] = {
    "judge": "judges",
    "firm": "firms",
    "attorney": "attorneys",
    "party": "parties",
}


@dataclass(frozen=True)
class _ParsedFile:
    frontmatter: dict[str, Any]
    body: str


def _slugify_header(header: str) -> str:
    """Slugify an H2 header per the documented rule.

    Lowercase; runs of non-``[a-z0-9]`` collapsed to ``_``; leading/trailing
    underscores stripped. ``"## Conflict screening notes"`` →
    ``"conflict_screening_notes"``.
    """
    lowered = header.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug


class IntelResolver:
    """Token-driven loader for intel-layer markdown."""

    TOKEN_RE = _TOKEN_RE
    ENTITY_TYPE_PATHS = _ENTITY_TYPE_PATHS

    def __init__(self, intel_root: Path) -> None:
        self.intel_root = Path(intel_root)
        self._schema_cache: dict[str, dict[str, Any]] = {}
        self._file_cache: dict[Path, _ParsedFile] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def resolve_tokens(self, text: str, on_missing: OnMissing = "halt") -> str:
        """Substitute every token in ``text`` with resolved content.

        ``on_missing`` controls behaviour when a token references a missing
        slug or empty section: ``"halt"`` raises, ``"placeholder"`` injects a
        marker comment, ``"omit"`` deletes the token silently.
        """

        def _sub(match: re.Match[str]) -> str:
            entity_type = match.group("entity_type")
            slug = match.group("slug")
            separator = match.group("separator")
            anchor = match.group("anchor")
            try:
                if separator == "@":
                    return self.resolve_frontmatter_field(
                        entity_type, slug, anchor or ""
                    )
                section_anchors = (
                    [a.strip() for a in anchor.split(",") if a.strip()]
                    if anchor
                    else None
                )
                return self.resolve_token(
                    entity_type, slug, section_anchors=section_anchors
                )
            except ResolutionError:
                if on_missing == "halt":
                    raise
                if on_missing == "placeholder":
                    return f"<!-- intel-resolver: missing {entity_type}:{slug} -->"
                return ""

        return self.TOKEN_RE.sub(_sub, text)

    def resolve_token(
        self,
        entity_type: str,
        slug: str,
        section_anchors: list[str] | None = None,
    ) -> str:
        """Resolve a body-section token to extracted markdown content."""
        file_path = self._find_intel_file(entity_type, slug)
        parsed = self._load_intel_file(file_path)
        self._validate_against_schema(entity_type, parsed.frontmatter, file_path)

        if section_anchors is None:
            section_anchors = self._default_sections_for(entity_type)
            if not section_anchors:
                raise ResolutionError(
                    f"No default_resolution_sections declared in "
                    f"{entity_type}.schema.yaml — cannot resolve "
                    f"{entity_type}:{slug} without an explicit #section anchor"
                )

        resolved_anchors = [
            self._resolve_alias(entity_type, anchor) for anchor in section_anchors
        ]
        return self._extract_sections(parsed.body, resolved_anchors, entity_type, slug)

    def resolve_frontmatter_field(
        self, entity_type: str, slug: str, field_path: str
    ) -> str:
        """Resolve a ``@dotted.path`` token to a frontmatter value (stringified)."""
        if not field_path:
            raise ResolutionError(
                f"Empty frontmatter field path for {entity_type}:{slug}"
            )
        file_path = self._find_intel_file(entity_type, slug)
        parsed = self._load_intel_file(file_path)
        self._validate_against_schema(entity_type, parsed.frontmatter, file_path)
        value = self._dotted_lookup(parsed.frontmatter, field_path)
        if value is None:
            raise ResolutionError(
                f"Frontmatter field '{field_path}' is null/missing for "
                f"{entity_type}:{slug} (file: {file_path})"
            )
        return self._render_frontmatter_value(value)

    # ── Internals ───────────────────────────────────────────────────────────

    def _find_intel_file(self, entity_type: str, slug: str) -> Path:
        if entity_type not in self.ENTITY_TYPE_PATHS:
            raise ResolutionError(f"Unknown entity_type '{entity_type}'")
        type_dir = self.intel_root / self.ENTITY_TYPE_PATHS[entity_type]
        candidates = sorted(type_dir.glob(f"**/{slug}.md"))
        if not candidates:
            raise ResolutionError(
                f"No intel file found for {entity_type}:{slug} under {type_dir}/"
            )
        if len(candidates) > 1:
            joined = ", ".join(str(p) for p in candidates)
            raise ResolutionError(
                f"Slug collision for {entity_type}:{slug} — found "
                f"{len(candidates)} matching files: {joined}"
            )
        return candidates[0]

    def _load_intel_file(self, path: Path) -> _ParsedFile:
        if path in self._file_cache:
            return self._file_cache[path]
        text = path.read_text(encoding="utf-8")
        parsed = self._parse_intel_file(text, path)
        self._file_cache[path] = parsed
        return parsed

    @staticmethod
    def _parse_intel_file(text: str, path: Path) -> _ParsedFile:
        if not text.startswith("---"):
            raise ResolutionError(
                f"Intel file {path} missing YAML frontmatter delimiter"
            )
        # Split on the *next* '---' line after the opening one.
        rest = text[3:]
        end_match = re.search(r"^---\s*$", rest, re.MULTILINE)
        if end_match is None:
            raise ResolutionError(
                f"Intel file {path} missing closing '---' for frontmatter"
            )
        fm_text = rest[: end_match.start()]
        body = rest[end_match.end() :].lstrip("\n")
        try:
            frontmatter = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError as exc:
            raise ResolutionError(
                f"YAML parse error in {path}: {exc}"
            ) from exc
        if not isinstance(frontmatter, dict):
            raise ResolutionError(
                f"Frontmatter in {path} must be a mapping, got {type(frontmatter).__name__}"
            )
        return _ParsedFile(frontmatter=frontmatter, body=body)

    # Schema keys the resolver actually consumes. Production schema files mix
    # machine-readable contract (these keys) with prose-y `field_types` blocks
    # that aren't valid YAML — so we extract only what we need.
    _SCHEMA_KEYS: tuple[str, ...] = (
        "required_fields",
        "default_resolution_sections",
        "section_aliases",
    )

    def _load_schema(self, entity_type: str) -> dict[str, Any]:
        if entity_type in self._schema_cache:
            return self._schema_cache[entity_type]
        schema_path = self.intel_root / "_schemas" / f"{entity_type}.schema.yaml"
        if not schema_path.exists():
            raise ResolutionError(
                f"Schema not found at {schema_path} for entity_type {entity_type}"
            )
        text = schema_path.read_text(encoding="utf-8")
        data = self._extract_schema_keys(text, schema_path)
        self._schema_cache[entity_type] = data
        return data

    @classmethod
    def _extract_schema_keys(cls, text: str, schema_path: Path) -> dict[str, Any]:
        """Extract just the top-level keys the resolver consumes.

        Production schemas mix machine-readable contract (``required_fields``,
        etc.) with documentation-style entries (``field_types`` containing
        prose values). A full ``yaml.safe_load`` chokes on the latter, so we
        slice each wanted top-level key into its own snippet and parse that.
        """
        result: dict[str, Any] = {}
        lines = text.splitlines()
        for key in cls._SCHEMA_KEYS:
            snippet = cls._slice_top_level_block(lines, key)
            if snippet is None:
                continue
            try:
                parsed = yaml.safe_load(snippet)
            except yaml.YAMLError as exc:
                raise ResolutionError(
                    f"YAML parse error for '{key}' in {schema_path}: {exc}"
                ) from exc
            if isinstance(parsed, dict) and key in parsed:
                result[key] = parsed[key]
        return result

    @staticmethod
    def _slice_top_level_block(lines: list[str], key: str) -> str | None:
        """Return the YAML snippet for top-level ``key:`` (key + indented body).

        Returns ``None`` if the key isn't present.
        """
        start: int | None = None
        for i, line in enumerate(lines):
            if line.startswith(f"{key}:") and (
                len(line) == len(key) + 1 or line[len(key) + 1] in (" ", "\t", "\n")
            ):
                start = i
                break
        if start is None:
            return None
        end = len(lines)
        for j in range(start + 1, len(lines)):
            line = lines[j]
            if not line.strip():
                continue
            if line.startswith("#"):
                continue
            # Top-level key reached when a non-blank line starts at col 0 and
            # isn't a continuation/comment of the current block.
            if not line.startswith((" ", "\t", "-", "#")):
                end = j
                break
        return "\n".join(lines[start:end]) + "\n"

    def _validate_against_schema(
        self, entity_type: str, frontmatter: dict[str, Any], path: Path
    ) -> None:
        schema = self._load_schema(entity_type)
        required_raw = schema.get("required_fields", [])
        if not isinstance(required_raw, list):
            raise ResolutionError(
                f"required_fields in {entity_type}.schema.yaml must be a list"
            )
        for field in required_raw:
            if field not in frontmatter:
                raise ResolutionError(
                    f"Schema validation failed for {path}: required field "
                    f"'{field}' missing"
                )

    def _default_sections_for(self, entity_type: str) -> list[str]:
        schema = self._load_schema(entity_type)
        sections = schema.get("default_resolution_sections", []) or []
        if not isinstance(sections, list):
            raise ResolutionError(
                f"default_resolution_sections in {entity_type}.schema.yaml "
                f"must be a list"
            )
        return [str(s) for s in sections]

    def _resolve_alias(self, entity_type: str, anchor: str) -> str:
        schema = self._load_schema(entity_type)
        aliases = schema.get("section_aliases", {}) or {}
        if not isinstance(aliases, dict):
            raise ResolutionError(
                f"section_aliases in {entity_type}.schema.yaml must be a mapping"
            )
        return str(aliases.get(anchor, anchor))

    def _extract_sections(
        self, body: str, anchors: list[str], entity_type: str, slug: str
    ) -> str:
        sections = self._index_body_sections(body)
        out_chunks: list[str] = []
        for anchor in anchors:
            if anchor not in sections:
                available = ", ".join(sorted(sections.keys())) or "<none>"
                raise ResolutionError(
                    f"Section anchor '{anchor}' not found in {entity_type}:{slug} "
                    f"body (available: {available})"
                )
            out_chunks.append(sections[anchor].strip())
        merged = "\n\n".join(out_chunks)
        return _AUTHORING_COMMENT_RE.sub("", merged).strip()

    @staticmethod
    def _index_body_sections(body: str) -> dict[str, str]:
        """Return ``{anchor: body_text}`` keyed by slugified H2 header.

        The body chunk for each H2 includes the H2 line itself and continues
        to the next H2 (or end of file).
        """
        index: dict[str, str] = {}
        current_anchor: str | None = None
        current_buf: list[str] = []
        for line in body.splitlines(keepends=True):
            h2 = re.match(r"^##\s+(.+?)\s*$", line.rstrip("\n"))
            if h2:
                if current_anchor is not None:
                    index[current_anchor] = "".join(current_buf)
                current_anchor = _slugify_header(h2.group(1))
                current_buf = [line]
            else:
                if current_anchor is not None:
                    current_buf.append(line)
        if current_anchor is not None:
            index[current_anchor] = "".join(current_buf)
        return index

    @staticmethod
    def _dotted_lookup(data: dict[str, Any], field_path: str) -> Any:
        cursor: Any = data
        for part in field_path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                raise ResolutionError(
                    f"Frontmatter field path '{field_path}' not resolvable; "
                    f"stopped at '{part}'"
                )
            cursor = cursor[part]
        return cursor

    @staticmethod
    def _render_frontmatter_value(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, dict)):
            return yaml.safe_dump(value, default_flow_style=False, sort_keys=False).strip()
        return str(value)


__all__ = ["IntelResolver", "ResolutionError", "OnMissing"]


def iter_tokens(text: str) -> Iterable[re.Match[str]]:
    """Yield every token match in ``text`` (helper for tests / debugging)."""
    return _TOKEN_RE.finditer(text)
