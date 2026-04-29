# Spark-3 + Spark-4 Retained State — 2026-04-29

**Driver:** ADR-004 amendment v2 (retain-and-document)
**Status:** No state changes from baseline; all services restored post-incident.

This document codifies the workloads on spark-3 and spark-4 that are formally retained per ADR-004 amendment v2, and enumerates the production-caller surface that must NOT be modified without a migration plan.

---

## Spark-3 (host: `spark-3`, fabric A 10.10.10.3, mgmt 192.168.0.105)

| Service | Status | Production callers |
|---|---|---|
| Vision NIM (`fortress-nim-vision-concierge`) | Active 6+d | Production sovereign workload |
| ollama (Docker container, port 11434) | Active | `crog_concierge_engine.HYDRA_32B_URL` default, `persona_template.HYDRA_HEAD_3` default, `fortress_atlas.yaml` (vision_specialist), other doc references |
| ollama models | qwen2.5:7b (privilege classifier), llama3.2-vision:90b, llama3.2-vision:latest, nomic-embed-text:latest | Various |
| `fortress-ray-worker.service` | Active, enabled | Inference cluster member |
| docling-shredder container | Active 13+d | Legal PDF parser |
| llama.cpp build | Present | TITAN-tier serving infrastructure |
| nccl-tests | Present | Fabric verification |
| Cached NIM images | nv-embedqa-e5-v5 (4.27 GB), deepseek-r1-distill-llama-70b (15 GB), cosmos-reason2-2b, nemotron-3-super-120b weights | Future deployment candidates |
| ConnectX 100Gbps fabric | UP, RoCE enumerated cleanly | Inference cluster |
| Postgres / app data | none | — |

## Spark-4 (host: `Spark-4`, fabric A 10.10.10.4, mgmt 192.168.0.106)

| Service | Status | Production callers |
|---|---|---|
| ollama.service (systemd, port 11434) | Active, enabled | `fortress-guest-platform/.env` SWARM_URL + HYDRA_FALLBACK_URL, `ingest_taylor_sent_tarball.py`, `reclassify_other_topics.py`, `sent_mail_retriever.py`, `crog_concierge_engine.HYDRA_120B_URL` default, `persona_template.HYDRA_HEAD_4` default, `fortress_atlas.yaml` (deep_reasoning_redundancy + vrs_fast_primary) |
| ollama models | qwen2.5:7b, qwen2.5:32b, deepseek-r1:70b, nomic-embed-text:latest, llava:latest, mistral:latest | SWARM tier per fortress_atlas.yaml |
| `fortress-qdrant-vrs.service` | Active 4+d | VRS dual-write target |
| SenseVoice container (ARM64) | Active 4+d | Deposition ASR (current, replace when NIM ASR ARM64 ships) |
| `fortress-ray-worker.service` | Active, enabled | Inference cluster member |
| llama.cpp build | Present | TITAN serving |
| nccl-tests | Present | Fabric verification |
| ConnectX 100Gbps fabric | Link UP, RDMA enumeration empty (P3 follow-up) | Inference cluster |
| Postgres / app data | none | — |

---

## Caller surface (must not be modified without migration)

### Spark-3 ollama callers (192.168.0.105:11434)

| File | Line | Pattern |
|---|---|---|
| `crog_concierge_engine.py` | 61 | HYDRA_32B_URL default → `http://192.168.0.105:11434/v1` |
| `tools/persona_template.py` | 82 | HYDRA_HEAD_3 default → `http://192.168.0.105:11434` |
| `fortress_atlas.yaml` | spark-3 entry | `ollama_url: http://192.168.0.105:11434` |
| `docs/SPARK3_SHARED_GPU_RUNBOOK.md` | various | spark-3 vision-Ollama host |

### Spark-4 ollama callers (192.168.0.106:11434)

| File | Line | Pattern |
|---|---|---|
| `fortress-guest-platform/.env` | 192 | `SWARM_URL=http://192.168.0.106:11434/v1` |
| `fortress-guest-platform/.env` | 196 | `HYDRA_FALLBACK_URL=http://192.168.0.106:11434/v1` |
| `src/ingest_taylor_sent_tarball.py` | 69 | `EMBED_URL = "http://192.168.0.106:11434/api/embeddings"` |
| `src/reclassify_other_topics.py` | 57 | `EMBED_URL = "http://192.168.0.106:11434"` |
| `fortress-guest-platform/backend/services/sent_mail_retriever.py` | 74 | `"http://192.168.0.106:11434/api/embeddings"` |
| `fortress-guest-platform/backend/services/crog_concierge_engine.py` | 62 | HYDRA_120B_URL default → `http://192.168.0.106:11434/v1` |
| `tools/persona_template.py` | 83 | HYDRA_HEAD_4 default → `http://192.168.0.106:11434` |
| `fortress_atlas.yaml` | spark-4 entry | `ollama_url: http://192.168.0.106:11434` |
| 6× backup `.env.bak.*` files | various | SWARM_URL/HYDRA_FALLBACK_URL same |

---

## Migration plan (deferred)

Service consolidation (collapsing ollama topology to fewer nodes) requires migrating all callers above. Not in scope for this PR, this session, or the next session. Filed as P4.

Pre-conditions before any consolidation:
1. All callers above migrated to new endpoints
2. `.env` files updated (production + backups noted)
3. `fortress_atlas.yaml` updated
4. Hardcoded Python URLs replaced with env-overrides at minimum
5. fortress-guest-platform tested end-to-end against new topology

Action plan: separate brief drafted when operator decides consolidation is worth the migration cost. Not urgent. The current 3-node ollama topology (spark-2 + spark-3 + spark-4) is operationally fine.

---

## Cross-references

- ADR-004 amendment v2: `docs/architecture/cross-division/ADR-004-app-vs-inference-boundary.md` § Amendment 2026-04-29
- Incident lessons: `docs/operational/incident-2026-04-29-ollama-removal.md`
- Original wipe brief (header-noted as superseded): `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md`
- MASTER-PLAN.md §6.5 — open follow-ups (RDMA debug, VRS migration, ASR monitor, doc/config reconciliation, ollama consolidation)
