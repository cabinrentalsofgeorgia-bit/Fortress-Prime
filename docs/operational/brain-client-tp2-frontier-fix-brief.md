# Phase B BrainClient — TP=2 Frontier Compatibility Fix (Path X)

**Target:** Claude Code on spark-2
**Branch:** `fix/brain-client-tp2-frontier-compatibility-2026-04-30`
**Date:** 2026-04-30
**Operator:** Gary Knight
**Mode:** END-TO-END AUTONOMOUS. Hard stops only on real break conditions.
**Driver:** Track A run (PR #323) surfaced three structural defects in `fortress-guest-platform/backend/services/brain_client.py` against the new TP=2 frontier with nemotron_v3 reasoning parser. Path X chosen over Path Y: fix BrainClient surgically; preserve v0.1 architecture; unblock Case II briefing. Path Y (retire BrainClient, route via LiteLLM) is Wave 6 NAT migration work, not this PR.
**Stacks on:**
- PR #322 (Phase 9 alias surgery + BRAIN retirement, merged)
- PR #323 (Track A empirical evidence, draft, awaiting operator promotion)
- PR #321 (TP=2 deployment evidence, soak in progress to 2026-05-14)
- vLLM stream sample at `docs/operational/track-a-evidence-2026-04-30/vllm-stream-sample-delta-reasoning.txt`
**Resolves:** P1 follow-up issue from Track A — Phase B BrainClient TP=2 compatibility

---

## 1. Mission

Fix three structural defects in `BrainClient` so it produces non-empty content against the TP=2 frontier endpoint with nemotron_v3 reasoning parser. Validate by reproducing Track A's failed sections and confirming `finish_reason=stop` with non-empty content. Do not migrate to LiteLLM (that's Wave 6). Do not change synthesizer logic. Targeted file edits only.

---

## 2. Hard stops (the ONLY conditions that halt execution)

1. **`brain_client.py` not found** at the path Track A identified (`fortress-guest-platform/backend/services/brain_client.py`).
2. **vLLM stream sample evidence file missing** at `docs/operational/track-a-evidence-2026-04-30/vllm-stream-sample-delta-reasoning.txt`. Need it to confirm wire format before changing parser.
3. **Frontier endpoint dead.** `curl /v1/health/ready` non-200 sustained >60s. Cannot validate fix without it.
4. **Tests fail with no clear path forward.** Existing tests catastrophically broken by the change with non-trivial fix scope.
5. **Fix introduces new defect detected during validation.** New regression in non-Track-A code paths.
6. **Soak halt event fires.** Cluster telling you to stop.
7. **Disk full.** <5GB free anywhere.

Everything else proceeds. Defaults documented; deviations land in final report.

---

## 3. Three defects (precise scope)

### Defect 1: Stream parser discards `delta.reasoning` chunks

**Evidence:** `docs/operational/track-a-evidence-2026-04-30/vllm-stream-sample-delta-reasoning.txt` (415 lines).

**Wire format confirmed:** vLLM nemotron_v3 parser emits two distinct delta channels per stream:

```
data: {..."choices":[{"delta":{"reasoning":"We"}}]}
data: {..."choices":[{"delta":{"reasoning":" need"}}]}
...
data: {..."choices":[{"delta":{"content":"## Section"}}]}
data: {..."choices":[{"delta":{"content":" 4"}}]}
```

Reasoning emits first (until reasoning trace completes), then content emits.

**Current `_stream()` behavior:** parses `delta.content` only. Reasoning chunks silently discarded. When max_tokens too low (Defect 2), reasoning fills the budget; content never starts; stream returns empty string.

**Fix:** parse both `delta.reasoning` and `delta.content`. Accumulate separately. Return both via the response object.

### Defect 2: Default `max_tokens=2000` below reasoning floor

**Evidence:** Phase 7 Section 5 smoke captured ~2,000-token reasoning traces on synthesis prompts. Track A's 5 failed sections all hit `finish_reason=length` at 2000.

**Fix:** raise default `max_tokens` for synthesis calls. Production-safe default 8000. Per-call override preserved.

