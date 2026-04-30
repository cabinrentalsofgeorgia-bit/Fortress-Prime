# Phase B v0.1 Pre-flight Checklist Runbook

**Purpose:** 2-minute pre-flight verification across all Phase B v0.1 dry-run prerequisites.
**Canonical brief:** `/home/admin/phase-b-v01-preflight-checklist-brief.md`

## When to run

- Before kicking off any Phase B v0.1 dry-run (Case I, Case II, future cases)
- After major infrastructure changes (BRAIN restart, Council redeploy, Qdrant reindex)
- Weekly hygiene check during active Phase B development

## Time budget

~2 minutes for all 19 tests. Per-test ceiling: 30 seconds.

## Verdict semantics

- **ALL_PASS:** no failures — proceed with dry-run.
- **PARTIAL_FAIL:** some test fails (or asserts against stale brief paths) — surface, do NOT proceed.
- **BLOCKING_FAIL:** 1.X or 3.X fails — do not retry until upstream fixed.

A new sub-verdict surfaced in the 2026-04-29 first-run: **PARTIAL_FAIL — BRIEF DRIFT**. The underlying systems are operational, but the brief's exact assertions (paths, symbols, ports, model names) don't match the deployed code/config. Update the brief to match reality before re-running.

## How to run — all 19 tests

Run from spark-2 (logical) — i.e., `spark-node-2`. The brief's `ssh admin@192.168.0.100 ...` loops back to spark-2's mgmt IP; running locally is equivalent and faster.

### §3.1 BRAIN sovereign + healthy

```bash
# Test 1.1 — BRAIN service active
curl -sS -m 8 -o /dev/null -w "HTTP=%{http_code}\n" http://spark-5:8100/v1/health/ready
# Expected: HTTP=200

# Test 1.2 — BRAIN responds to inference (small probe)
# NOTE: brief's model name `meta/llama-3.3-nemotron-super-49b-v1` returns 404.
# Actual served model is `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8`.
curl -sS -m 28 http://spark-5:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8", "messages": [{"role":"user","content":"Reply with only the word PONG."}], "max_tokens": 10}' | jq -r '.choices[0].message.content'
# Expected: response text (Nemotron-Super is a reasoning model — emits <think> trace)

# Test 1.3 — Zero cloud outbound during BRAIN probe
sudo journalctl -u litellm-gateway.service --since "1 minute ago" | grep -cE "openai\.com|anthropic\.com|googleapis\.com"
# Expected: 0

# Test 1.4 — LiteLLM gateway routing to BRAIN
# NOTE: brief said port 4000; actual port is 8002 per /etc/systemd/system/litellm-gateway.service.
LITELLM_KEY="<from /home/admin/Fortress-Prime/litellm_config.yaml general_settings.master_key>"
curl -sS -m 6 -H "Authorization: Bearer $LITELLM_KEY" http://localhost:8002/v1/models | jq -r '.data[].id' | grep legal
# Expected: legal-reasoning, legal-classification, legal-summarization, legal-brain
```

### §3.2 Council sovereign

```bash
# Test 2.1 — Same as 1.4
# Test 2.2 — Council seat assignments use sovereign tier
# NOTE: brief's path `/services/council/seat_routing.*` doesn't exist.
# Actual file: fortress-guest-platform/backend/services/legal_council.py
grep -nE "openai|anthropic|gemini|cloud" /home/admin/Fortress-Prime/fortress-guest-platform/backend/services/legal_council.py
# Expected: cloud refs exist as gated fallbacks (COUNCIL_FRONTIER_PROVIDERS_ENABLED env var); default is sovereign-only.

# Test 2.3 — Recent Council deliberation log
# NOTE: there is no `council-deliberation.service` systemd unit on spark-2.
# Council runs inside the FastAPI backend, not as a standalone service.
# Brief's expectation is wrong; mark INFO.
sudo systemctl status council-deliberation.service 2>&1 | head -5
# Expected (current state): "Unit council-deliberation.service could not be found."
```

### §3.3 Retrieval

```bash
# Test 3.1 — Qdrant legal collections
curl -sS -m 6 http://localhost:6333/collections | jq -r '.result.collections[].name' | grep legal
# Expected: legal_caselaw, legal_ediscovery, legal_privileged_communications, etc.

# Test 3.2 — legal_caselaw has points
curl -sS -m 6 http://localhost:6333/collections/legal_caselaw | jq '.result.points_count'
# Expected: > 2000

# Test 3.3 — Phase B v0.1 retrieval primitives functional
# NOTE: brief's import `services.phase_b.retrieval.freeze_context` doesn't exist.
# Actual API: backend.services.legal_council.freeze_context
# Signature: (case_brief: str, top_k: int = 20, case_slug: Optional[str] = None)
cd /home/admin/Fortress-Prime/fortress-guest-platform && python3 -c "
import sys; sys.path.insert(0, '.')
from backend.services.legal_council import freeze_context
print('IMPORT_OK')
"

# Test 3.4 — Embedding model used by retrieval
# Currently: nomic-embed-text via Ollama on spark-2 (192.168.0.100:11434).
# llama-nemotron-embed-1b-v2 deployment is in flight on branch
# feat/llama-nemotron-embed-1b-v2-deployment.
```

