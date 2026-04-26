# Shared: Sentinel — NAS Walker

Spark allocation:
- **Current:** Spark 2
- **Target:** **Spark 2 permanent** (per ADR-002 LOCKED 2026-04-26 — NAS mounts identically from any spark, per-division NAS paths are already cleanly separated by directory tree, centralization avoids 4× sync overhead with no architectural benefit)

Last updated: 2026-04-26

## Technical overview

Sentinel is the cross-cutting NAS document indexer. Walks `/mnt/fortress_nas/` directories, extracts text from each file, chunks + embeds via nomic, upserts to the `fortress_knowledge` Qdrant collection. Owned exclusively by Sentinel — other code paths (notably the legal vault ingestion pipeline) do **not** write to `fortress_knowledge`.

This boundary is intentional: legal docs go to `legal_ediscovery` / `legal_privileged_communications`, property docs to `fortress_knowledge`, never the same chunk in both.

## Walker scope

Per visible code paths:

- `/mnt/fortress_nas/Business_Prime/` — property docs (acquisitions / crog-vrs)
- `/mnt/fortress_nas/sectors/` — cross-sector shared docs
- (legal NAS folders are explicitly **out of scope** for Sentinel; legal owns its own ingestion via `vault_ingest_legal_case.py`)

## State

- `/.fortress_sentinel_state.json` (in `/home/admin/`) — recursive crawler state
- `/.recursive_crawler_chroma_state.json` — alternative chroma-backed state
- `/.nas_harvester_state.json` — harvester checkpoint

These state files exist on the operator host; Sentinel uses them to resume incremental walks without re-processing unchanged files.

## Consumers

- Council deliberation (when general-knowledge retrieval needed, not case-scoped)
- crog-vrs document search
- acquisitions document search (TBD; per atlas)

## Contract / API surface

- Sentinel writes to `fortress_knowledge` only. **Read-only consumers** access via standard Qdrant search API.
- No REST surface today (Sentinel is a daemon / scheduled walker)
- File ownership respected: Sentinel does not modify NAS files, only reads

## Where to read the code

- `tools/fortress_sentinel.py` — main walker
- `tools/nvidia_sentinel.py` — possibly a hardware-monitoring sibling (different from NAS walker; needs verification)
- `src/mailplus_sentinel.py` — email-related sentinel (possibly captain-adjacent; needs verification)
- `backend/services/competitive_sentinel.py` — competitive-pricing sentinel (different from NAS walker)
- State files: see above

## Open questions

- Confirm Sentinel's exact systemd unit name / scheduling
- Does Sentinel handle legal NAS at all, or is the legal-vault path entirely separate?
- What's the recursion strategy — depth-first, breadth-first, time-prioritized?
- Are there per-folder allow/deny lists?

## Cross-references

- [`qdrant-collections.md`](qdrant-collections.md) — `fortress_knowledge` ownership row
- [`../divisions/fortress-legal.md`](../divisions/fortress-legal.md) — explicitly does NOT use Sentinel
- Vault ingest runbook: [`../../runbooks/legal-vault-ingest.md`](../../runbooks/legal-vault-ingest.md)

Last updated: 2026-04-26
