# Case Briefing Compose — Operator Runbook

**Module:** `backend.services.case_briefing_compose` (v0.1)
**CLI:** `python -m backend.scripts.case_briefing_cli {inspect|compose|assemble}`
**First operator-runnable date:** 2026-04-29
**Stacks on:** PR #285 (LiteLLM legal cutover), PR #289 (Council consumer cutover), PR #280 (BrainClient)

---

## What it is

The Phase B drafting orchestrator turns a curated evidence set + sovereign BRAIN inference into a 10-section attorney briefing package. Track A produced v2 of the Case II brief by hand on 2026-04-29; this tool reproduces that quality on demand without operator hand-curation of every section.

```
STAGE 0 (curate) → STAGE 1 (grounding) → STAGE 2 (synthesize) → STAGE 3 (operator review) → STAGE 4 (assemble)
```

**Mechanical sections** (1, 3, 6, 10) — deterministic, no LLM, always pass grounding-citation enforcement.
**Synthesis sections** (2, 4, 5, 7, 8) — call BrainClient with packet-grounded prompts, streaming-default, grounding-citation enforced (≥3 per section).
**Operator-written section** (9) — placeholder; operator hand-edits.

---

## Prerequisites

Before running:

1. Spark-5 BRAIN reachable: `curl -sS http://spark-5:8100/v1/models | jq -r '.data[].id'` → returns `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8`.
2. LiteLLM gateway alive: `sudo systemctl status litellm-gateway` → active (running).
3. Postgres `legal.cases` row for the target case_slug (or its alias).
4. `legal.vault_documents` rows for the case (mostly status `complete`).
5. Qdrant `legal_ediscovery` and `legal_privileged_communications` collections green (per `qdrant-collections.md`).

---

## Commands

### `inspect` — read-only audit of the grounding packet

```bash
cd ~/Fortress-Prime/fortress-guest-platform
source venv/bin/activate
source .env

python -m backend.scripts.case_briefing_cli inspect \
  --case-slug 7il-v-knight-ndga-ii \
  --top-k 15 --privileged-top-k 10 \
  --output /tmp/inspect-7il-ii.json
```

Returns: vault document count, curated cluster summary, work-product chunk count, privileged chunk count, related matters, case metadata keys. **No LLM calls. No writes anywhere.**

Use this to sanity-check that retrieval surfaces what you expect before paying the BRAIN-time cost of `compose`.

### `compose --mechanical-only` — fast, no BRAIN calls

```bash
python -m backend.scripts.case_briefing_cli compose \
  --case-slug 7il-v-knight-ndga-ii \
  --mechanical-only \
  --dry-run
```

Produces sections 01, 03, 06, 09 (placeholder), 10 only. Skips synthesis sections entirely. Output lands in `/tmp/phase-b-7il-v-knight-ndga-ii/Attorney_Briefing_Package_<...>_v<N>_<YYYYMMDD>.md`.

Useful as a **smoke test** of Stages 0, 1, 4 against a real case before committing to a synthesis run.

### `compose` — full pipeline, real BRAIN calls

```bash
python -m backend.scripts.case_briefing_cli compose \
  --case-slug 7il-v-knight-ndga-ii \
  --dry-run
```

Runs all 10 sections. Synthesis sections (02, 04, 05, 07, 08) each take **5-10 min wall-clock** at the 49B Nemotron's ~3.7 tok/s throughput, so plan for **30-60 min total**. The probe latency is roughly:

* Section 02 (timeline) — ~5 min (shorter output)
* Section 04 (claims) — ~10 min (long synthesis)
* Section 05 (defenses) — ~10 min
* Section 07 (email intelligence) — ~5-8 min
* Section 08 (financial exposure) — ~5-10 min

`--dry-run` redirects output to `/tmp/phase-b-<slug>/...` instead of the canonical NAS path, so you can review before publishing. Drop `--dry-run` to publish to `/mnt/fortress_nas/Corporate_Legal/Business_Legal/<slug>/filings/outgoing/` (auto-versioned vN+1).

### `assemble` — re-publish from edited section JSONs

If you edited the generated sections by hand and want to re-assemble:

```bash
python -m backend.scripts.case_briefing_cli assemble \
  --case-slug 7il-v-knight-ndga-ii \
  --sections-json /tmp/phase-b-7il-v-knight-ndga-ii/sections.json \
  --version 4
```