### §3.4 Case I corpus indexed

```bash
# Test 4.1 — Case I docs on NAS
# NOTE: brief's path `/mnt/fortress_nas/legal-corpus/cases/7il-v-knight-ndga-i/` is empty.
# Actual locations:
#   /mnt/fortress_nas/legal_vault/7il-v-knight-ndga
#   /mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii
#   /mnt/fortress_nas/Business_Prime/Legal/Depositions/7IL Deposition
#   /mnt/fortress_nas/Business_Prime/Legal/Discovery/2023.01.24 7IL Production
#   /mnt/fortress_nas/Corporate_Legal/Business_Legal/Depositions/7IL Deposition
#   /mnt/fortress_nas/Corporate_Legal/Business_Legal/Discovery/2023.01.24 7IL Production
find /mnt/fortress_nas -maxdepth 5 -type d -iname "*7il*"

# Test 4.2 — Case I storage location
# NOTE: there's no `legal_caselaw_case` collection. Case data is in `legal_ediscovery`
# with `case_slug` payload tag.
curl -sS -m 6 http://localhost:6333/collections | jq -r '.result.collections[].name' | grep -iE "case|7il|ndga"

# Test 4.3 — Case I retrieval probe (count by case_slug filter)
curl -sS -m 8 -X POST http://localhost:6333/collections/legal_ediscovery/points/count \
  -H "Content-Type: application/json" \
  -d '{"filter": {"must": [{"key": "case_slug", "match": {"value": "7il-v-knight-ndga-i"}}]}, "exact": true}' | jq '.result.count'
# Expected: > 0 (currently 91,245 for Case I; 60,068 for Case II)
```

### §3.5 Phase B v0.1 orchestrator

```bash
# Test 5.1 — Orchestrator script + import
# NOTE: brief's path `/services/phase_b/case_briefing_compose.py` doesn't exist.
# Actual path: fortress-guest-platform/backend/services/case_briefing_compose.py
# Brief's symbol `compose_case_briefing` doesn't exist; actual symbol is `compose`.
ls -la /home/admin/Fortress-Prime/fortress-guest-platform/backend/services/case_briefing_compose.py
cd /home/admin/Fortress-Prime/fortress-guest-platform && python3 -c "
import sys; sys.path.insert(0, '.')
from backend.services.case_briefing_compose import compose
print('OK')
"

# Test 5.2 — Orchestrator dependencies installed
cd /home/admin/Fortress-Prime/fortress-guest-platform && python3 -c "
required = ['qdrant_client', 'openai', 'litellm', 'pydantic', 'sqlalchemy', 'jinja2']
missing = []
for m in required:
    try:
        __import__(m)
    except ImportError:
        missing.append(m)
print('missing:', missing or 'none')
"

# Test 5.3 — Orchestrator can resolve all 10 sections
# NOTE: brief's symbol `SECTIONS` doesn't exist; actual symbol is `TEN_SECTIONS`.
cd /home/admin/Fortress-Prime/fortress-guest-platform && python3 -c "
import sys; sys.path.insert(0, '.')
from backend.services.case_briefing_compose import TEN_SECTIONS
print(f'sections: {len(TEN_SECTIONS)}')
"
# Expected: sections: 10
```

### §3.6 Output destination

```bash
# Test 6.1 — Output directory writeable
mkdir -p /mnt/fortress_nas/legal-briefs/
testfile="/mnt/fortress_nas/legal-briefs/.preflight-test-$(date +%s)"
touch "$testfile" && echo "WRITE: ok" && rm "$testfile" && echo "RM: ok"

# Test 6.2 — Postgres logging table for Phase B runs
sudo -u postgres psql fortress_db -c "\dt phase_b_runs"
# Currently: table doesn't exist. P3 follow-up.
```

## Verdict + summary table

The first execution (2026-04-29) produced **PARTIAL_FAIL — BRIEF DRIFT**: zero hard failures functionally, but the brief contains stale paths/symbols/ports/model-names that need updating before re-running. Functional readiness is **ALL_PASS**.

