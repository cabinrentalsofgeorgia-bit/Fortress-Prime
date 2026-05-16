# Qdrant `legal_ediscovery` Reindex Brief — 768-dim → 2048-dim

**Target:** Claude Code on spark-2
**Branch:** `feat/qdrant-legal-ediscovery-reindex-2026-05-01`
**Date:** 2026-05-01
**Operator:** Gary Knight
**Mode:** AUTONOMOUS background job (runs while Wave 4 §5 + Wave 5 Guardrails proceed in parallel on other hosts)
**Driver:** Wave 3 PARTIAL surfaced dim mismatch — `legal_ediscovery` is 768-dim (built against older embed); current production EMBED `llama-nemotron-embed-1b-v2` produces 2048-dim. Phase B Case II briefing (Wave 7) cannot ground against a dim-mismatched collection. **This is on the critical path for Sunday's Phase B kickoff.**

**Stacks on:**
- PR #343 merged (Wave 3 PARTIAL — EMBED/Vision verify + cluster conventions)
- EMBED healthy on spark-3:8102, dim=2048 confirmed
- Frontier soak active to 2026-05-14 (untouched by this work)
- Phase B v0.1 orchestrator references `legal_ediscovery` collection name

**Resolves:** the 768→2048 dim mismatch blocking Phase B Case II grounding.

---

## 1. Mission

Build a new Qdrant collection at 2048-dim, populate it via re-embedding the 738K points from the existing 768-dim `legal_ediscovery` collection's source text, validate against quality probes, and atomic-swap the alias `legal_ediscovery_active` to point at the new collection. Original 768-dim collection retained for 14-day rollback window.

**Critical:** The "source text" must be the original chunk text, not the existing 768-dim vectors. We're regenerating embeddings against the new EMBED model; the old vectors are unusable.

---

## 2. Hard stops

Halt + surface ONLY for:

1. **EMBED endpoint dies during reindex** — `curl http://192.168.0.105:8102/v1/health/ready` non-200 sustained >60s. Reindex is wholly dependent on EMBED throughput; if it dies, halt and protect.
2. **Frontier endpoint dies** — `curl http://10.10.10.3:8000/health` non-200 sustained >60s. Reindex shouldn't touch frontier, but if soak halts, this is operator's signal too.
3. **Disk full on NAS** — <10GB free in `/mnt/fortress_nas`. Halt before further writes.
4. **Source collection corruption** — if scroll API returns errors >3 successive batches, halt and verify source collection integrity.
5. **Embedding rate <5/sec sustained for 5 minutes** — something's wrong with the EMBED service or batch size. Investigate before continuing.
6. **Qdrant server OOM or crash** — local Qdrant on spark-2 dies. Halt, verify state, restart cleanly before resuming.
7. **Soak halt event fires** — Phase 9 collector emits halt.

Everything else proceeds. Defaults apply.

---

## 3. Scope

**In scope:**
- Create `legal_ediscovery_v2` collection at 2048-dim, Cosine distance
- Scroll source `legal_ediscovery` collection (768-dim) for chunk text + payload
- Batch re-embed via `legal-embed` LiteLLM alias (or direct to spark-3:8102)
- Upsert into `legal_ediscovery_v2` preserving original payload metadata + source_id
- Quality probes: 5 known-good queries against both collections, top-5 overlap percentage
- Atomic alias swap: `legal_ediscovery_active` → `legal_ediscovery_v2`
- Document migration evidence pack
- Update Phase B v0.1 retrieval config if it references `legal_ediscovery` directly (should be alias-based; verify)

**Out of scope:**
- Deleting old `legal_ediscovery` collection (retain 14 days for rollback)
- Schema changes to chunks (no chunk re-segmentation; same chunks, new embeddings)
- Modifying EMBED service config
- Touching the frontier
- Wave 4 / Wave 5 / Wave 7 work

---

## 4. Pre-flight (autonomous)

### 4.1 State

```bash
git fetch origin
git checkout origin/main
git checkout -b feat/qdrant-legal-ediscovery-reindex-2026-05-01
git status
```

