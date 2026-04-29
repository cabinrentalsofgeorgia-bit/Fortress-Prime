# Caselaw Corpus Audit — 2026-04-29

**Operator:** Gary Knight
**Executor:** Claude Code on spark-2
**Brief:** `/home/admin/caselaw-corpus-audit-brief.md`
**Driver:** Case II is federal NDGA (Eleventh Circuit). White-shoe-grade Case II prep requires queryable federal caselaw at minimum. ADR-003 Phase 1 cutover (PR #285) means legal queries now route to BRAIN; retrieval inputs need to exist for retrieval-augmented inference to work.

**Outcome:** **B — `legal_caselaw_federal` empty, ingestion path ready.** Companion ingestion brief drafted at `docs/operational/briefs/legal-caselaw-federal-ingestion-2026-04-29.md`.

---

## Findings

### `legal_caselaw` (Georgia state — insurance-only)

| Field | Value |
|---|---|
| Points count | **2,711** |
| Vector size | 768 |
| Distance | Cosine |
| Status | green |
| Indexed vectors | 0 (HNSW index not built — points are stored but on-disk indexing pending) |
| Sample retrieval | **PASS** (3 cases, scores 0.62 / 0.59 / 0.58 against query "easement appurtenant Georgia") |
| NAS source | `/mnt/fortress_nas/legal-corpus/courtlistener/opinions-full.jsonl` (52 MB) + `opinions-expanded.jsonl` (8 MB) |
| Manifest | `/mnt/fortress_nas/legal-corpus/courtlistener/manifest.json` — courts: `ga`, `gactapp`, `gasupct`; query: `insurance OR insurer OR bad faith OR subrogation OR duty to defend`; date range 2010-2026; 1,880 filtered rows |

**Sample retrieval evidence (query: "easement appurtenant Georgia"):**

| Score | Case | Court |
|---|---|---|
| 0.621 | Thomas Murphy v. Ticor Title Insurance Company | Court of Appeals of Georgia |
| 0.589 | Willis Insurance Services of Georgia, Inc. v. Brent Hartman | Court of Appeals of Georgia |
| 0.583 | Erick K. Morton v. Nationwide Insurance Company | Court of Appeals of Georgia |

**Corpus-quality notes:**
- The corpus is **insurance-filtered**, not general Georgia caselaw. The driver query in the manifest is `insurance OR insurer OR bad faith OR subrogation OR duty to defend`. A query about easements still returns the closest insurance-coverage cases — the corpus has no real-property or easement caselaw to surface. **Not adequate for general Case II prep on its own.** Adequate for the insurance-coverage angle of any Case II claim that touches title insurance / closing escrow disputes.
- `payload.citation` is an empty array on every chunk inspected. Either CourtListener returned no citation strings for this filtered subset, or the ingestion script dropped the field. Retrieval works; citation-based filtering / cite-checking against this corpus does not.
- `indexed_vectors_count: 0` — Qdrant has the points but the HNSW index is not built. Retrieval still works (linear-scan on 2,711 points) but is slower than indexed retrieval would be. This is a cosmetic / performance issue, not a correctness issue.

### `legal_caselaw_federal` (Federal CA11)

| Field | Value |
|---|---|
| Collection exists | **NO — collection does not exist on the localhost Qdrant cluster** |
| Points count | n/a |
| Vector size | n/a |
| Sample retrieval | **FAIL** — HTTP 404 `Not found: Collection 'legal_caselaw_federal' doesn't exist!` |
| NAS source | absent — `/mnt/fortress_nas/legal-corpus/courtlistener/opinions-ca11.jsonl` does not exist |

**`qdrant-collections.md` claim is inaccurate.** Line 21 states: `'legal_caselaw_federal' | localhost | Federal CA11 caselaw RAG | ... | 'ingest_courtlistener.py' (fed mode) | 0 (PR #184; awaits ingest)`. PR #184 either never created the collection on this Qdrant instance, or it was dropped at some point. The script today is `ingest_courtlistener_11th_cir.py` (sibling, not a "fed mode" of the GA script), and the collection it targets has to be created on first run via the script's `ensure_collection()` step.

### Ingestion scripts

| Script | Path | Target collection | Status |
|---|---|---|---|
| GA-state | `fortress-guest-platform/backend/scripts/ingest_courtlistener.py` | `legal_caselaw` | LIVE — produced the 2,711-point corpus |
| Federal CA11 | `fortress-guest-platform/backend/scripts/ingest_courtlistener_11th_cir.py` | `legal_caselaw_federal` | **READY — never run** |

**11th-Cir script readiness checklist:**

- ✓ Pagination CourtListener API client (`fetch_ca11_to_jsonl`) — line ≈83 onward
- ✓ Targets `legal_caselaw_federal` (`COLLECTION_NAME = "legal_caselaw_federal"` line 75)
- ✓ Auto-creates collection (`sink.ensure_collection(VECTOR_DIM)` at line 367)
- ✓ Default NAS source: `/mnt/fortress_nas/legal-corpus/courtlistener/opinions-ca11.jsonl`
- ✓ Default state DB: `/mnt/fortress_nas/legal-corpus/courtlistener/.ingest_state_ca11.db`
- ✓ Idempotent (deterministic UUID5 point IDs + sqlite resume log)
- ✓ Full CLI surface: `--reset --limit --batch-size --dry-run --source --log-every --since`
- ✓ Reuses GA script's chunker (1500/150 word-based) + RealEmbedder (nomic-embed-text via legal_ediscovery._embed_single) + QdrantSink
- ✓ Reads `COURTLISTENER_API_TOKEN` from env; raises if unset

### CourtListener API access

| Item | State |
|---|---|
| Env var | `COURTLISTENER_API_TOKEN` |
| Where set | `fortress-guest-platform/.env` |
| Length | 40 chars (token-shaped) |
| Validator hook | `courtlistener_api_token: str = Field(default="")` in `backend/core/config.py:814` |
| API base | `https://www.courtlistener.com/api/rest/v4` |

Token is **configured**. The `ingest_courtlistener_11th_cir.py` `_get_token()` helper at line ≈123 reads `os.environ.get("COURTLISTENER_API_TOKEN", "").strip()` and raises with the message `"COURTLISTENER_API_TOKEN is unset — required for ca11 fetch"` if empty. Token is non-empty, so this is unblocked.

---

## Gap analysis — Outcome B

The federal-caselaw substrate that Case II needs (Eleventh Circuit precedent, plus federal SCOTUS where relevant) is entirely missing from the sovereign retrieval cluster. The path to fix it is **fully ready**:

- Script is committed, idempotent, with a working CLI surface and matching pipeline to the production GA-state ingest.
- API token is configured and non-empty.
- NAS path is writable; the script will create both the cached JSONL and the sqlite resume DB on first run.
- Qdrant cluster is reachable on localhost:6333 and the script's `ensure_collection()` will create `legal_caselaw_federal` with the right vector size (768) and Cosine distance on first run.

This is **not a blocker that needs unblocking work** (Outcome C) — it's a "press-the-button-once-authorized" path (Outcome B). Companion ingestion brief drafted at `docs/operational/briefs/legal-caselaw-federal-ingestion-2026-04-29.md`.

---

## Secondary findings worth surfacing

These are not Phase B blockers but were observed during the audit:

1. **GA caselaw is insurance-filtered, not general.** If Case II prep needs Georgia easement / real-property / quiet-title precedent, the existing `legal_caselaw` corpus does not have it. A second GA ingest with a broader query (or no query — full ga/gactapp/gasupct dump within a date range) may be warranted. Out of scope for this audit; flagging for a follow-up brief.

2. **Citation field is empty on `legal_caselaw` payloads.** Either CourtListener's filtered API returned empty `citations`, or the GA ingest script drops them. Cite-based filters / cite-checks against this corpus will return nothing. Worth a one-line investigation in the GA script (out of scope here).

3. **`qdrant-collections.md` line 21 needs correction.** It currently claims `legal_caselaw_federal` exists with 0 points (PR #184 origin). The collection does not exist. Consider amending to `0 (collection not yet created; ingest_courtlistener_11th_cir.py creates on first run)` once the federal ingest lands.

4. **`legal_caselaw` HNSW index is not built (`indexed_vectors_count: 0`).** Retrieval still works at this corpus size (linear-scan on 2,711 points is fast). Worth flipping the indexing threshold lower or running an explicit `update_collection` to materialize the index — performance hygiene, not correctness.

---

## Cross-references

- Brief: `/home/admin/caselaw-corpus-audit-brief.md` (operator-uploaded)
- Companion ingestion brief: `docs/operational/briefs/legal-caselaw-federal-ingestion-2026-04-29.md` (drafted in this PR)
- ADR-003 Phase 1 cutover: PR #285 (legal traffic now routes to spark-5 BRAIN; retrieval inputs need to exist on localhost:6333 Qdrant for RAG to work)
- ADR-004: dedicated inference cluster expanded to 3/4/5/6
- `docs/architecture/shared/qdrant-collections.md` — needs the line-21 correction noted above
- `legal-corpus/courtlistener/manifest.json` — corpus-filter provenance for `legal_caselaw`
