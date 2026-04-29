# Federal CA11 Caselaw Ingestion — Operational Brief

**Date:** 2026-04-29
**Status:** PLANNED — execution gated on operator authorization
**Driver:** Audit `docs/operational/caselaw-corpus-audit-2026-04-29.md` confirmed Outcome B — federal caselaw missing from the sovereign retrieval cluster, ingestion path fully ready.

> This brief describes the execution; it does not run the ingestion. A separate operator-authorized session runs the actual fetch + embed + upsert.

---

## Source

- **API:** CourtListener REST v4 — `https://www.courtlistener.com/api/rest/v4`
- **Court ID:** `ca11` — U.S. Court of Appeals for the Eleventh Circuit
- **Auth:** `COURTLISTENER_API_TOKEN` env var (configured in `fortress-guest-platform/.env`, 40-char token, validated)
- **Why CA11:** Case II is filed in NDGA (Northern District of Georgia, Gainesville Division). NDGA appellate review is the Eleventh Circuit. Federal precedent for the case lives at the CA11 level.

## Scope

- **v1 (this brief):** full Eleventh Circuit caselaw — all CA11 opinions returned by the CourtListener API; no date-range filter, no keyword filter. The script supports `--since` if the operator wants a date-floor cutover, but the default is "everything CA11 ever published."
- **Out of scope for v1:** SCOTUS opinions, sister-circuit opinions (CA1-CA10, CA-DC, CA-Fed), district-court opinions. If Case II prep surfaces a sister-circuit / SCOTUS gap, that's a follow-up brief.

## Pipeline

```
CourtListener API v4 (CA11)
     ↓ fetch_ca11_to_jsonl()  — paginated, idempotent
NAS: /mnt/fortress_nas/legal-corpus/courtlistener/opinions-ca11.jsonl
     ↓ word-based chunker (1500/150 overlap)
     ↓ nomic-embed-text via Ollama at 192.168.0.100:11434 (legal_ediscovery._embed_single)
Qdrant: localhost:6333 collection `legal_caselaw_federal` (768-dim, Cosine)
     ↓ idempotent upsert (deterministic UUID5 point IDs)
Done — RAG-queryable
```

## Idempotency

- **Fetch step:** the JSONL grows; re-fetch skips opinion IDs already present.
- **Ingest step:** sqlite resume log at `/mnt/fortress_nas/legal-corpus/courtlistener/.ingest_state_ca11.db` records `(opinion_id, chunks_upserted, run_id, completed_at)`. Re-runs with the same `--source` / state-DB pair pick up where the prior run stopped.
- **UUID5 point IDs:** chunk identity is deterministic from `(opinion_id, chunk_index)`, so re-upserting the same chunk does not duplicate it.

## Pre-execution checklist

```bash
# 1. Confirm Qdrant reachable
curl -sS http://localhost:6333/collections | jq -r '.result.collections[].name' | head -10

# 2. Confirm embed service reachable
curl -sS http://192.168.0.100:11434/api/embeddings \
  -d '{"model":"nomic-embed-text","prompt":"smoke"}' \
  | jq -r '.embedding | length'   # expect 768

# 3. Confirm token loaded into the script's env
( cd /home/admin/Fortress-Prime && \
  source fortress-guest-platform/.env && \
  python -c 'import os; t=os.environ.get("COURTLISTENER_API_TOKEN",""); print("token len:", len(t))' )
# expect: token len: 40

# 4. Disk-space sanity on NAS
df -h /mnt/fortress_nas | head -3

# 5. Dry-run with limit (proves the pipeline end-to-end without network spend)
cd /home/admin/Fortress-Prime
source fortress-guest-platform/venv/bin/activate
python -m backend.scripts.ingest_courtlistener_11th_cir --dry-run --limit 10
```

If any of (1)-(5) fails: STOP, surface, do not proceed.

## Execution sequence

```bash
cd /home/admin/Fortress-Prime
source fortress-guest-platform/.env
source fortress-guest-platform/venv/bin/activate

# Live run — full CA11 ingest, no limit.
nohup python -m backend.scripts.ingest_courtlistener_11th_cir \
  --batch-size 64 \
  --log-every 50 \
  > /tmp/ca11-ingest-$(date +%Y%m%dT%H%M%SZ).log 2>&1 &

# Tail progress
tail -f /tmp/ca11-ingest-*.log
```

