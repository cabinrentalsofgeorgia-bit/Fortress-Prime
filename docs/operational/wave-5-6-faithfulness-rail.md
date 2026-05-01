# Wave 5.6 — RAG Faithfulness Rail

**Date shipped:** 2026-05-01
**Stacks on:** Wave 5 (PRs #346 + #347)
**Brief:** `wave-5-6-faithfulness-rail-brief-2026-05-01.md` (operator brief, not committed)

## Purpose

Score generated brief sections against the retrieval packets that grounded
them, to detect ungrounded claims. Output feeds the v1 → v2 regen triage
window per master plan §3.3.

This rail is **additive**. It does not gate generation, does not block
sections, does not modify retrieval, does not change Wave 5 components.

## Architecture

```
       ┌─────────────────────────────────────────────────────────┐
       │  Wave 7 runner (track_a_case_i_runner.py)               │
       │                                                         │
       │   compose() runs all 10 sections                        │
       │   for sid, result in section_results.items():           │
       │     write section_*.md                                  │
       │     if --faithfulness-check and synthesis section:      │
       │       judge_result = faithfulness_judge.score(          │
       │         sid, result.content, retrieval_packet)          │
       │       persist judge_result → faithfulness/<sid>.json    │
       │   write run-report.md with faithfulness summary table   │
       └─────────────────────────────┬───────────────────────────┘
                                     │
                                     ▼
       ┌─────────────────────────────────────────────────────────┐
       │  faithfulness_judge.score(...)                          │
       │  (called directly via Python import; the FastAPI        │
       │   service is an alternative entry point for callers     │
       │   that prefer HTTP)                                     │
       │                                                         │
       │   → render JUDGE_PROMPT_TEMPLATE                        │
       │   → POST LiteLLM /v1/chat/completions                   │
       │     model=legal-faithfulness                            │
       │     response_format={type: "json_object"}               │
       │   → parse JSON; on parse-fail, retry once with stricter │
       │     prompt; on second fail, return {error: ..., raw}    │
       └─────────────────────────────┬───────────────────────────┘
                                     │
                                     ▼
       ┌─────────────────────────────────────────────────────────┐
       │  LiteLLM gateway 127.0.0.1:8002                         │
       │  legal-faithfulness alias (Wave 5.6 addition)           │
       │     model: openai/nemotron-3-super                      │
       │     api_base: http://10.10.10.3:8000/v1                 │
       │     temperature: 0.0, max_tokens: 2000                  │
       │     chat_template_kwargs: enable_thinking: false        │
       │     timeout: 600                                         │
       └─────────────────────────────────────────────────────────┘
```

## Why a dedicated `legal-faithfulness` alias

LiteLLM does not propagate `extra_body.chat_template_kwargs.enable_thinking`
overrides to vLLM (verified empirically against this gateway version
1.83.4). A request to `legal-reasoning` with thinking-off intent in
`extra_body` still gets the alias's baked `enable_thinking: true`, which
produces a thinking-style ramble that exhausts `max_tokens` before any JSON
output appears. The dedicated `legal-faithfulness` alias bakes
`enable_thinking: false` into the alias config, which IS forwarded.

## Components

- `backend/services/guardrails/faithfulness_judge.py` — judge logic + LiteLLM client
- `backend/services/guardrails/faithfulness_prompts.py` — versioned prompt template
- `backend/services/faithfulness_service/main.py` — FastAPI wrapper service (Option B)
- `deploy/systemd/spark-2/fortress-faithfulness.service` — systemd unit
- `track_a_case_i_runner.py` — `--faithfulness-check` flag + per-synthesis-section scoring
- `litellm_config.yaml` — `legal-faithfulness` alias

## Usage

### From the Wave 7 runner

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
.uv-venv/bin/python -m backend.scripts.track_a_case_i_runner --faithfulness-check
```

Output:
- `${RUN_DIR}/sections/<sid>.md` — section content (unchanged)
- `${RUN_DIR}/faithfulness/<sid>.json` — judge output per synthesis section
- `${RUN_DIR}/run-report.md` — summary table + flagged sections + top
  unsupported claims for operator triage
- `${RUN_DIR}/metrics/run-summary.json` — includes `faithfulness_check_enabled`
  and `faithfulness_results` keys

Mechanical sections (§1, §3, §6, §10) and the deterministic timeline (§2)
are skipped — no LLM-generated content to audit.

### Standalone (post-hoc on existing brief)

```python
import json
from backend.services.guardrails.faithfulness_judge import score

section_text = open("sections/section_05_key_defenses_identified.md").read()
packet = json.load(open("packet.json"))  # list of {source_id, text} dicts

result = score("section_05_key_defenses_identified", section_text, packet)
print(json.dumps(result, indent=2))
```

### As an HTTP service (Option B)

```bash
curl -fsS http://127.0.0.1:8201/v1/faithfulness/score \
  -H "Content-Type: application/json" \
  -d '{
    "section_id": "section_05",
    "generated_section": "...",
    "retrieval_packet": [{"source_id": "doc1.pdf", "text": "..."}]
  }' | jq .