**Why 8000 not 6000:** Nemotron-Super-120B reasoning + content on Section 4/5/9 (the deepest reasoning sections) can total 6,000-7,000 tokens. 8000 leaves headroom without being wasteful — Section 9 augmentation via LiteLLM used 5000 max_tokens and produced 4,578 bytes content with `finish_reason=stop`, so 8000 is conservative-safe across all section types.

### Defect 3: No reasoning_effort / thinking flag injection

**Evidence:** Phase 9 alias surgery defined per-alias profiles (`legal-reasoning` = `reasoning_effort: high`, `thinking: true`; `legal-summarization` = `reasoning_effort: low`, `thinking: false`). BrainClient has no constructor or per-call kwarg for these.

**Fix:** add constructor params + per-call override for:
- `reasoning_effort` (string: `low` / `medium` / `high`)
- `thinking` (bool, maps to `chat_template_kwargs.thinking`)

Both pass through to the request body's `extra_body` / appropriate keys per vLLM API.

---

## 4. Pre-flight (autonomous)

### 4.1 Branch + state

```bash
git fetch origin
git checkout origin/main
git checkout -b fix/brain-client-tp2-frontier-compatibility-2026-04-30
git status
git log origin/main..HEAD --oneline
```

### 4.2 Locate files

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  ls -la fortress-guest-platform/backend/services/brain_client.py
  ls -la docs/operational/track-a-evidence-2026-04-30/vllm-stream-sample-delta-reasoning.txt
  
  # Existing tests
  find . -path "*test*brain*" -name "*.py" 2>/dev/null | grep -v __pycache__ | head -10
  
  # Callers (we are NOT modifying these — just inventorying impact surface)
  grep -rn "from.*brain_client\|import.*BrainClient\|BrainClient(" \
    --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v ".git/" | grep -v test_
'
```

If `brain_client.py` missing: hard stop §2.1.
If evidence file missing: hard stop §2.2.

### 4.3 Read current BrainClient

```bash
ssh admin@192.168.0.100 'cat /home/admin/Fortress-Prime/fortress-guest-platform/backend/services/brain_client.py'
```

Surface inline:
- Constructor signature
- `_stream()` method
- Public method signatures (likely `complete()` or similar)
- Module-level defaults (`_DEFAULT_MODEL`, `_DEFAULT_MAX_TOKENS`, etc.)

### 4.4 Frontier health

```bash
ssh admin@192.168.0.100 '
  curl -fsS --max-time 10 http://10.10.10.3:8000/v1/health/ready
  curl -fsS --max-time 30 http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"legal-reasoning\", \"messages\": [{\"role\":\"user\",\"content\":\"PONG\"}], \"max_tokens\": 10}" \
    | jq -r ".choices[0].message.content"
'
```

200 + PONG → proceed. Otherwise hard stop §2.3.

---

## 5. The fix — surgical edits to `brain_client.py`

### 5.1 Edit 1: Constructor — add kwargs

Add to `__init__`:

```python
def __init__(
    self,
    base_url: str = _DEFAULT_BASE_URL,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
    timeout: float = 180.0,
    # NEW — Defect 3
    reasoning_effort: str | None = None,    # "low" | "medium" | "high"
    thinking: bool | None = None,            # maps to chat_template_kwargs.thinking
    default_max_tokens: int = 8000,          # NEW — Defect 2 (was 2000)
):
    # existing init body
    # ...
    self._reasoning_effort = reasoning_effort
    self._thinking = thinking
    self._default_max_tokens = default_max_tokens