The sections-json shape mirrors the `compose` step's intermediate state — see the function `_run_assemble` in the CLI source for the expected schema.

---

## What's enforced

* **Grounding citation enforcement.** Every synthesis section must cite ≥3 distinct bracketed-filename sources from the grounding packet. Sections that don't get tagged `FAIL_GROUNDING: only N grounded citations; minimum required is 3` in the output package.
* **Section 7 privilege filter.** Defense-counsel correspondence (Underwood / Podesta / Sanker / Argo and their domains) is dropped from the prompt before BRAIN sees it. Pinned by `test_stage_2_section_07_excludes_defense_counsel`.
* **FYEO warning.** Any section's `contains_privileged: true` (or the packet-level flag) appends the FYEO warning at the end of the package.
* **Streaming default.** All BRAIN calls go through `BrainClient` with `stream=True` per Phase A5 §7.2.

---

## Known limitations (v0.1 — what's deferred)

* **Stage 3 interactive review loop is deferred.** v0.1 ships `compose` as non-interactive (sections write through to assembly without per-section prompts). Operator can edit by hand post-compose then re-run `assemble`. Live review-loop CLI (per brief §5.5) is a follow-up enhancement.
* **Email-archive query integration is shallow.** `email_archive_hits` field on the GroundingPacket is currently empty pending operationalization of the Track A overnight queries (CSV exports under `docs/case-briefing/email-archive-query-*.csv`). Synthesis sections fall back on the work-product Qdrant chunks; section 7 will report "thin substrate" until email-archive queries are wired.
* **Stage 0 LLM-classify of ambiguous mime types is deferred.** v0.1 uses pure-mechanical mime-type + filename keyword clustering. Brief §5.2 calls for SWARM-tier classification of ambiguous chunks; not present in v0.1.
* **Multi-case batching is out of scope.** One `--case-slug` per invocation.
* **Web UI is out of scope.** CLI only.

---

## First-run checklist (operator-paced)

```bash
# 0. Pre-flight
curl -sS http://spark-5:8100/v1/models | jq -r '.data[].id'
sudo systemctl status litellm-gateway --no-pager | head -3

# 1. Inspect the grounding packet
python -m backend.scripts.case_briefing_cli inspect \
  --case-slug 7il-v-knight-ndga-ii \
  --output /tmp/inspect-7il-ii.json
cat /tmp/inspect-7il-ii.json | jq '.work_product_chunks, .privileged_chunks, .vault_documents_count'

# 2. Mechanical-only smoke test
python -m backend.scripts.case_briefing_cli compose \
  --case-slug 7il-v-knight-ndga-ii \
  --mechanical-only --dry-run
# review /tmp/phase-b-7il-v-knight-ndga-ii/...md

# 3. Full compose (synthesis included) — plan 30-60 min
nohup python -m backend.scripts.case_briefing_cli compose \
  --case-slug 7il-v-knight-ndga-ii \
  --dry-run > /tmp/phase-b-compose.log 2>&1 &
tail -f /tmp/phase-b-compose.log

# 4. Hand-review + edit
# Edit /tmp/phase-b-7il-v-knight-ndga-ii/...md as needed.
# Section 09 stays a placeholder for operator's strategic deliberation.

# 5. Publish to NAS canonical path (after operator approval)
python -m backend.scripts.case_briefing_cli compose \
  --case-slug 7il-v-knight-ndga-ii
# (no --dry-run — writes to /mnt/fortress_nas/.../filings/outgoing/ at vN+1)
```

---

## Cross-references

* PR #281 — Track A Case II briefing v2 (the hand-curated baseline this tool reproduces)
* PR #285 — ADR-003 Phase 1 LiteLLM legal cutover (the routing-layer enabler)
* PR #289 — Council consumer cutover (sibling consumer-layer cutover)
* PR #280 — BrainClient (the streaming-default abstraction this orchestrator builds on)
* Brief: `docs/operational/briefs/phase-b-drafting-orchestrator-2026-04-29.md`
* MASTER-PLAN §6.3 P2 — "Phase B drafting orchestrator" entry should be marked v0.1 SHIPPED after this PR merges.