### 4.2 Frontier health (must stay 200 throughout)

```bash
curl -fsS --max-time 10 http://10.10.10.3:8000/health
curl -fsS http://10.10.10.3:8000/v1/models | jq '.data[].id'
```

Expected: 200, `nemotron-3-super` listed. Halt if non-200.

### 4.3 EMBED health + dim confirmation

```bash
curl -fsS http://192.168.0.105:8102/v1/health/ready

# Confirm dim
DIM=$(curl -fsS http://192.168.0.105:8102/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "llama-nemotron-embed-1b-v2", "input": ["dim probe"]}' | \
  jq '.data[0].embedding | length')
echo "EMBED dim: $DIM"
# Expected: 2048
```

If dim != 2048, halt — model state has shifted since Wave 3 PARTIAL verification.

### 4.4 Qdrant local state

```bash
# Source collection state
curl -fsS http://localhost:6333/collections/legal_ediscovery | jq '.result | {
  status: .status,
  points_count: .points_count,
  vector_size: .config.params.vectors.size,
  distance: .config.params.vectors.distance
}'

# Confirm: status=green, points_count=~738000, vector_size=768, distance=Cosine
```

Halt if source collection unhealthy or doesn't match expected shape.

### 4.5 Disk + memory check

```bash
df -h /mnt/fortress_nas /var/lib/qdrant 2>/dev/null || df -h /mnt/fortress_nas /
free -h
# Need: >10GB free on Qdrant data path; >8GB free RAM for Qdrant working set
```

### 4.6 Snapshot source for safety

```bash
SNAP_NAME=$(curl -fsS -X POST "http://localhost:6333/collections/legal_ediscovery/snapshots" | \
  jq -r '.result.name')
echo "Source snapshot: $SNAP_NAME"
# Stored at /var/lib/qdrant/storage/legal_ediscovery/snapshots/ or wherever Qdrant is configured
```

---

## 5. Create target collection

### 5.1 Create `legal_ediscovery_v2` at 2048-dim

```bash
curl -fsS -X PUT "http://localhost:6333/collections/legal_ediscovery_v2" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {
      "size": 2048,
      "distance": "Cosine"
    },
    "optimizers_config": {
      "indexing_threshold": 20000,
      "default_segment_number": 4
    },
    "hnsw_config": {
      "m": 16,
      "ef_construct": 200
    }
  }'

# Verify
curl -fsS http://localhost:6333/collections/legal_ediscovery_v2 | jq '.result | {
  status: .status,
  vector_size: .config.params.vectors.size
}'
```

Expected: status=green, vector_size=2048.

### 5.2 Build payload index for fast filtering on `source_id`

```bash
curl -fsS -X PUT "http://localhost:6333/collections/legal_ediscovery_v2/index" \
  -H "Content-Type: application/json" \
  -d '{
    "field_name": "source_id",
    "field_schema": "keyword"
  }'
```

If other indexed payload fields exist on the source collection, replicate them on v2. Inspect via:

```bash
curl -fsS http://localhost:6333/collections/legal_ediscovery | \
  jq '.result.config.params'
```

---

## 6. The reindex script

### 6.1 Script location

Build at `/home/admin/Fortress-Prime/scripts/reindex_qdrant_collection.py`. **Commit this** — it's reusable for future dim migrations and worth productionizing.

### 6.2 Script logic