```

Preserve all existing constructor params verbatim. Additions only.

### 5.2 Edit 2: Public completion method — wire kwargs through

Whichever method exposes the public API (likely `complete()`, `synthesize()`, or similar — surface in §4.3 read), add kwargs:

```python
def complete(
    self,
    prompt: str,
    *,
    max_tokens: int | None = None,
    temperature: float = 0.5,
    # NEW — Defect 3 per-call override
    reasoning_effort: str | None = None,
    thinking: bool | None = None,
    stream: bool = True,
):
    # Resolve effective values: per-call > constructor > None
    effective_max_tokens = max_tokens or self._default_max_tokens
    effective_reasoning_effort = reasoning_effort or self._reasoning_effort
    effective_thinking = thinking if thinking is not None else self._thinking
    
    # Build request body
    body = {
        "model": self._model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": effective_max_tokens,
        "temperature": temperature,
        "stream": stream,
    }
    
    # Inject reasoning controls if specified
    extra_body = {}
    if effective_reasoning_effort is not None:
        extra_body["reasoning_effort"] = effective_reasoning_effort
    chat_template_kwargs = {}
    if effective_thinking is not None:
        chat_template_kwargs["thinking"] = effective_thinking
    if chat_template_kwargs:
        extra_body["chat_template_kwargs"] = chat_template_kwargs
    if extra_body:
        body.update(extra_body)
    
    # ... rest of method
```

Preserve existing return shape. Add reasoning content as new attribute on return object (not as content; content stays content).

### 5.3 Edit 3: `_stream()` — handle delta.reasoning

Current behavior (per Track A evidence): only `delta.content` parsed. `delta.reasoning` discarded.

New behavior: parse both. Yield content as before (consumer compatibility preserved). Accumulate reasoning into a side channel exposed via the response object.

```python
async def _stream(self, response):
    """
    Yield content chunks. Accumulate reasoning chunks into self._last_reasoning.
    nemotron_v3 emits delta.reasoning before delta.content; both must be parsed.
    """
    self._last_reasoning = ""
    self._last_finish_reason = None
    
    async for line in response.aiter_lines():
        if not line or not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        
        choices = obj.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        finish = choice.get("finish_reason")
        if finish is not None:
            self._last_finish_reason = finish
        
        # Accumulate reasoning (do NOT yield — consumers expect content only)
        reasoning_chunk = delta.get("reasoning")
        if reasoning_chunk is not None:
            self._last_reasoning += reasoning_chunk
        
        # Yield content as before
        content_chunk = delta.get("content")
        if content_chunk is not None:
            yield content_chunk
```

Key behavior:
- Existing consumers (`async for chunk in client._stream(): response += chunk`) continue to receive content-only chunks. No consumer code change required.
- Reasoning accessible via `client._last_reasoning` after stream consumed.
- `finish_reason` accessible via `client._last_finish_reason` (likely already exposed; preserve).

### 5.4 Edit 4: Module-level default constant

```python
_DEFAULT_MAX_TOKENS = 8000   # was 2000 — Defect 2 fix
```

Or wherever the current `2000` literal lives — replace with `8000`. Surface what existed before in the §11 final report.

### 5.5 Edit 5: Surface reasoning + finish_reason on synchronous (non-stream) path

If BrainClient has a `stream=False` code path (likely yes — Section 9 augmentation used a non-streaming pattern), parse `choices[0].message.reasoning` and `choices[0].message.content` separately. Same accumulator pattern.

```python
if not stream:
    obj = response.json()
    msg = obj["choices"][0].get("message", {})
    self._last_reasoning = msg.get("reasoning", "")
    self._last_finish_reason = obj["choices"][0].get("finish_reason")
    return msg.get("content", "")
```

---

## 6. Tests

### 6.1 Existing tests

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime/fortress-guest-platform
  
  # Run only brain_client-related tests pre-fix to establish baseline
  source .venv/bin/activate 2>/dev/null || true
  python -m pytest backend/tests/ -k "brain" -v 2>&1 | tee /tmp/brain-tests-pre-fix.log
'
```

Surface count: pre-fix passing/failing.

### 6.2 New test cases

Add to `backend/tests/test_brain_client.py` (create if not exists):

