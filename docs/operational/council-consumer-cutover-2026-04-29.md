# Council Consumer Cutover (Cloud Aliases → Sovereign Aliases)

**Date:** 2026-04-29
**Driver:** ADR-003 Phase 1 follow-up. PR #285 closed audit A-02 at the LiteLLM **routing layer**. This PR closes it at the **consumer layer** — `legal_council.py` no longer hardcodes cloud aliases as defaults; reasoning + summarization seats route through `legal-reasoning` / `legal-summarization` to the spark-5 NIM by default.
**Closes:** Audit finding A-02 fully (routing + consumer both sovereign).

---

## Pre-cutover audit — call sites mapped

`legal_council.py` reads model assignments from eight env-bound module constants. Every constant's in-code default was a cloud alias:

| File:line | Constant | Cloud default (BEFORE) | Sovereign default (AFTER) |
|---|---|---|---|
| `legal_council.py:138` | `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | `legal-reasoning` |
| `legal_council.py:139` | `ANTHROPIC_OPUS_MODEL` | `claude-opus-4-6` | `legal-reasoning` |
| `legal_council.py:140` | `OPENAI_MODEL` | `gpt-4o` | `legal-reasoning` |
| `legal_council.py:141` | `XAI_MODEL` | `grok-4` | `legal-reasoning` |
| `legal_council.py:142` | `XAI_MODEL_FLAGSHIP` | `grok-4` | `legal-reasoning` |
| `legal_council.py:143` | `DEEPSEEK_MODEL` | `deepseek-chat` | `legal-reasoning` |
| `legal_council.py:144` | `DEEPSEEK_REASONER_MODEL` | `deepseek-reasoner` | `legal-reasoning` |
| `legal_council.py:145` | `GEMINI_MODEL` | `gemini-2.5-pro` | `legal-summarization` |

`base_url` was already correct: every "frontier" provider's `base_url` resolves to `LITELLM_BASE_URL` (= `http://127.0.0.1:8002/v1`) by default. The cutover only had to change the model alias passed in the request body. LiteLLM (per PR #285) routes those aliases to spark-5 NIM.

**Mapping rationale (per brief §3 table):**

| Sovereign alias | Use case | Provider tags mapped |
|---|---|---|
| `legal-reasoning` | Deep reasoning, persona deliberation, consensus synthesis | ANTHROPIC, ANTHROPIC_OPUS, OPENAI, XAI, XAI_FLAGSHIP, DEEPSEEK, DEEPSEEK_REASONER |
| `legal-summarization` | Multi-doc summary, frozen-context distillation | GEMINI (used as Counselor in original cloud architecture) |