```python
#!/usr/bin/env python3
"""
Reindex Qdrant collection against new embedding model.

Usage:
  python3 reindex_qdrant_collection.py \
    --source legal_ediscovery \
    --target legal_ediscovery_v2 \
    --embed-endpoint http://192.168.0.105:8102/v1 \
    --embed-model llama-nemotron-embed-1b-v2 \
    --batch-size 64 \
    --resume-from /tmp/reindex-resume.json

Reads source chunks via scroll API, re-embeds via OpenAI-compatible
endpoint, upserts to target. Resumable via offset checkpoint file.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, Filter

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--qdrant-url", default="http://localhost:6333")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--embed-endpoint", required=True)
    p.add_argument("--embed-model", required=True)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--scroll-batch", type=int, default=256)
    p.add_argument("--resume-from", default="/tmp/reindex-resume.json")
    p.add_argument("--audit-log", default="/mnt/fortress_nas/audits/qdrant-reindex.log")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()

def embed_batch(endpoint, model, texts):
    """Call OpenAI-compatible embedding endpoint, return list of vectors."""
    response = requests.post(
        f"{endpoint}/embeddings",
        json={"model": model, "input": texts},
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return [d["embedding"] for d in data["data"]]

def main():
    args = parse_args()
    client = QdrantClient(url=args.qdrant_url)

    # Resume state
    resume_path = Path(args.resume_from)
    next_offset = None
    points_done = 0
    if resume_path.exists():
        state = json.loads(resume_path.read_text())
        next_offset = state.get("next_offset")
        points_done = state.get("points_done", 0)
        print(f"Resuming from offset {next_offset}, {points_done} points done")

    # Audit log
    Path(args.audit_log).parent.mkdir(parents=True, exist_ok=True)
    audit = open(args.audit_log, "a")
    audit.write(f"\n\n=== REINDEX START {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ===\n")
    audit.write(f"Source: {args.source}, Target: {args.target}\n")
    audit.write(f"Embed: {args.embed_model} @ {args.embed_endpoint}\n")
    audit.flush()

    # Scroll source
    start_time = time.time()
    while True:
        scroll_response = client.scroll(
            collection_name=args.source,
            limit=args.scroll_batch,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,  # We don't want old 768-dim vectors
        )
        points, next_offset = scroll_response

        if not points:
            print("All points processed.")
            break

        # Process in embed-batch chunks
        for i in range(0, len(points), args.batch_size):
            batch = points[i : i + args.batch_size]
            texts = []
            ids = []
            payloads = []

            for p in batch:
                # Chunk text MUST be in payload. Adjust key if convention differs.
                text = p.payload.get("text") or p.payload.get("chunk") or p.payload.get("content")
                if not text:
                    print(f"WARN: point {p.id} has no text in payload; skipping")
                    audit.write(f"SKIP point {p.id}: no text in payload\n")
                    continue
                texts.append(text)
                ids.append(p.id)
                payloads.append(p.payload)

            if not texts:
                continue

            try:
                vectors = embed_batch(args.embed_endpoint, args.embed_model, texts)
            except Exception as e:
                print(f"ERROR embedding batch starting at {ids[0]}: {e}")
                audit.write(f"ERROR batch starting {ids[0]}: {e}\n")
                # Save resume state and bail
                resume_path.write_text(json.dumps({
                    "next_offset": next_offset,
                    "points_done": points_done,
                }))
                sys.exit(1)

            if args.dry_run:
                print(f"DRY RUN: would upsert {len(vectors)} points to {args.target}")
            else:
                client.upsert(
                    collection_name=args.target,
                    points=[
                        PointStruct(id=ids[j], vector=vectors[j], payload=payloads[j])
                        for j in range(len(vectors))
                    ],
                )

            points_done += len(vectors)
            elapsed = time.time() - start_time
            rate = points_done / elapsed if elapsed > 0 else 0
            print(f"[{points_done:>7}] rate={rate:.1f}/s elapsed={elapsed:.0f}s")

        # Save resume state every scroll batch
        resume_path.write_text(json.dumps({
            "next_offset": next_offset,
            "points_done": points_done,
        }))
        audit.flush()

        if next_offset is None:
            break

    elapsed = time.time() - start_time
    audit.write(f"\n=== REINDEX COMPLETE ===\n")
    audit.write(f"Total points: {points_done}\n")
    audit.write(f"Wall: {elapsed:.0f}s\n")
    audit.write(f"Rate: {points_done/elapsed:.1f}/s\n")
    audit.close()

    # Clean up resume file on success
    if not args.dry_run and resume_path.exists():
        resume_path.unlink()

    print(f"Done. {points_done} points in {elapsed:.0f}s ({points_done/elapsed:.1f}/s)")

if __name__ == "__main__":
    main()
```

