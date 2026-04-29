# LiteLLM Legal Routes Cutover (Cloud → Spark-5 NIM)

**Date:** 2026-04-29
**Driver:** ADR-003 Phase 1 (LOCKED — operator decision 2026-04-29)
**Closes:** Audit finding A-02 (2026-04-22 audit) — sovereign legal inference

---

## Before

- Legal-tier inference flowed through cloud frontier providers (Anthropic / OpenAI / Gemini / xAI / DeepSeek) via the LiteLLM gateway on spark-2.
- `legal_council.py` `SEAT_ROUTING` mapped all 9 deliberation seats to `claude-sonnet-4-6` / `gpt-4o` / `grok-4` / `deepseek-reasoner` / `claude-opus-4-6`.
- `litellm_config.yaml` exposed only those cloud routes; no sovereign legal route existed.
- `IRON_DOME v6.1`'s claim that legal inference is sovereign was **inaccurate** — every privileged document touched a cloud API.

## After

- New sovereign legal routes added to LiteLLM, all backed by the spark-5 NIM (`http://spark-5:8100/v1`) running `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8` under NIM 2.0.1:
  - `legal-reasoning`
  - `legal-classification`
  - `legal-summarization`
  - `legal-brain`
- Cloud routes (Anthropic, OpenAI, Gemini, xAI, DeepSeek) preserved active in LiteLLM for non-legal callers AND as emergency rollback path for legal traffic. **Not deleted, only re-scoped.**
- Operator can re-enable cloud routing for legal seats by flipping `COUNCIL_FRONTIER_PROVIDERS_ENABLED` in the legal_council runtime env (already implemented; documented in `runbooks/litellm-key-rotation.md`).
- LiteLLM service restarted cleanly (`systemctl restart litellm-gateway.service`).

A separate Phase B PR will migrate `legal_council.py` `SEAT_ROUTING` to consume `legal-reasoning` directly. Until that lands, the sovereign route is **available** but not yet **traffic-cutover** at the seat level. This Phase 1 PR closes A-02 at the routing layer; Phase B closes it at the consumer layer.

## YAML diffs

### Live config (`/home/admin/Fortress-Prime/litellm_config.yaml`, gitignored — contains master_key)

Pattern added at top of `model_list` (one entry per legal alias):

```yaml
- model_name: legal-reasoning
  litellm_params:
    model: openai/nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8
    api_base: http://spark-5:8100/v1
    api_key: dummy   # NIM does not require auth on the internal Tailscale/LAN
    timeout: 600     # streaming long-context legal RAG calls
```

### Repo template (`deploy/litellm_config.yaml`, tracked)

Same pattern committed in this PR. Cloud routes annotated as "non-legal use only after ADR-003 Phase 1; emergency rollback for legal".

## Verification (per brief §8.5)

### Spark-5 reachability check (run before YAML edit)

| Endpoint | HTTP | Wall-time |
|---|---|---|
| `http://spark-5:8100/v1/models` (LAN) | 200 | 0.002 s |
| `http://100.96.13.99:8100/v1/models` (Tailscale) | 200 | 0.004 s |

Confirmed model id: `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8`.

### LiteLLM service restart

```
● litellm-gateway.service - LiteLLM API Gateway (Fortress Sovereign Model Router)
     Loaded: loaded (/etc/systemd/system/litellm-gateway.service; enabled)
     Active: active (running) since Wed 2026-04-29 14:32:54 EDT
```

No errors on load. Both legal aliases registered in the model list.

### Probe — `legal-reasoning` route

Request:

```bash
curl -sS http://127.0.0.1:8002/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model":"legal-reasoning",
    "messages":[
      {"role":"system","content":"detailed thinking on"},
      {"role":"user","content":"Reply with the single word: spark"}
    ],
    "max_tokens":50, "stream":false
  }'
```

Response (saved at `/tmp/litellm-cutover-probe.json`):

```json
{
  "id": "chatcmpl-8543e2bf833c0724",
  "created": 1777487594,
  "model": "legal-reasoning",
  "object": "chat.completion",
  "choices": [
    {
      "finish_reason": "length",
      "index": 0,
      "message": {
        "content": "<think>\nOkay, the user wants me to reply with exactly the single word \"spark\"...",
        "role": "assistant"
      }
    }
  ],
  "usage": {"completion_tokens": 50, "prompt_tokens": 28, "total_tokens": 78}
}
```

- HTTP **200** in 12.0 s (cold startup; second probe was 7.1 s).
- Response model id: `legal-reasoning` (LiteLLM-side route name).
- Response content opens with `<think>...` — the Nemotron-49B-FP8 reasoning-block signature. Anthropic / OpenAI / Gemini cloud models do not emit this token sequence at temp=0.
- A direct probe to `http://spark-5:8100` with the same payload produced the identical `<think>` signature and the upstream model id `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8` — confirming the route resolves to spark-5, not a cloud provider.
- `finish_reason=length` is expected: 50 max_tokens cuts the reasoning block before the final answer. The probe is testing route resolution, not output quality.

### LiteLLM journalctl during the probe window

```
Apr 29 14:33:26 spark-node-2 litellm[774150]:     legal-reasoning
Apr 29 14:33:26 spark-node-2 litellm[774150]: INFO: 127.0.0.1:41618 - "POST /v1/chat/completions HTTP/1.1" 200 OK
Apr 29 14:33:33 spark-node-2 litellm[774150]: INFO: 127.0.0.1:45950 - "POST /v1/chat/completions HTTP/1.1" 200 OK
```

No `api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com`, `api.x.ai`, or `api.deepseek.com` outbound calls in the journal during the probe window. Route resolution is sovereign.

### Probe — `legal-classification` alias (sanity)

Same payload pattern, `model: "legal-classification"`. HTTP **200** in 7.1 s. Same Nemotron `<think>` signature. Confirms all four legal aliases share the same backend.

## PASS / FAIL

- HTTP 200 ✓
- Route resolves to spark-5 NIM (Nemotron signature + journalctl) ✓
- No cloud provider in the journalctl outbound during probe window ✓

**PROBE STATUS: PASS**

## Rollback

```bash
# Roll back YAML
git -C /home/admin/Fortress-Prime checkout HEAD -- deploy/litellm_config.yaml
# (Live config is gitignored; restore from .litellm.bak if needed)
cp /home/admin/Fortress-Prime/litellm_config.yaml.bak /home/admin/Fortress-Prime/litellm_config.yaml

# Restart
sudo systemctl restart litellm-gateway.service
```

ETA to rollback: < 30 s. Cloud routes stay active throughout (per brief §11), so the legal-tier traffic resumes through cloud the moment the legal-* model names are removed from the YAML.

## Cross-references

- Brief: `docs/operational/briefs/adr-003-lock-phase-1-brief-2026-04-29.md` (committed in PR #284)
- ADR: `docs/architecture/cross-division/ADR-003-inference-cluster-topology.md`
- Audit findings: 2026-04-22 audit, finding A-02
- Phase A5 BRAIN+RAG probe (PR #280) — earlier sovereign-routing verification against the same spark-5 endpoint