```python
import pytest
from unittest.mock import AsyncMock, patch
import json

from backend.services.brain_client import BrainClient


def test_brain_client_default_max_tokens_is_8000():
    """Defect 2 regression guard."""
    client = BrainClient()
    assert client._default_max_tokens == 8000


def test_brain_client_constructor_accepts_reasoning_kwargs():
    """Defect 3 — kwargs accepted at construction."""
    client = BrainClient(
        reasoning_effort="high",
        thinking=True,
    )
    assert client._reasoning_effort == "high"
    assert client._thinking is True


def test_brain_client_complete_passes_reasoning_effort():
    """Defect 3 — kwargs reach request body."""
    client = BrainClient(reasoning_effort="high", thinking=True)
    
    captured_body = {}
    
    async def fake_post(url, json=None, **kw):
        captured_body.update(json)
        # Return a non-streaming mock
        ...
    
    # Invoke complete() with mocked transport; assert extra_body in captured
    # Implementation depends on how BrainClient calls httpx
    ...


def test_stream_parses_delta_reasoning_separately():
    """Defect 1 — reasoning chunks accumulated, not discarded."""
    client = BrainClient()
    
    # Construct a fake stream response with the nemotron_v3 wire format
    fake_lines = [
        'data: {"choices":[{"delta":{"reasoning":"We"}}]}',
        'data: {"choices":[{"delta":{"reasoning":" need"}}]}',
        'data: {"choices":[{"delta":{"content":"## Section"}}]}',
        'data: {"choices":[{"delta":{"content":" 4"},"finish_reason":"stop"}]}',
        'data: [DONE]',
    ]
    
    # Mock response.aiter_lines to yield these
    # Consume the stream; assert content yielded = "## Section 4"
    # Assert client._last_reasoning == "We need"
    # Assert client._last_finish_reason == "stop"
    ...


def test_stream_backward_compatible_yield_shape():
    """Defect 1 — existing consumers unchanged."""
    client = BrainClient()
    
    # Same fake stream
    # Use the existing consumer pattern: response = ""; async for chunk in client._stream(...): response += chunk
    # Assert response == "## Section 4"  (content only, not "We need## Section 4")
    ...
```

Run new + existing tests post-fix:

```bash
python -m pytest backend/tests/ -k "brain" -v 2>&1 | tee /tmp/brain-tests-post-fix.log
```

If existing tests fail post-fix that didn't fail pre-fix: investigate. If unfixable in a clean way: hard stop §2.4.

---

## 7. Reproduce Track A failure → confirm fix

This is the empirical proof.

### 7.1 Pre-fix repro (sanity — should fail same as Track A)

If the runner script from Track A is committed (`fortress-guest-platform/backend/scripts/track_a_case_i_runner.py`), use it. Otherwise build a minimal repro:

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  source fortress-guest-platform/.venv/bin/activate 2>/dev/null || true
  
  cat > /tmp/brain-client-repro.py <<EOF
import asyncio
from backend.services.brain_client import BrainClient

async def main():
    # Use the new TP=2 frontier
    client = BrainClient(
        base_url="http://10.10.10.3:8000",
        model="nemotron-3-super",
    )
    
    # The kind of synthesis prompt that failed in Track A — long context, deep reasoning ask
    prompt = "Analyze the following claims under Georgia law. " * 200 + " What defenses are strongest?"
    
    # Existing complete() pattern
    result = await client.complete(prompt)
    print(f"CONTENT_LEN={len(result)}")
    print(f"REASONING_LEN={len(getattr(client, \"_last_reasoning\", \"\"))}")
    print(f"FINISH={getattr(client, \"_last_finish_reason\", None)}")

asyncio.run(main())
EOF
  
  cd fortress-guest-platform
  python /tmp/brain-client-repro.py
'
```

**Pre-fix expected:** `CONTENT_LEN=0`, `FINISH=length`. (Reasoning length may not print pre-fix — attribute does not exist.)

If pre-fix run shows `CONTENT_LEN > 0` somehow (e.g., short prompt that finishes within 2000 tokens): use Track A's actual Section 5 prompt, which is the real-world failing case.

### 7.2 Apply the fix

Edits per §5.

### 7.3 Post-fix repro

Same script. Now expect:
- `CONTENT_LEN > 1000` (Section 9 augmentation produced 4,578 — synthesis sections similar order of magnitude)
- `REASONING_LEN > 1000`
- `FINISH=stop`

Surface inline. This is the fix proven empirically.

### 7.4 With explicit reasoning controls

```bash
# Add to repro:
client_high = BrainClient(
    base_url="http://10.10.10.3:8000",
    model="nemotron-3-super",
    reasoning_effort="high",
    thinking=True,
)
result_high = await client_high.complete(prompt)