### 6.3 Confirm payload key convention before running

Inspect a sample point from source to confirm chunk text is at `.payload.text` (or `.chunk` or `.content`):

```bash
curl -fsS "http://localhost:6333/collections/legal_ediscovery/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{"limit": 1, "with_payload": true}' | jq '.result.points[0].payload | keys'
```

If the chunk text key is something else, update the script's payload reading line accordingly.

---

## 7. Dry run first

### 7.1 Tiny dry run on 100 points

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  source /home/admin/fortress-guardrails-venv/bin/activate || \
    python3 -m venv /home/admin/reindex-venv && source /home/admin/reindex-venv/bin/activate
  pip install qdrant-client requests

  # Hack: limit to first 100 by deleting target after, then run real
  python3 scripts/reindex_qdrant_collection.py \
    --source legal_ediscovery \
    --target legal_ediscovery_v2 \
    --embed-endpoint http://192.168.0.105:8102/v1 \
    --embed-model llama-nemotron-embed-1b-v2 \
    --batch-size 16 \
    --scroll-batch 100 \
    --dry-run
'
```

Confirm: dry run completes, identifies chunk text in payload correctly, no errors.

### 7.2 Real run on 100 points (smoke)

Drop `--dry-run`. After completion, verify target collection has ~100 points and they retrieve correctly:

```bash
curl -fsS http://localhost:6333/collections/legal_ediscovery_v2 | \
  jq '.result.points_count'

# Test one retrieval
QUERY_VEC=$(curl -fsS http://192.168.0.105:8102/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "llama-nemotron-embed-1b-v2", "input": ["easement on River Heights"]}' | \
  jq '.data[0].embedding')

curl -fsS -X POST "http://localhost:6333/collections/legal_ediscovery_v2/points/search" \
  -H "Content-Type: application/json" \
  -d "{\"vector\": $QUERY_VEC, \"limit\": 5, \"with_payload\": true}" | \
  jq '.result[] | {score, payload}'
```

Expected: top-5 results with score values, payload preserved.

### 7.3 Reset target after smoke

```bash
curl -fsS -X DELETE "http://localhost:6333/collections/legal_ediscovery_v2"
# Then recreate per §5.1
```

---

## 8. Full reindex run

### 8.1 Kick off in tmux for resumability

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  tmux new-session -d -s qdrant-reindex "
    source /home/admin/reindex-venv/bin/activate
    python3 scripts/reindex_qdrant_collection.py \
      --source legal_ediscovery \
      --target legal_ediscovery_v2 \
      --embed-endpoint http://192.168.0.105:8102/v1 \
      --embed-model llama-nemotron-embed-1b-v2 \
      --batch-size 64 \
      --scroll-batch 256 \
      2>&1 | tee /mnt/fortress_nas/audits/qdrant-reindex-$(date +%Y%m%dT%H%M%SZ).log
  "
'
```

### 8.2 Monitor progress

```bash
ssh admin@192.168.0.100 'tmux attach -t qdrant-reindex'
# Detach: Ctrl-B then D
```

Or tail log:

```bash
ssh admin@192.168.0.100 'tail -f /mnt/fortress_nas/audits/qdrant-reindex-*.log'
```

### 8.3 Expected wall time

At target rate 30-60 embeds/sec via `legal-embed` NIM:
- 738K points / 45/sec = **~4.5 hours** wall

If rate drops below 10/sec sustained, halt and investigate (HARD STOP §2.5).

### 8.4 Periodic frontier health spot-check

Every 30 min during reindex, from a separate session:

```bash
curl -fsS --max-time 10 http://10.10.10.3:8000/health
curl -fsS --max-time 10 http://192.168.0.105:8102/v1/health/ready
```

If either falls over, halt the reindex.

---

## 9. Validation against shadow

### 9.1 Point count check

