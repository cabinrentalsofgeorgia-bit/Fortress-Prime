# NAS Model & NIM Cache Audit — 2026-04-28

## Summary

Total model storage: **443G** across 4 directories with significant drift between underscore and hyphen naming conventions. The poisoned cache `llm-nim-runtime-cache.poisoned-20260424` (52K, quarantined Apr 24) appears unrelated to current BRAIN mounts, which use per-host subdirectories. BRAIN actively uses nim-cache (hyphen) while nim_cache (underscore) contains different models.

## Directory inventory

| Path | Size | Last modified | Status |
|---|---|---|---|
| /mnt/fortress_nas/models | 156G | 2026-04-22 18:38 | **Active** — legal-instruct training artifacts |
| /mnt/fortress_nas/model_vault | 0G | 2026-04-07 10:28 | **Empty** — placeholder directories only |
| /mnt/fortress_nas/nim_cache | 108G | 2026-03-15 20:32 | **Stale** — DeepSeek model, NGC artifacts |
| /mnt/fortress_nas/nim-cache | 179G | 2026-04-23 19:31 | **Active** — BRAIN production mounts |

**Total model storage**: 443G  
**NAS capacity**: 54T available / 63T total (16% used)

## Drift analysis

**Critical naming drift**: `nim_cache` (underscore) and `nim-cache` (hyphen) are separate directories with distinct contents:

**nim_cache (108G, underscore)**:
- `hub/` — 90G DeepSeek-R1-Distill-Llama-70B (incomplete download)
- `ngc/` — 18G various NGC NIM models (llama-3.3-70b, embed models)
- Last activity: March 2026

**nim-cache (179G, hyphen)**:
- `hf/` — 142G Nemotron models + runtime caches  
- `nim/` — 37G NIM containers and weights
- Per-host runtime cache directories (spark-1, spark-5, etc.)
- Last activity: April 2026

**Canonical winner**: `nim-cache` (hyphen) — actively used by BRAIN production service.

## Poisoned cache verdict

**Poisoned cache is NOT the BRAIN gibberish cause**.

**Forensics**:
- Path: `/mnt/fortress_nas/nim-cache/hf/llm-nim-runtime-cache.poisoned-20260424/`
- Size: 52K (tiny — mostly empty directories)
- Quarantined: 2026-04-24 09:39:13 (directory rename/move)
- Original modification: 2026-04-23 13:22:36
- Contents: Empty `local_cache/` and `huggingface/hub/modules/` skeleton

**Verdict**: The poisoned cache was quarantined in isolation and contains no active artifacts. BRAIN mounts use per-host subdirectories (`llm-nim-runtime-cache/spark-5`) which bypass the quarantined directory entirely.

## Active mounts

**BRAIN (fortress-nim-brain.service)**:
- **Model weights**: `/mnt/fortress_nas/nim-cache/hf/nvidia-Llama-3_3-Nemotron-Super-49B-v1_5-FP8` → `/opt/nim/models/`
- **Runtime cache**: `/mnt/fortress_nas/nim-cache/hf/llm-nim-runtime-cache/%H` → `/opt/nim/.cache` (where %H = hostname)
  - spark-5 uses: `/mnt/fortress_nas/nim-cache/hf/llm-nim-runtime-cache/spark-5`

**Training/Evaluation Services**:
- `/mnt/fortress_nas/models/` — Legal-instruct training outputs, Qwen2.5-7B base model
- `/mnt/fortress_nas/models/legal-instruct-production` → symlink to latest legal-instruct adapter

**NIM Container Management**:
- `nim_pull_to_nas.py` script uses `/mnt/fortress_nas/nim-cache/nim/` for container storage

## Model completeness assessment

**Complete models**:
- nvidia-Llama-3_3-Nemotron-Super-49B-v1_5-FP8 (21 safetensors files, production ready)
- Qwen2.5-7B-Instruct (4 safetensors files, 15G)
- Legal-instruct adapters (multiple epochs, production symlink)

**Incomplete models**:
- **DeepSeek-R1-Distill-Llama-70B** (90G, contains `.incomplete` files — download interrupted)
  - Location: `/mnt/fortress_nas/nim_cache/hub/models--deepseek-ai--DeepSeek-R1-Distill-Llama-70B/`
  - Not suitable for deployment without re-download

## Recommended cleanup (NOT executed in this pass)

### High Priority
1. **Consolidate cache directories**: Migrate useful artifacts from `nim_cache/` (underscore) to `nim-cache/` (hyphen) and retire the underscore version — **saves 108G**
2. **Complete DeepSeek download**: Either complete the interrupted download or delete the 90G of incomplete artifacts
3. **Remove poisoned cache**: Delete `/mnt/fortress_nas/nim-cache/hf/llm-nim-runtime-cache.poisoned-20260424/` (52K cleanup)

### Medium Priority  
4. **Archive old legal-instruct epochs**: Move non-production legal-instruct checkpoints to `/mnt/fortress_nas/models/archive/` — **saves ~2G**
5. **Audit model_vault**: Remove empty placeholder directories or populate with intended content

### Low Priority
6. **Document cache strategy**: Establish naming conventions to prevent future underscore/hyphen drift
7. **Monitor runtime cache growth**: Per-host cache directories in `llm-nim-runtime-cache/` may accumulate over time

**Estimated total reclamable**: ~110G (primarily from nim_cache consolidation + DeepSeek cleanup)

## Next actions

1. **Operator decision**: Approve consolidation of nim_cache → nim-cache migration
2. **BRAIN service verification**: Confirm no other services depend on nim_cache (underscore) before deletion
3. **DeepSeek strategy**: Decide whether to complete download (70B deployment candidate for spark-4/spark-6) or delete
4. **Cache monitoring**: Establish alerting for NAS capacity growth trends

---

**Audit completed**: 2026-04-28  
**Total audit time**: Read-only investigation  
**No modifications made**: All findings are observational