client_low = BrainClient(
    base_url="http://10.10.10.3:8000",
    model="nemotron-3-super",
    reasoning_effort="low",
    thinking=False,
)
result_low = await client_low.complete(prompt)

# Compare reasoning lengths — high should produce longer reasoning trace
```

If `len(reasoning_high) > len(reasoning_low)` significantly: Defect 3 fix verified — reasoning_effort actually changes behavior at the model.

If they're equal: vLLM build may not honor `reasoning_effort` extra_body kwarg. Document the finding; the constructor wiring is still correct (frontier may need newer vLLM build to act on it). Don't halt — the kwarg infrastructure is in place; activation depends on vLLM features.

---

## 8. Track A re-run (the real proof)

After repro confirms fix at the unit level, run Track A's failed sections through the real orchestrator path. Don't run all 10 sections — run just the 5 that failed (2, 4, 5, 7, 8) to validate orchestrator integration.

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  
  # Re-invoke the Track A runner against Case I, but only synthesis sections
  python -m backend.scripts.track_a_case_i_runner \
    --case-slug 7il-v-knight-ndga-i \
    --sections 2,4,5,7,8 \
    --output-dir /tmp/brain-fix-validation-$(date +%Y%m%dT%H%M%SZ) \
    2>&1 | tee /tmp/brain-fix-track-a-rerun.log
'
```

If runner doesn't accept `--sections` filter, run full 10-section pipeline; just inspect the previously-failed sections in output.

**Expected:** all 5 synthesis sections produce non-empty content with `finish_reason=stop`. Citation density should now be measurable; format compliance per Phase 7 smoke (no first-person bleed, no `<think>` leakage in content).

If any of the 5 still fail: Defect set wasn't complete. Surface, halt, do NOT modify further. File new issue.

---

## 9. PR

### 9.1 Files

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  git status
  
  # Expected modifications:
  #   fortress-guest-platform/backend/services/brain_client.py
  #   fortress-guest-platform/backend/tests/test_brain_client.py (new or modified)
  #   docs/operational/brain-client-tp2-fix-2026-04-30.md (this brief, copy)
  #   docs/operational/brain-client-fix-validation-2026-04-30.md (run report)
'
```

Validation report content:

```markdown
# BrainClient TP=2 Fix — Validation Report