The script logs every 50 chunks. Expect a long tail: pagination-fetch is ~5 opinions/page at typical CourtListener throughput, embedding is ~50-100 chunks/sec on local nomic-embed-text, Qdrant upsert is the cheap step.

### Estimated runtime

- **Fetch:** CourtListener has on the order of ~30,000 CA11 opinions historically. At 20 per page and the courtlistener default rate-limit, fetch is the bottleneck — estimated **6-12 hours wall-clock** for the full pull. Re-runs are idempotent so a resumable approach is fine if it gets interrupted.
- **Embed + upsert:** ~30k opinions × ~10 chunks each = ~300k chunks. At ~75 chunks/sec on the existing GA-corpus benchmark, that's **~70 minutes** of embed time once the JSONL is on NAS.
- **Total wall-clock:** plan for **8-13 hours** end-to-end, mostly fetch-bound. Operator can run it overnight. Phase B work can use an empty `legal_caselaw_federal` collection during the run (queries return zero hits but don't crash) and the corpus arrives by morning.

## STOP gates during execution

- **CourtListener rate-limit** — if the API returns HTTP 429 / 503 with a `Retry-After`, the script's HTTP layer should back off; if it does not, kill and resume later.
- **Embed service down** — if `192.168.0.100:11434/api/embeddings` returns 5xx for more than 30 s, kill, investigate Ollama on spark-2, resume.
- **Qdrant collection wrong vector size** — `ensure_collection()` only creates if absent; if a prior partial run created the collection at the wrong dimension, the upsert will fail. Resolution: `--reset` to drop and recreate (acceptable since the collection isn't serving any production traffic yet).
- **Disk-full on NAS** — `opinions-ca11.jsonl` will grow; estimate ~150-300 MB compressed JSONL for the full CA11 historical pull. If `/mnt/fortress_nas` is anywhere near full, free space first.

## Post-execution verification

```bash
# Collection exists + has points
curl -sS http://localhost:6333/collections/legal_caselaw_federal | \
  jq '{points: .result.points_count, status: .result.status, dim: .result.config.params.vectors.size}'

# Sample retrieval (proves end-to-end queryability matches the GA corpus)
EMBED=$(curl -sS http://192.168.0.100:11434/api/embeddings \
  -d '{"model":"nomic-embed-text","prompt":"diversity jurisdiction LLC citizenship"}' | jq -c '.embedding')
curl -sS -X POST http://localhost:6333/collections/legal_caselaw_federal/points/search \
  -H "Content-Type: application/json" \
  -d "{\"vector\": $EMBED, \"limit\": 3, \"with_payload\": true}" \
  | jq '.result[] | {score, case_name: .payload.case_name, court: .payload.court}'
```

PASS criteria:
- `points_count` > 0 (target: order of low-100k chunks)
- `status: green`
- Sample retrieval returns 3 results with reasonable case names and `court: "ca11"` (or similar canonical court tag)
- `qdrant-collections.md` line 21 amended to reflect the live point count

## Closing artifact

After the ingest run, produce `docs/operational/legal-caselaw-federal-ingest-complete-<DATE>.md`:

- Final point count
- Wall-clock runtime (fetch / embed / upsert breakdown)
- Sample retrieval output (3 results with scores)
- Any STOP-gate hits and how they were resolved
- `qdrant-collections.md` correction PR linked

## Hard constraints

- **DO NOT** run this ingest without operator authorization
- **DO NOT** modify the ingestion script in this brief — if a defect surfaces during dry-run, surface it, do not patch in place
- **DO NOT** re-pull or modify the GA-state corpus (`legal_caselaw`) during this run
- **DO NOT** upsert into any collection other than `legal_caselaw_federal`
- **DO NOT** disable the dry-run gate — every operator-execution must start with `--dry-run --limit 10` to prove the pipeline end-to-end before the live run

## Cross-references

- Audit: `docs/operational/caselaw-corpus-audit-2026-04-29.md`
- Script: `fortress-guest-platform/backend/scripts/ingest_courtlistener_11th_cir.py`
- GA-state sibling (already-running pattern): `fortress-guest-platform/backend/scripts/ingest_courtlistener.py`
- ADR-003 Phase 1 (LiteLLM cutover): PR #285 — legal traffic terminates on spark-5 BRAIN; this corpus is the retrieval input for federal-tier legal-RAG queries
- `docs/architecture/shared/qdrant-collections.md` — line 21 correction to land alongside the live point count
