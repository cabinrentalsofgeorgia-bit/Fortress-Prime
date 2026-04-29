# NGC NIM / NeMo Catalog Refresh — 2026-04-29 (BLOCKED)

**Probe date attempted:** 2026-04-29
**Enumerator:** `tools/ngc_catalog_enumerator.py` (last touched PR #130, 2026-04-22)
**Status:** **BLOCKED — NGC search API returns HTTP 400 Bad Request.** No new catalog data captured. No ARM64 probe pass executed.

---

## TL;DR

- Brief authorized refresh per `feat/nim-stack-audit-2026-04-29` (PR #291) recommendation.
- NGC catalog enumerator hits `https://api.ngc.nvidia.com/v2/search/catalog/resources/CONTAINER?q=nim+<namespace>&fields=...&offset=0&limit=100` — returns **HTTP 400 Bad Request**, deterministic across 16 attempts (4 retries × 4 namespaces tested).
- Authentication is **not** the problem (NGC_API_KEY loaded; length 70 chars; rotated 2026-04-23). The error is HTTP 400 from the API itself, suggesting the search endpoint surface changed since the 2026-04-22 successful run (PR #130 committed → NGC catalog last produced).
- ARM64 probe pass against newly-discovered images is **also blocked**: no new images discovered to probe.
- Per brief instruction (`If tooling missing or NGC API auth fails: surface, do not improvise.`), no improvised endpoint probes were attempted. The 2026-04-22 snapshot remains the authoritative reference.

**Operator decision queued:** patch the enumerator's request format (likely a 5–15 line change once NGC's current docs are consulted) OR contact NVIDIA via the NGC support channel.

---

## 1. What ran

```bash
cd /home/admin/Fortress-Prime
python3 tools/ngc_catalog_enumerator.py
```

Default invocation (no `--namespace` filter, no `--dry-run`, no `--no-manifest`). Iterates all five `DEFAULT_NAMESPACES`: `nim/nvidia`, `nim/meta`, `nim/mistralai`, `nim/deepseek-ai`, `nemo`.

NGC_API_KEY loaded successfully via `sudo -n cat /etc/fortress/nim.env` (length 70). Enumeration began 2026-04-29 17:09:16 EDT.

## 2. What failed

Every namespace returned **0 raw catalog entries** because every retry to the search endpoint returned HTTP 400. Sample (first namespace, full retry sequence):

```
17:09:16  Enumerating namespace: nim/nvidia
17:09:17  WARNING  NGC request error (attempt 1/4): 400 Client Error: Bad Request for url:
            https://api.ngc.nvidia.com/v2/search/catalog/resources/CONTAINER
              ?q=nim+nvidia
              &fields=name,latestTag,description,architecture,orgName,teamName,displayName,publisher
              &offset=0&limit=100
17:09:19  WARNING  NGC request error (attempt 2/4): 400 Client Error: Bad Request ...
17:09:23  WARNING  NGC request error (attempt 3/4): 400 Client Error: Bad Request ...
17:09:31  WARNING  NGC request error (attempt 4/4): 400 Client Error: Bad Request ...
17:09:31  Found 0 raw catalog entries for nim/nvidia
```

Identical pattern for `nim/meta`, `nim/mistralai`, `nim/deepseek-ai` (run aborted after 4 namespaces × 4 retries = 16 confirmed identical 400s; 5th namespace `nemo` not tested but expected to fail the same way).

Run terminated by SIGTERM after the failure pattern was confirmed deterministic.

## 3. Failure analysis

**Not auth.** `_load_nim_env()` succeeded; `NGC_API_KEY` length 70 (matching the rotated 2026-04-23 key in `/etc/fortress/nim.env`); the request reached NVIDIA's API and got back a 400 — not a 401 or 403.

**Not transient.** 4 retries with exponential backoff (delay starting at base, doubled each time) all returned the same 400. Pattern repeated identically across 4 namespaces.

**Most likely:** the NGC search-catalog API surface changed between 2026-04-22 and 2026-04-29. The hardcoded endpoint at `tools/ngc_catalog_enumerator.py:79` (`NGC_CATALOG_API`) and the field list / query format embedded around line 168–195 must be reconciled with NVIDIA's current public docs. NGC has rolled API surface changes silently in the past — the 2026-04-22 docs of the search endpoint are 7 days stale.

**Diagnostic probes against the bare endpoint were intentionally NOT attempted** — the brief specifies `do not improvise` if NGC API fails, and direct curl attempts with the API key fall outside the enumerator's intended flow.

## 4. Impact on PR #291 follow-ups

The 2026-04-29 NIM stack audit (PR #291) recommended five priority NIMs whose ARM64 status needed verification this refresh would have provided:

| Tier | NIM family | ARM64 status (2026-04-22) | This refresh would have updated |
|---|---|---|---|
| TIER 1 | `nemoretriever-parse*` | not in 2026-04-22 snapshot | **STILL UNKNOWN** |
| TIER 1 | `*rerank*` | 0 ARM64 of 3 in catalog | **STILL UNKNOWN** |
| TIER 1 | `nemoretriever-page-elements*` | not in 2026-04-22 snapshot | **STILL UNKNOWN** |
| TIER 1 | `nemoretriever-table-structure*` | not in 2026-04-22 snapshot | **STILL UNKNOWN** |
| TIER 1 | `nemoretriever-graphic-elements*` | not in 2026-04-22 snapshot | **STILL UNKNOWN** |
| TIER 2 | `nv-embedqa*` | v5 NVAIE-gated 2026-04-22 (premium tier) | **STILL UNKNOWN** |
| TIER 2 | `parakeet*`, `canary*`, `riva/*` | speech family 0 ARM64 of 2 in catalog | **STILL UNKNOWN** |
| TIER 2 | `llama-guard*` | guard-3-8b ARM64=Yes accessible | confirmed unchanged from 2026-04-22 (no fresh probe data) |
| TIER 3 | `cosmos-reason*` | not in 2026-04-22 snapshot | **STILL UNKNOWN** |

PR #291's P0 ("`llama-nemotron-embed-1b-v2` deployment, cached + ARM64_OK") and P1 ("`llama-guard-3-8b` pull + arm64 probe") are unaffected by this blocker — both are already in the existing 2026-04-22 catalog with positive ARM64 verdicts. The TIER 1 reranker / NeMo Retriever / page-element gap remains unresolved.

## 5. Recommended next steps (operator decides)

**Option A — patch the enumerator (cheapest path).** Read NVIDIA's current NGC search/catalog API docs, reconcile `NGC_CATALOG_API`, the `q=...` query format, and the `fields=...` list at `tools/ngc_catalog_enumerator.py:79–195`. Likely a 5–15 line diff. Test against a single namespace before re-running the full pass. Open a separate `chore/ngc-enumerator-api-surface-fix-2026-04-29` branch.

**Option B — escalate via NVIDIA.** Open a support ticket against NGC referencing the 400 error on the catalog-search endpoint. Slower; useful only if the API documentation itself is unclear.

**Option C — defer.** Continue using the 2026-04-22 snapshot for any pull authorization. Acceptable risk if the operator is willing to act on 7-day-stale data; not acceptable for the TIER 1 NeMo Retriever items that aren't in the 2026-04-22 snapshot at all.

## 6. What this PR contains

- This document only. **No code changes.** No pulls. No deploys. No catalog table writes.
- The enumerator's JSONL snapshot at `/mnt/fortress_nas/fortress_data/nim_catalog/snapshot_2026-04-29.jsonl` was **not produced** (run aborted before any namespace returned data). The directory was created but is empty.
- The `nim_arm64_probe_results` Postgres table received **no new rows** from this attempt.

## Cross-references

- Upstream brief: PR #291 (`docs/operational/nim-stack-audit-2026-04-29.md`) — Top P0/P1 recommendations and the original §3.5/§3.6 NGC discovery deferment
- Existing snapshot (still authoritative): `docs/NGC_NIM_CATALOG_2026-04-22.md`
- ARM64 probe table source: `nim_arm64_probe_results` (`fortress_db`) — last entry 2026-04-29 from the audit-time spot-check, NOT from this refresh
- Enumerator: `tools/ngc_catalog_enumerator.py`
- Per-image probe wrapper: `tools/nim_arm64_probe.py`
- Pull pipeline: `scripts/nim_pull_to_nas.py`

---

End of report.