**Date:** 2026-04-30
**Driver:** Path X fix for Track A (PR #323) BrainClient defects

## Pre-fix repro
- CONTENT_LEN: 0
- FINISH: length
- (Track A reproduced)

## Post-fix repro
- CONTENT_LEN: <actual>
- REASONING_LEN: <actual>
- FINISH: stop

## reasoning_effort verification
- high: <reasoning_len>
- low: <reasoning_len>
- Delta: <observation>

## Track A re-run (sections 2/4/5/7/8 only)
- Section 2: <tokens>, <cites>, finish=<finish>
- Section 4: <tokens>, <cites>, finish=<finish>
- Section 5: <tokens>, <cites>, finish=<finish>
- Section 7: <tokens>, <cites>, finish=<finish>
- Section 8: <tokens>, <cites>, finish=<finish>

## Test results
- Pre-fix: <passing>/<total>
- Post-fix: <passing>/<total>
- New tests: <count>

## Defect status
- Defect 1 (delta.reasoning parsing): FIXED + validated
- Defect 2 (max_tokens default): FIXED + validated
- Defect 3 (reasoning_effort/thinking kwargs): FIXED + wiring validated; activation depends on vLLM build features
```

### 9.2 Commit + push + PR

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  git add fortress-guest-platform/backend/services/brain_client.py
  git add fortress-guest-platform/backend/tests/test_brain_client.py
  git add docs/operational/brain-client-tp2-fix-2026-04-30.md
  git add docs/operational/brain-client-fix-validation-2026-04-30.md
  
  git commit -m "fix(brain-client): TP=2 frontier compatibility (3 defects)

Defect 1: _stream() now parses delta.reasoning chunks alongside
delta.content. Reasoning accumulated to client._last_reasoning;
content yielded as before (backward-compatible).

Defect 2: Default max_tokens raised from 2000 to 8000. Track A
synthesis sections hit length=2000 with reasoning-only output
(content never started emitting). 8000 leaves headroom for
deepest reasoning + content on Sections 4/5/9.

Defect 3: Constructor + per-call kwargs reasoning_effort and
thinking added. Pass through to request body extra_body /
chat_template_kwargs per vLLM nemotron_v3 API.

Validation: Track A failed-sections re-run on real orchestrator
path produces non-empty content with finish_reason=stop on all
5 previously-failing synthesis sections.

Resolves: P1 follow-up from PR #323 Track A evidence.
Path X (surgical fix) chosen over Path Y (LiteLLM migration).
Path Y deferred to Wave 6 NAT migration.
"
  
  git push -u origin fix/brain-client-tp2-frontier-compatibility-2026-04-30
  
  gh pr create \
    --title "fix(brain-client): TP=2 frontier compatibility (3 defects, Path X)" \
    --body-file docs/operational/brain-client-fix-validation-2026-04-30.md \
    --draft
'
```

PR opens as draft. Operator promotes to ready after reviewing diff + validation report.

---

## 10. Final report (auto-surface)

1. **Pre-flight summary**
   - Branch cut, files located, frontier health 200, evidence file present

2. **Pre-fix BrainClient state**
   - Constructor signature
   - `_stream()` behavior summary
   - Default max_tokens value
   - Caller surface count

3. **Pre-fix repro**
   - CONTENT_LEN, FINISH, full repro script output

4. **Edits applied**
   - File diff stats
   - Line-level changes per defect

5. **Post-fix unit test results**
   - Pre-fix: X passing / Y failing
   - Post-fix: X passing / Y failing
   - New tests added: Z

6. **Post-fix repro**
   - CONTENT_LEN, REASONING_LEN, FINISH

7. **reasoning_effort behavior validation**
   - high reasoning length, low reasoning length, delta

8. **Track A re-run on real orchestrator**
   - Per-section: tokens, cites, finish_reason
   - All 5 previously-failing sections now content-producing? Y/N

9. **Soak impact**
   - Endpoint health throughout
   - No halt triggers fired

10. **PR**
    - Branch
    - PR number + URL
    - Files modified (3 expected)

11. **Defect closure**
    - Defect 1: closed/open
    - Defect 2: closed/open
    - Defect 3: closed/open (note vLLM activation dependency)

12. **What this unblocks**
    - Phase B v0.1 synthesis works end-to-end against TP=2 frontier
    - Track A full re-run can produce a real v3 brief
    - Case II briefing path is unblocked on existing orchestrator architecture
    - Path Y (Wave 6 NAT migration) remains the strategic endgame; not blocked, not urgent

---

## 11. Constraints

- Branches from `origin/main` only.
- Single Claude Code session at a time on the cluster.
- Never `--admin`, never self-merge, never force-push main.
- Modify ONLY:
  - `fortress-guest-platform/backend/services/brain_client.py` (the fix)
  - `fortress-guest-platform/backend/tests/test_brain_client.py` (new/extended tests)
  - `docs/operational/brain-client-*.md` (this brief + validation report)
- DO NOT touch:
  - Synthesizer prompt logic
  - case_briefing_compose.py orchestrator
  - Phase B runner script
  - LiteLLM config
  - Frontier endpoint
  - Any other service
- DO NOT migrate to LiteLLM in this PR — that's Path Y / Wave 6.
- DO NOT halt for soft conditions. Hard stops in §2 only.
- Backward compatibility on `_stream()` is non-negotiable: existing content-only consumers continue to work.

---

## 12. Wall time budget

- Pre-flight + read code: 5-10 min
- Apply edits per §5: 10-15 min
- Add + run unit tests: 15-20 min
- Pre-fix + post-fix repro: 10-15 min
- Track A re-run on 5 sections: ~15-20 min (reasoning section call ~1-3 min each on Super-120B)
- Validation report + PR commit: 10 min

**Total: 1-1.5 hours wall time** for fix + validation + PR.

If Track A re-run reveals additional defects: STOP, surface, do not auto-iterate. File new issue.

---

End of brief.