```

## Output schema

```json
{
  "section_id": "<echo from input>",
  "grounded_claims_count": 12,
  "unsupported_claims": [
    {"claim": "<<=240 char>", "reason": "<<=160 char>"}
  ],
  "partial_support_claims": [
    {"claim": "<<=240 char>", "supported_part": "<<=160 char>", "unsupported_part": "<<=160 char>"}
  ],
  "summary": "<<=200 char overall assessment>"
}
```

Output is bounded: at most 10 unsupported_claims and 10 partial_support_claims
entries (the highest-impact ones if more exist), with per-string length caps.
This keeps the response compact enough to fit within `max_tokens: 2000` even
for sections with many claims.

## Threshold guidance for v2 regen triage

Informational only. Operator makes final triage call at v1 review per
master plan §3.3. The runner's auto-generated `run-report.md` flags
sections meeting either of:

- `unsupported_claims` length > 3
- `partial_support_claims` length > 5

…as candidates for v2 regen. Adjust thresholds in `_write_faithfulness_run_report`
if operator triage signals it's noisy.

## Performance

Wave 5.6 brief §6.4 timing probe on Track A v3 §5 (Key Defenses, 7762 chars
section, 30-chunk packet, 28KB):

| Metric | Value |
|---|---|
| Generation wall (compose §5) | 83s |
| Faithfulness judge wall | 98s |
| Faithfulness wall as % of generation | 118% |
| Brief §2.6 strict bar | 30% |

The 118% per-section judge wall **exceeds** §2.6's 30% strict bar but
the rail is opt-in (default `--faithfulness-check=False`) and runs
post-assembly (sections aren't slowed individually — total run wall
increases when the flag is on). The brief's intended use (Saturday Block B
v1 → v2 regen triage per master plan §3.2) is a deliberate triage run, not
routine. The architecture preserves §2.6's intent ("don't make routine
runs slower") even though the literal wall ratio is exceeded.

## Smoke results (committed JSONs)

| Smoke | Grounded | Unsupported | Wall | Signal |
|---|---|---|---|---|
| Positive (§5 + real Case I packet) | 12 | 5 | 98s | grounded ≫ unsupported ✓ |
| Negative (§5 + synthetic wrong packet) | 0 | 10 (capped) | 64s | grounded → 0 ✓ |

Strong signal separation. The negative-control packet contained six chunks
from totally unrelated cases (patent, Title VII, software license, FTCA,
antitrust class action, securities fraud); the §5 text was unchanged from
the positive smoke. The judge correctly returned `grounded_claims_count=0`
and surfaced 10 unsupported claims — the maximum allowed by the prompt's
bound — confirming the rail detects ungroundedness.

§2.5 hard stop (non-JSON output > 20%): 0/2 smokes produced non-JSON.
§2.7 hard stop (runner needs invasive changes): not fired — argparse + a
post-compose conditional was sufficient.

## Failure modes

- **Judge returns prose instead of JSON**: `_parse_judge_output` strips
  markdown fences and finds the first `{` in the response. On parse
  failure, retries once with a stricter prompt; on second failure returns
  `{"error": "parse_failed", "raw": <output>}`. Section is not blocked,
  just unscored.
- **Frontier dies during scoring**: HTTP error captured in
  `{"error": "http_error", "exception": "..."}`. Section is not scored;
  runner continues other sections.
- **`legal-faithfulness` alias missing from LiteLLM**: judge call returns
  HTTP error from gateway. Operator runbook to install/restart gateway is
  in `docs/operational/runbooks/` (Wave 5 baseline).
- **`max_tokens` exhaustion mid-JSON**: bounded prompt keeps the response
  compact enough to fit at 2000 tokens; if a future section produces output
  that doesn't fit, the parser's first attempt fails (truncated JSON), the
  retry uses a stricter prompt and typically succeeds with shorter output.

## Limitations

- **Single judge** — no consensus. Multi-judge ensemble is Q3 work.
- **No claim-level chunk back-reference** — the judge does not surface
  which specific chunk supports each claim. Q3 enhancement.
- **Doctrinal expansions on settled law** sometimes register as
  UNSUPPORTED even when accurate. This is correct behavior — the rail
  classifies against the packet, not against the world. Operator triages.
- **Recall on long packets** — across 30 chunks, the judge occasionally
  misses content that IS in the packet (observed in the §5 smoke for the
  $305,281.87 figure: the judge said "not in packet" but it was in chunk 7).
  The bounded output may amplify this. Q3: consider chunk-level retrieval
  back-citation (judge returns `supported_by_chunk_index`).
- **Phase B v0.1 retrieval is global, not per-section** — every synthesis
  section grounds against the same `packet.work_product_chunk_texts +
  packet.privileged_chunk_texts`. The faithfulness rail therefore scores
  every section against the same packet. When v0.2 introduces per-section
  retrieval, the rail's runner-side packet construction will need
  adjustment.

## Watchlist

- **LiteLLM extra_body propagation** — re-test on each LiteLLM upgrade.
  If a future version forwards `extra_body.chat_template_kwargs` cleanly,
  the dedicated `legal-faithfulness` alias becomes optional and could be
  removed in favor of per-call overrides on `legal-reasoning`.
- **Judge model upgrade** — when a smaller, fast structured-output model
  is available (e.g., Nemotron-3-Reasoning-4B variants), evaluate as a
  drop-in for the judge to reduce wall.
- **Total run wall with --faithfulness-check** — measured impact will
  inform whether the operator runs the flag on every Saturday Block B or
  only on flagged candidates.