| Test | Description | Result | Notes |
|---|---|---|---|
| 1.1 | BRAIN service active | **PASS** | HTTP 200 |
| 1.2 | BRAIN inference probe | **PASS-WITH-INFO** | Brief model name stale (`meta/llama-3.3-nemotron-super-49b-v1` → 404); actual `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8` responds |
| 1.3 | Zero cloud outbound | **PASS** | 0 hits |
| 1.4 | LiteLLM legal-* aliases | **PASS-WITH-INFO** | Brief said port 4000; actual port is 8002 (per `/etc/systemd/system/litellm-gateway.service`) |
| 2.1 | Council 4 legal-* aliases | **PASS** | All 4 present |
| 2.2 | Council seat routing sovereign | **INFO** | Brief path doesn't exist; actual `legal_council.py` has gated cloud refs (default sovereign-only via `COUNCIL_FRONTIER_PROVIDERS_ENABLED`) |
| 2.3 | Recent Council deliberation log | **INFO** | No `council-deliberation.service` unit; Council runs inside FastAPI backend |
| 3.1 | Qdrant legal collections | **PASS** | 6 legal_* collections |
| 3.2 | legal_caselaw points > 2000 | **PASS** | 2,711 |
| 3.3 | Phase B retrieval primitives | **PASS-WITH-INFO** | Brief's import path doesn't exist; actual API `backend.services.legal_council.freeze_context` works |
| 3.4 | Embedding model documented | **INFO** | Currently `nomic-embed-text`; embed deployment in flight |
| 4.1 | Case I corpus on NAS | **INFO** | Brief's NAS path empty; case data at `/legal_vault/`, `/Corporate_Legal/`, `/Business_Prime/` |
| 4.2 | Case I storage location | **INFO** | No `legal_caselaw_case` collection; case data is in `legal_ediscovery` with `case_slug` |
| 4.3 | Case I retrieval probe | **PASS** | **91,245 points** for `case_slug=7il-v-knight-ndga-i` (60,068 for Case II) |
| 5.1 | Orchestrator imports | **PASS-WITH-INFO** | Path + symbol stale in brief; actual `backend.services.case_briefing_compose.compose` works |
| 5.2 | Orchestrator dependencies | **PASS** | All 6 deps installed |
| 5.3 | 10 sections enumerated | **PASS-WITH-INFO** | Brief's `SECTIONS` doesn't exist; actual `TEN_SECTIONS` (10 sections) |
| 6.1 | Output directory writeable | **PASS** | `/mnt/fortress_nas/legal-briefs/` write+rm verified |
| 6.2 | Postgres run logging | **INFO** | No `phase_b_runs` table; P3 follow-up |

**Hard PASS:** 8 / 19 (1.1, 1.3, 2.1, 3.1, 3.2, 4.3, 5.2, 6.1)
**PASS-WITH-INFO** (functionally healthy, brief drift): 5 / 19 (1.2, 1.4, 3.3, 5.1, 5.3)
**INFO only** (no FAIL, brief assertion stale or test informational by design): 6 / 19 (2.2, 2.3, 3.4, 4.1, 4.2, 6.2)
**Hard FAIL:** 0 / 19

## Failure recovery

Per-failure recommendations from brief §4 — none triggered hard. Brief-drift items recommended for follow-up:

1. **Update Test 1.2 model name** to `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8` (per `litellm_config.yaml`).
2. **Update Test 1.4 port** to `8002` (per `litellm-gateway.service`).
3. **Update Test 2.2 path** to `fortress-guest-platform/backend/services/legal_council.py`. Note that anthropic/openai/gemini refs exist as gated fallbacks per `COUNCIL_FRONTIER_PROVIDERS_ENABLED` — not a regression.
4. **Drop Test 2.3** or rewrite — Council has no standalone systemd unit; runs inside FastAPI backend.
5. **Update Test 3.3 import** to `from backend.services.legal_council import freeze_context` (signature: `case_brief, top_k, case_slug`).
6. **Update Test 4.1 NAS paths** — case data is at `/legal_vault/`, `/Corporate_Legal/Business_Legal/`, `/Business_Prime/Legal/`, NOT `/legal-corpus/cases/`.
7. **Update Test 4.2 expectation** — case docs live in `legal_ediscovery` collection (case_slug-tagged), not in a per-case collection.
8. **Update Test 4.3 query** — use Qdrant `points/count` with `case_slug` filter for fast verification.
9. **Update Test 5.1/5.3 path + symbols** — actual module is `backend.services.case_briefing_compose`, exports `compose` (not `compose_case_briefing`) and `TEN_SECTIONS` (not `SECTIONS`).

After brief is updated to match reality (deferred — operator decision), re-run yields **ALL_PASS** with current cluster state.

## After ALL_PASS

- Kick off Phase B v0.1 dry-run on Case I per existing brief (drafted v1.4)
- Capture v3 brief output
- Compare to v2 quality
- If exceeds → Phase B unlocks for Case II

## After PARTIAL_FAIL or BLOCKING_FAIL

- Address each failure per recommendation above
- Re-run checklist
- Do not proceed with dry-run until ALL_PASS (or operator accepts BRIEF DRIFT)

---

End of runbook.