```bash
ORIG=$(curl -fsS http://localhost:6333/collections/legal_ediscovery | jq '.result.points_count')
NEW=$(curl -fsS http://localhost:6333/collections/legal_ediscovery_v2 | jq '.result.points_count')
echo "Original: $ORIG, New: $NEW"

# Within 1% tolerance (some chunks may have empty text and skip)
DELTA=$(echo "scale=4; ($ORIG - $NEW) / $ORIG * 100" | bc -l)
echo "Delta: $DELTA%"
```

If delta >1%, investigate skipped points before cutover.

### 9.2 Quality probe — 5 known-good Case II queries

```python
# /home/admin/Fortress-Prime/scripts/qdrant_quality_probe.py
import requests
import json

QDRANT = "http://localhost:6333"
EMBED = "http://192.168.0.105:8102/v1/embeddings"
MODEL = "llama-nemotron-embed-1b-v2"

QUERIES = [
    "What did Knight argue about easement timing?",
    "Section 8 financial breakdown for Q3 2025",
    "Thor James grantor warranty deed",
    "Motion to dismiss analysis on §4 claims",
    "Procedural posture on counsel hire deadline",
]

for q in QUERIES:
    vec = requests.post(EMBED, json={"model": MODEL, "input": [q]}).json()["data"][0]["embedding"]

    new_results = requests.post(
        f"{QDRANT}/collections/legal_ediscovery_v2/points/search",
        json={"vector": vec, "limit": 5, "with_payload": True}
    ).json()["result"]

    print(f"\nQUERY: {q}")
    print("V2 (2048-dim) top-5 source_ids + scores:")
    for r in new_results:
        print(f"  {r.get('score', 0):.4f}  {r['payload'].get('source_id', 'unknown')[:60]}")
```

Expected: scores >0.4 for top-5, source_ids look relevant (not random). Document output in final report.

### 9.3 Audit log review

```bash
grep -E "ERROR|SKIP" /mnt/fortress_nas/audits/qdrant-reindex-*.log | wc -l
```

Skipped/errored count should be <0.5% of total points.

---

## 10. Atomic alias swap

### 10.1 Pre-swap state check

```bash
# Does legal_ediscovery_active alias exist?
curl -fsS http://localhost:6333/aliases | jq '.result.aliases'
```

Three cases:
- **(a)** Alias exists, points at `legal_ediscovery` → atomic delete+create swap
- **(b)** Alias exists, points elsewhere → investigate before any change
- **(c)** Alias doesn't exist → create alias pointing at v2; update Phase B retrieval config to use alias

### 10.2 Atomic swap (case a)

```bash
curl -fsS -X POST "http://localhost:6333/collections/aliases" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {"delete_alias": {"alias_name": "legal_ediscovery_active"}},
      {"create_alias": {"collection_name": "legal_ediscovery_v2", "alias_name": "legal_ediscovery_active"}}
    ]
  }'
```

**Why explicit delete + create:** qdrant#7584 — `create_alias` silently overwrites without warning. Atomic delete+create makes the swap intent explicit.

### 10.3 Verify alias

```bash
curl -fsS http://localhost:6333/aliases | jq '.result.aliases[] | select(.alias_name == "legal_ediscovery_active")'
# Expected: collection_name = legal_ediscovery_v2
```

### 10.4 Phase B v0.1 retrieval config audit

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  grep -rn "legal_ediscovery" --include="*.py" --include="*.yaml" --include="*.yml" | \
    grep -v ".bak" | grep -v "\.git/"
'
```

Inspect every match. Anything referencing `legal_ediscovery` directly (not the `legal_ediscovery_active` alias) needs updating to use the alias. **Do not delete the original collection** — leave for 14-day rollback.

If Phase B already uses the alias, no code change needed. If it uses the bare collection name, single-line config change in retrieval module.

---

## 11. PR

### 11.1 Files to commit

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime

  # Reindex script (productionize)
  git add scripts/reindex_qdrant_collection.py
  git add scripts/qdrant_quality_probe.py

  # Reindex evidence
  cp /mnt/fortress_nas/audits/qdrant-reindex-*.log docs/operational/

  # If Phase B retrieval module needed alias update
  git add fortress-guest-platform/backend/services/case_briefing_synthesizers.py 2>/dev/null || true

  # Final report
  cat > docs/operational/qdrant-reindex-final-report.md <<EOF
# Qdrant legal_ediscovery Reindex Report — $(date +%Y-%m-%d)
[populated per §12]
EOF
  git add docs/operational/qdrant-reindex-final-report.md

  git status
'
```