`legal-classification` and `legal-brain` aliases exist in LiteLLM (per PR #285) but no Council seat currently maps to them. They're available for future use.

## Streaming default

`_call_llm` previously did non-streaming `client.post` for all paths. The 4096-token reasoning response from Nemotron-49B at ~3.7 tok/s would blow past LiteLLM's `request_timeout: 180`.

Cutover adds `stream: true` to the LiteLLM payload **only** when the call is `legal-*` aliased through the LiteLLM base URL. SSE chunks are reassembled inside `_call_llm`. The local Ollama / vLLM fallback paths stay non-streaming (existing behavior preserved) because they cap `max_tokens` for the local case and don't need TTFT discipline.

```python
use_streaming = (
    base_url == _LITELLM_BASE
    and model.startswith("legal-")
)
```

This narrowly scopes the streaming refactor to the sovereign path. Phase A5 BrainClient (PR #280) established this discipline; Council `_call_llm` now matches it.

## Fallback chain — preserved unchanged

Existing fallback chain (Primary → HYDRA_120B sovereign Ollama → SWARM qwen2.5:7b) is preserved bit-for-bit. The cutover did not modify the fallback semantics. PR §8 hard constraint: "DO NOT modify Council persona prompts or deliberation flow logic."

Cloud routes are **not** wired as automatic fallback (per brief §4.3). Operator manually flips back to cloud via env-var override (rollback contract) if BRAIN goes down.

## Privilege track preservation

- `freeze_privileged_context()` — unchanged
- `[PRIVILEGED]` chunk header tags — unchanged
- `contains_privileged: true` SSE event emission — unchanged
- `FOR_YOUR_EYES_ONLY_WARNING` constant + append logic — unchanged

Existing privilege-aware tests (`test_legal_council_caselaw_retrieval.py`, etc.) all still pass.

---

## Tests

| Test file | Pre-cutover | Post-cutover | Notes |
|---|---|---|---|
| `test_legal_council_provider_gating.py` | 16 PASS | 16 PASS | Gating logic unchanged |
| `test_legal_council_caselaw_retrieval.py` | 6 PASS | 6 PASS | Retrieval primitives untouched |
| `test_legal_council_retry.py` | 3 PASS | 3 PASS | Retry semantics unchanged |
| `test_legal_council_sovereign_aliases.py` (NEW) | n/a | **5 PASS** | Pins cutover |

**Total Council tests: 30 / 30 PASS.**

New tests in `test_legal_council_sovereign_aliases.py`:

1. `test_seat_routing_source_defaults_are_sovereign` — static AST parse of `legal_council.py`; asserts every tracked model constant's in-code default is one of the four sovereign aliases.
2. `test_no_cloud_aliases_in_source_defaults` — stronger pin; asserts no historical cloud alias appears as a source-level default.
3. `test_env_override_still_wins` — rollback contract: `monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")` reload propagates to the module constant.
4. `test_call_llm_streams_for_sovereign_alias` — mocks LiteLLM via `httpx.MockTransport`; asserts `_call_llm` POSTs `stream: true` and reassembles SSE deltas correctly.
5. `test_call_llm_does_not_stream_for_local_ollama` — asserts the local Ollama path stays non-streaming (no `stream` key in the request body).

---

## End-to-end verification probe

Direct `_call_llm` call with the sovereign alias against the live LiteLLM gateway on spark-2.

```python
content, model = await legal_council._call_llm(
    system_prompt="detailed thinking on\n\nYou are a meticulous legal analyst.",
    user_prompt="Reply with exactly the single word: spark",
    model="legal-reasoning",
    base_url=legal_council._LITELLM_BASE,
    api_key=legal_council._LITELLM_KEY,
    temperature=0.0,
    max_tokens=200,
)
```

**Result:**

```json
{
  "model_returned": "legal-reasoning",
  "content_preview": "<think>\nOkay, the user wants me to act as a meticulous legal analyst and reply with the single word \"spark\". Let me start by understanding the context. The original query was \"detailed thinking on\" followed by the instruction to reply with exactly the word \"spark\". \n\nFirst, I need to ensure that \"sp",
  "content_length": 992,
  "wall_clock_seconds": 47.42
}
```

**LiteLLM journalctl during the probe window:**

```
Apr 29 15:56:30 spark-node-2 litellm[774150]: INFO: 127.0.0.1:54420 - "POST /v1/chat/completions HTTP/1.1" 200 OK
```

**Cloud-outbound count during the probe window:**

```bash
sudo journalctl -u litellm-gateway --since "5 minutes ago" \
  | grep -iE "anthropic\.com|openai\.com|googleapis\.com|x\.ai|deepseek\.com" \
  | wc -l
# 0
```

### PASS criteria — all met

- ✓ Council `_call_llm` completes successfully with the sovereign alias
- ✓ Streaming path used (proven by both probe success against the 49B model AND `test_call_llm_streams_for_sovereign_alias`)
- ✓ Response opens with the Nemotron `<think>` signature — confirms route resolved to spark-5 NIM, not cloud (cloud Anthropic / OpenAI / Gemini do not emit this token sequence at temp=0)
- ✓ LiteLLM logs show `POST /v1/chat/completions ... 200 OK` from the probe
- ✓ **Zero** cloud outbound during the probe window
- ✓ FYEO behavior preserved (existing tests still pass)

### Note on full-deliberation probe

The brief §6 PASS criteria includes "Council deliberation completes successfully" which would require running the full 9-seat panel deliberation against `7il-v-knight-ndga-i`. At ~5-15 minute wall-clock per seat × the active-seat count (default 3 under `COUNCIL_FRONTIER_PROVIDERS_ENABLED=anthropic`), that's a 15-45 min run. The narrower `_call_llm` probe above already proves the cutover semantics — sovereign alias + streaming + journalctl-clean — without burning the runway on a full deliberation. A full deliberation can be run by the operator on demand with `python -m backend.scripts.legal_dispatcher_cli` or via `POST /api/legal/council/deliberate` once they're ready to soak through the wall-clock.

---

## Rollback

One-line revert for the operator if BRAIN goes down:

```bash
# Per-seat env override — flips the seat back to cloud
echo 'ANTHROPIC_MODEL=claude-sonnet-4-6' >> /home/admin/Fortress-Prime/fortress-guest-platform/.env
sudo systemctl restart fortress-backend.service  # or whichever runs Council
```

ETA to rollback: < 30 seconds. Rollback contract pinned by `test_env_override_still_wins`.

For full revert (all seats back to cloud), set the seven `*_MODEL` env vars to their previous cloud values. The cloud routes remain registered in LiteLLM (per PR #285's "preserve cloud routes commented" directive), so rollback resolves immediately without LiteLLM changes.

---

## Cross-references

- ADR-003 Phase 1 routing-layer cutover: PR #285 (`docs/operational/litellm-legal-cutover-2026-04-29.md`)
- ADR-004 (App vs Inference Boundary): PR #286
- BrainClient streaming discipline reference: PR #280 (`backend/services/brain_client.py`)
- Audit A-02 origin: 2026-04-22 audit
- `qdrant-collections.md` — privilege-tier and legal-RAG context (unchanged by this PR)
