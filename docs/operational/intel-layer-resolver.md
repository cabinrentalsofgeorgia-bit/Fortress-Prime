# Intel Layer Resolver

**Module:** `fortress.legal.intel_resolver`
**CLI:** `python -m fortress.legal.intel_resolver_cli`
**Loader (case-briefing):** `backend.services.case_briefing_augmentation.load_section_9_augmentation`
**Brief:** `section-9-intel-resolver-brief-2026-05-01.md` (this PR)

---

## What this resolves

The intel layer at `/mnt/fortress_nas/intel/` is the canonical store for
non-public knowledge about judges, firms, attorneys, and parties relevant to
operator's matters. Each entity is a markdown file with YAML frontmatter and
H2-section body prose.

Without a resolver, §9 (and any other section that wants to draw on intel)
either hardcodes that prose inline (drift) or duplicates it (rot). The
resolver lets prompt-augmentation files reference intel entities by short
tokens; substitution happens at orchestration time.

## Token grammar

```
{{ entity_type:slug }}
{{ entity_type:slug#section_anchor }}
{{ entity_type:slug#anchor_a,anchor_b }}
{{ entity_type:slug@frontmatter.dotted.path }}
```

`entity_type` is one of `judge | firm | attorney | party`. `slug` matches
the intel filename (lowercase + hyphen by convention; uppercase tolerated for
PLACEHOLDER markers like `goldberg-PLACEHOLDER-firm`).

Separators:

- `#` — body section(s). Slug = lowercase-of-H2 with non-alphanumeric runs
  collapsed to `_`. Multi-section tokens join sections in the listed order
  with a blank line.
- `@` — frontmatter dotted path; resolves to the field value (string, int,
  bool — or YAML-dumped for nested mappings/lists).

Bare tokens (no separator) inject the schema's `default_resolution_sections`.

## Schema additions

Each `_schemas/<entity_type>.schema.yaml` declares two resolver-facing keys:

```yaml
default_resolution_sections:
  - operator_relevance
  - strategic_implications        # judge example

# Optional — friendly anchors → actual slugified H2 of the body.
section_aliases:
  operator_relevance: operator_relevant_context
```

The judge body H2 is `## Operator-relevant context` (slug:
`operator_relevant_context`). The alias keeps `#operator_relevance` working
in §9 augmentation tokens for symmetry with firm/attorney bodies (which use
`## Operator-relevance`).

### Required NAS additions (operator handoff)

The resolver fails loudly if a schema has no `default_resolution_sections`.
The PR cannot land production-functional without these one-line additions
to the live schemas. The blocks below are paste-ready; they sit at the end
of each schema file.

**`/mnt/fortress_nas/intel/_schemas/judge.schema.yaml`:**

```yaml
default_resolution_sections:
  - operator_relevance
  - strategic_implications

section_aliases:
  operator_relevance: operator_relevant_context
```

**`/mnt/fortress_nas/intel/_schemas/firm.schema.yaml`:**

```yaml
default_resolution_sections:
  - operator_relevance
  - conflict_screening_notes
```

**`/mnt/fortress_nas/intel/_schemas/attorney.schema.yaml`:**

```yaml
default_resolution_sections:
  - operator_relevance
```

The schema parser only consumes `required_fields`,
`default_resolution_sections`, and `section_aliases` — the prose-y
`field_types` blocks elsewhere in the schema files are tolerated.

## Hard stops

The resolver halts and surfaces (per brief §2) when:

1. **Missing slug.** No file matches `<entity_type>/**/<slug>.md`.
2. **Slug collision.** Two files claim the same slug; entity identity is
   broken.
3. **Schema validation failure.** A `required_fields` entry is missing from
   the file's frontmatter. PLACEHOLDER *values* are tolerated (intel was just
   seeded); only field *presence* is enforced.
4. **Unknown body anchor.** `#section_anchor` doesn't match any H2 in the
   resolved file.
5. **Empty default sections.** Schema declares no
   `default_resolution_sections` and the token has no explicit `#anchor`.

## Integration: §9 augmentation flow

Currently the §9 path returns `operator_written_placeholder()`. To switch §9
over to live augmentation:

```python
from backend.services.case_briefing_augmentation import (
    load_section_9_augmentation,
)

# in case_briefing_compose.stage_3_synthesize, replace the
# SECTION_MODE_OPERATOR_WRITTEN branch's `content=...` for §9 with:
content = load_section_9_augmentation(
    case_slug=packet.case_slug_canonical,
    intel_root=Path("/mnt/fortress_nas/intel"),  # or runner CLI flag
)
```

The loader searches:

1. `services/section_prompts/<case_slug>/section_09.md`
2. `services/section_prompts/case_ii_section_09_augmentation.md`

Or accepts `explicit_path=` to bypass the search.

## CLI

```bash
# Default sections
python -m fortress.legal.intel_resolver_cli \
    --token "judge:richard-w-story" \
    --intel-root /mnt/fortress_nas/intel

# Single named section (no schema defaults required)
python -m fortress.legal.intel_resolver_cli \
    --token "judge:richard-w-story#operator_relevant_context" \
    --intel-root /mnt/fortress_nas/intel

# Frontmatter dotted lookup
python -m fortress.legal.intel_resolver_cli \
    --token "judge:richard-w-story@operator_relevance.critical_context" \
    --intel-root /mnt/fortress_nas/intel

# Whole augmentation file in one shot
python -m fortress.legal.intel_resolver_cli \
    --file /home/admin/case-ii-section-09-prompt-augmentation-2026-05-01.md \
    --intel-root /mnt/fortress_nas/intel
```

Exit code 0 on success, 1 on `ResolutionError`. Error message is written to
stderr; resolved content goes to stdout.

`--on-missing` controls behaviour (only applies to `--file` mode):

| value         | effect                                                      |
|---------------|-------------------------------------------------------------|
| `halt`        | raise on first missing slug (default)                       |
| `placeholder` | inject `<!-- intel-resolver: missing X:Y -->` and continue  |
| `omit`        | drop the token silently and continue                        |

## Troubleshooting

**`No default_resolution_sections declared in <type>.schema.yaml` →** the
operator NAS schema-update step is missing. Apply the YAML blocks above.

**`YAML parse error for 'required_fields' in ...schema.yaml` →** the schema
has malformed YAML *inside* a key the resolver consumes (the prose-y
`field_types` block is tolerated; `required_fields` /
`default_resolution_sections` / `section_aliases` are not). Fix the YAML.

**`Section anchor '<x>' not found` →** check the H2 slug rule: lowercase,
runs of non-alphanumeric → `_`, leading/trailing `_` stripped. For verbose
H2s (e.g., judge's `## Operator-relevant context`) prefer adding a
`section_aliases` entry over renaming the body.

**`Slug collision`** → two files claim the same slug under the same
entity-type tree. Rename one or scope it under a deeper directory; entity
identity must be 1:1.

## What this resolver deliberately doesn't do

Per brief §13:

- No Postgres mirror of intel files (Q3)
- No pgvector embedding (Q3)
- No automated CourtListener / RECAP / Juriscraper ingestion (Q3)
- No enforcement of authoring annotations beyond stripping
  `<!-- authoring: ... -->` lines from injected content
- No write path against the intel layer (read-only)
- No web inspection UI (Q3+)

## Related

- `section-9-intel-resolver-brief-2026-05-01.md` — implementation brief
- `case-ii-section-09-prompt-augmentation-2026-05-01.md` — first consumer
- `fortress-prime-intel-layer-architecture-2026-05-01.md` — intel layer
  architecture (NAS canonical, Postgres mirror Q3, schema design)