### 11.2 Commit + PR

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  git commit -m "feat(qdrant): reindex legal_ediscovery 768->2048 against current EMBED

Surfaces existing 738K points as legal_ediscovery_v2 at 2048-dim against
llama-nemotron-embed-1b-v2 (current production EMBED, dim verified in PR
#343). Atomic alias swap of legal_ediscovery_active per qdrant#7584.

Original legal_ediscovery 768-dim collection retained for 14-day rollback
window.

Phase B v0.1 retrieval reads via legal_ediscovery_active alias; no
orchestrator code changes required (verified via grep audit).

Adds reusable scripts/reindex_qdrant_collection.py for future dim
migrations.

Closes Wave 3.5 watchlist item: legal_ediscovery reindex (separate brief).
Frontier endpoint untouched; soak unaffected.
"

  git push -u origin feat/qdrant-legal-ediscovery-reindex-2026-05-01

  gh pr create \
    --title "Qdrant legal_ediscovery reindex 768->2048 (Wave 3.5 retrieval prerequisite for Case II)" \
    --body-file docs/operational/qdrant-reindex-final-report.md \
    --draft
'
```

PR opens as draft. Operator promotes to ready after reviewing reindex log + quality probe output.

---

## 12. Final report (auto-surface at run end)

Surface to chat at run end:

1. **Pre-flight summary**
   - Frontier health throughout
   - EMBED dim confirmed 2048
   - Source collection state (points_count, dim, status)
   - Snapshot ID retained for rollback

2. **Reindex execution**
   - Total points processed
   - Wall time
   - Sustained rate (points/sec)
   - Errors / skipped count
   - Resume checkpoints triggered (if any)

3. **Validation**
   - Point count delta original vs new
   - Quality probe results — top-5 source_ids per query, scores

4. **Alias swap**
   - Pre-swap alias state
   - Post-swap verification
   - Phase B retrieval config audit result

5. **Halt triggers fired** (should be zero on clean run)

6. **PR**
   - Branch, PR number + URL
   - Files committed

7. **Recommended operator next action**
   - Quality probe passes: PR ready for review; Phase B Case II unblocked
   - Quality probe weak: investigate retrieval before Phase B

---

## 13. Constraints

- Branches from `origin/main` only
- Single Claude Code task at a time on spark-2
- Never `--admin`, never `--force`, never self-merge
- DO NOT modify EMBED service config
- DO NOT touch the frontier
- DO NOT delete original `legal_ediscovery` collection (14-day rollback window)
- DO NOT modify Phase B v0.1 orchestrator beyond single-line alias config update if needed
- Atomic alias swap = explicit `delete_alias` + `create_alias` in same transaction
- Reindex script committed for reusability — do not leave as scratch

---

## 14. Rollback procedure

If anything goes wrong post-cutover:

```bash
# Revert alias to point at original
curl -fsS -X POST "http://localhost:6333/collections/aliases" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {"delete_alias": {"alias_name": "legal_ediscovery_active"}},
      {"create_alias": {"collection_name": "legal_ediscovery", "alias_name": "legal_ediscovery_active"}}
    ]
  }'
```

But: original is 768-dim. EMBED is 2048-dim. Rollback only works if you also swap EMBED back to whatever 768-dim model originally built the collection. Likely not feasible in production. **Forward-only is the realistic path.**

If reindex completes and quality probe is bad, the recovery is to investigate why (likely chunk-text payload key issue or batch-size induced ordering) and re-run, not to roll back.

---

End of brief.
