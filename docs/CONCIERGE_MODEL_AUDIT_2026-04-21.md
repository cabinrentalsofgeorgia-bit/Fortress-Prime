# Concierge Model Audit — 2026-04-21

**Branch:** feat/concierge-model-audit

---

## TL;DR

**The 9-seat council is running in fully degraded mode.** All 9 seats return
blank responses, converted to `signal=NEUTRAL, conviction=0.5`. No real
deliberation is occurring.

Two root causes:

1. **LiteLLM gateway authentication broken** — `LITELLM_MASTER_KEY` in
   `fortress-guest-platform/.env` does not match the `master_key` value in
   `litellm_config.yaml`. All cloud provider calls fail with HTTP 400.

2. **Local model names are stale** — `HYDRA_MODEL_120B = "gpt-oss:120b"` and
   `HYDRA_MODEL_32B = "qwen3:32b"` reference models not loaded on any node.
   vLLM endpoint at spark-4:8000 is not running.

---

## Fleet Inventory (live as of audit)

| Node | IP | Models |
|---|---|---|
| spark-2 | 192.168.0.100 | qwen2.5:7b, qwen2.5:0.5b, nomic-embed-text |
| spark-1 | 192.168.0.104 | qwen2.5:7b, qwen2.5:32b, deepseek-r1:70b, mistral, llava, llama3.2-vision:90b, nomic-embed-text |
| spark-3 | 192.168.0.105 | llama3.2-vision:90b x2, nomic-embed-text |
| spark-4 | 192.168.0.106 | qwen2.5:7b, qwen2.5:32b, deepseek-r1:70b, mistral, llava, nomic-embed-text |

LiteLLM gateway: **running** at 127.0.0.1:8002.
Configured models: claude-sonnet-4-6, gpt-4o, grok-4, gemini-2.5-pro, deepseek-chat/reasoner.
API keys for all providers present in env.
**Unreachable from concierge engine due to master key mismatch — see item A.**

---

## Reference Audit

| Constant | Value | Endpoint | Status |
|---|---|---|---|
| `ANTHROPIC_MODEL` | claude-sonnet-4-5-20250929 | LiteLLM :8002/v1 | **BROKEN** — key mismatch + model not in LiteLLM config |
| `GEMINI_MODEL` | gemini-2.5-pro | LiteLLM :8002/v1 | **BROKEN** — key mismatch |
| `XAI_MODEL` | grok-3 | LiteLLM :8002/v1 | **BROKEN** — key mismatch + name not in config |
| `XAI_MODEL_FLAGSHIP` | grok-4-0709 | LiteLLM :8002/v1 | **BROKEN** — key mismatch + name not in config |
| `HYDRA_MODEL_32B` | qwen3:32b | spark-3 :11434/v1 | **DEAD** — not on spark-3 (vision-only) |
| `HYDRA_MODEL_120B` | gpt-oss:120b | spark-4 :11434/v1 | **DEAD** — not on any node |
| `HYDRA_MODEL` | alias of HYDRA_MODEL_120B | same | **DEAD** |
| `VLLM_MODEL_120B` | openai/gpt-oss-120b | spark-4 :8000/v1 | **DEAD** — vLLM not running |
| `SWARM_MODEL` | qwen2.5:7b | LiteLLM :8002/v1 | **BROKEN** — key mismatch |
| `"qwen2.5:7b"` (PR #114 literal) | literal | spark-4 :11434/v1 | **WORKING** |

---

## 9-Seat Council — All Blank

```
Seat 1 (ANTHROPIC)    → LiteLLM 401 → HYDRA_120B dead → SWARM 401 → BLANK
Seat 2 (ANTHROPIC)    → same → BLANK
Seat 3 (GEMINI)       → LiteLLM 401 → HYDRA_120B dead → SWARM 401 → BLANK
Seat 4 (HYDRA_32B)    → qwen3:32b not on spark-3 → HYDRA_120B dead → SWARM 401 → BLANK
Seat 5 (XAI)          → LiteLLM 401 → HYDRA_120B dead → SWARM 401 → BLANK
Seat 6 (HYDRA_32B)    → same as seat 4 → BLANK
Seat 7 (VLLM_120B)    → :8000 not running → HYDRA_32B dead → SWARM 401 → BLANK
Seat 8 (GEMINI)       → same as seat 3 → BLANK
Seat 9 (XAI_FLAGSHIP) → LiteLLM 401 → HYDRA_120B dead → SWARM 401 → BLANK
```

All seats: `ConciergeOpinion(NEUTRAL, conviction=0.5, "Seat returned a blank response.")`

The 2-3 RESOLVE votes observed in recent council output are noise from
`_parse_loose_opinion` pattern-matching on LiteLLM error payloads.

`_compose_draft_reply` (SMS composer, line 1211) also uses `HYDRA_MODEL_120B`
→ blank → hardcoded fallback template. Same failure as email before PR #114.

---

## Fixes in This PR (safe code-only)

### 1. `ANTHROPIC_MODEL` default → `claude-sonnet-4-6`
Matches the model name in LiteLLM config. Pre-emptive; applies once key is fixed.

### 2. SMS `_compose_draft_reply` → `qwen2.5:7b` at `HYDRA_120B_URL`
Same fix as PR #114 for the email composer. SMS drafts will now produce real
output immediately, without waiting for the LiteLLM key fix.

---

## Gary Decisions Required

**A — LiteLLM master key (HIGHEST PRIORITY)**
`LITELLM_MASTER_KEY` in `fortress-guest-platform/.env` and `master_key` in
`litellm_config.yaml` are out of sync. Env-only fix, no code change. Restores
4-5 of 9 council seats immediately.

**B — XAI model names**
Code: `grok-3` / `grok-4-0709`. LiteLLM config: `grok-4`. Decide which to use.

**C — seats 4 and 6 (`HYDRA_MODEL_32B` / `qwen3:32b`)**
`qwen3:32b` not on any node; spark-3 is vision-only. Options:
- Load `qwen3:32b` on spark-1 or spark-4
- Redirect to `qwen2.5:32b` on spark-1 (loaded, capable)
- Redirect to `deepseek-r1:70b` on spark-1/spark-4 (reasoning tier)

**D — seat 7 (`VLLM_MODEL_120B` / spark-4:8000)**
vLLM not running. Start the service, or redirect seat 7 to available model.

---

## Expected State After This PR + Key Fix (item A)

| Layer | Now | After this PR | After key fix |
|---|---|---|---|
| Email composer | WORKING | WORKING | WORKING |
| SMS composer | DEAD | **WORKING** | WORKING |
| Seats 1-3, 8 (cloud) | BLANK | BLANK | **WORKING** (4 seats) |
| Seat 9 (XAI flagship) | BLANK | BLANK | Working if name fixed |
| Seats 4, 6 (HYDRA_32B) | BLANK | BLANK | Gary decision |
| Seat 7 (VLLM_120B) | BLANK | BLANK | Gary decision |
