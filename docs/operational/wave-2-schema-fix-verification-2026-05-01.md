# Wave 2 Schema-Fix Verification — Step 2 of 4

**Date:** 2026-05-01 (fix applied 2026-04-30 21:46 EDT, probes 21:48 EDT)
**Branch:** `fix/wave-2-litellm-schema-2026-05-01` (from `origin/main` at `cfb744e97`, PR #337 merge)
**Scope:** Step 2 of the Wave 2 4-PR sequence per brief §0.7. Schema fix applied to the live `/home/admin/Fortress-Prime/litellm_config.yaml`; durable verification record committed here. Live config is gitignored (`.gitignore` line 89, secrets); fix is recorded via the diff + verdict matrix below.

**Pairs with:** PR #337 (Wave 2 alias-surgery brief, §0.2 schema-fix scope on main as `cfb744e97`). This PR is the post-fix probe-on-the-wire verification.

---

## 1. What was applied to the live config

Live config: `/home/admin/Fortress-Prime/litellm_config.yaml` (gitignored).
Backup: `/home/admin/Fortress-Prime/litellm_config.yaml.bak.pre-schema-fix.20260430-214559` (rollback path open).

### 1.1 Per-alias schema diff (verbatim)

```diff
@@ legal-reasoning @@
-      extra_body:
-        reasoning_effort: high
-        chat_template_kwargs:
-          thinking: true
+      chat_template_kwargs:
+        enable_thinking: true
+        low_effort: false
+        force_nonempty_content: true

@@ legal-drafting @@
-      extra_body:
-        reasoning_effort: medium
-        chat_template_kwargs:
-          thinking: true
+      # Note: medium-effort middle-ground intent not engageable on this
+      # frontier (no --reasoning-config). legal-drafting defaults to full
+      # reasoning (same as legal-reasoning) per brief §0.2 deferral.
+      chat_template_kwargs:
+        enable_thinking: true
+        low_effort: false
+        force_nonempty_content: true

@@ legal-summarization @@
-      extra_body:
-        reasoning_effort: low
-        chat_template_kwargs:
-          thinking: false
+      # enable_thinking=false suppresses reasoning entirely per chat
+      # template; low_effort omitted (not applicable when thinking off).
+      chat_template_kwargs:
+        enable_thinking: false
+        force_nonempty_content: true

@@ legal-brain (transitional, mirrors legal-reasoning) @@
-      extra_body:
-        reasoning_effort: high
-        chat_template_kwargs:
-          thinking: true
+      chat_template_kwargs:
+        enable_thinking: true
+        low_effort: false
+        force_nonempty_content: true

@@ legal-classification (transitional, mirrors legal-summarization) @@
-      extra_body:
-        reasoning_effort: low
-        chat_template_kwargs:
-          thinking: false
+      chat_template_kwargs:
+        enable_thinking: false
+        force_nonempty_content: true
```

Sampling fields (`max_tokens`, `temperature`, `top_p`, `timeout`) unchanged on all five aliases per brief §0.3 — sampling alignment is a separate decision out of this PR's scope.

`legal-embed` entry untouched (different model, different schema).
Cloud aliases (`claude-sonnet-4-6`, `claude-opus-4-6`, `gpt-4o`, `grok-4`, `gemini-2.5-pro`, `deepseek-chat`, `deepseek-reasoner`) untouched.

### 1.2 Per-alias post-fix configuration

| Alias | enable_thinking | low_effort | force_nonempty_content | Sampling (unchanged) |
|---|---|---|---|---|
| legal-reasoning | true | false | true | max_tokens=6000, T=0.3, top_p=0.95, timeout=600 |
| legal-drafting | true | false | true | max_tokens=4000, T=0.5, top_p=0.95, timeout=600 |
| legal-summarization | **false** | (omitted) | true | max_tokens=2000, T=0.4, top_p=0.95, timeout=600 |
| legal-brain (transitional) | true | false | true | mirrors legal-reasoning |
| legal-classification (transitional) | false | (omitted) | true | mirrors legal-summarization |

### 1.3 Reload + alias registration

- `sudo systemctl restart litellm-gateway.service` issued at **2026-04-30 21:47:30 EDT**
- Gateway returned `active (running)` within 5 seconds, no errors in startup logs
- Memory: 297.7M (peak 298.2M) — comparable to pre-restart 321.4M
- Process PID: 366557 (was 1372307 pre-restart)
- All 13 model_list entries registered post-reload (6 legal-* + 7 cloud)

---

## 2. Step 3 verdict matrix — post-fix probes (read-only, single curl per probe)

Three probes against the reloaded gateway. Same prompts as the §1.5 v3 kickoff probes that established the pre-fix DEFECT verdict.

| Probe | Pre-fix (PR #337 §0.1 baseline) | Post-fix (this PR) | Status |
|---|---|---|---|
| `legal-summarization` `reasoning_content` present | **YES (105 chars)** — control silently dropped | **NO (0 chars)** — control reached model, response is direct content | ✓ **PASS** |
| `legal-reasoning` `reasoning_content` present | YES (36 chars) | YES (105 chars) | ✓ **PASS** |
| Differentiation: legal-reasoning vs legal-summarization | None (both reasoned) | reasoning=105 vs **0** | ✓ **PASS** |
| `legal-drafting` non-trivial prompt | not previously tested | content=203, reasoning=209, finish=stop, valid drafted email | ✓ **PASS** |
| Gateway alias registration | 6 aliases | 6 aliases (legal-reasoning, legal-drafting, legal-summarization, legal-brain, legal-classification, legal-embed) | ✓ **PASS** |
| Frontier `/health` 200 throughout | 200 | 200 | ✓ **PASS** |
| Zero cloud outbound during probes | 0 | **0** | ✓ **PASS** |

### 2.1 Headline result

`legal-summarization` pre-fix probe produced 105 chars of `reasoning_content` despite the YAML's `thinking=false` config (per PR #337 §0.1 layer-attribution). Post-fix probe with `enable_thinking=false` at top level produced **0 chars of reasoning_content** — 14 completion tokens vs 47 pre-fix. Wire-level differentiation now reaches the model.

### 2.2 Probe artifacts (in /tmp, ephemeral)

```
/tmp/post-fix-probe-legal-summarization-20260501T014807Z.json
/tmp/post-fix-probe-legal-reasoning-20260501T014810Z.json
/tmp/post-fix-probe-legal-drafting-20260501T014812Z.json
```

Sample probe response (legal-summarization):

```json
{
  "model": "legal-summarization",
  "choices": [{
    "finish_reason": "stop",
    "message": {
      "role": "assistant",
      "content": "Water boils at 100°C at sea level.",
      "reasoning_content": null
    }
  }],
  "usage": {"completion_tokens": 14, "prompt_tokens": 38, "total_tokens": 52}
}
```

---

## 3. Layer-attribution closure

PR #337 §0.1 documented two independently-sufficient failure modes that produced the pre-fix DEFECT:

1. **LiteLLM `extra_body` silently dropped at gateway** — wrapped fields not unwrapped to top-level
2. **Chat-template key mismatch** — YAML used `thinking`, chat template defines `enable_thinking`

The schema fix addresses **both** layers simultaneously:
- Removed `extra_body` wrapper → fields placed at top-level (resolves #1 if it was the cause)
- Renamed `thinking` → `enable_thinking` (resolves #2 regardless)
- Dropped inert `reasoning_effort` (defensive cleanup, was never load-bearing)

Whether layer #1 or #2 (or both) was the proximate cause was untestable from response-shape alone (PR #337 §0.1 caveat). Now that the fix is in and the wire-level effect is correct, layer attribution is moot — the fix is empirically validated.

---

## 4. What this PR does NOT do

- Does not change sampling defaults (`temperature`, `top_p`, `max_tokens`) — per brief §0.3, separate decision
- Does not sync `deploy/litellm_config.yaml` template — sequence step 3 (separate PR)
- Does not formalize BRAIN-49B retirement or ADR-007 acceptance — sequence step 4 (separate PR)
- Does not modify any code (BrainClient, synthesizers, legal_council)
- Does not modify the frontier endpoint or any NIM service
- Does not enable `--reasoning-config` on the frontier (separate ticket — required to engage `thinking_token_budget` for the deferred medium-effort middle-ground)
- Does not amend the live config in this commit (live config is gitignored; the change has been applied to the live file directly per brief §0.2)

---

## 5. Rollback path

If post-merge issues surface against gateway behavior:

```sh
# On spark-2 as admin
cp /home/admin/Fortress-Prime/litellm_config.yaml.bak.pre-schema-fix.20260430-214559 \
   /home/admin/Fortress-Prime/litellm_config.yaml
sudo systemctl restart litellm-gateway.service
sudo systemctl is-active litellm-gateway.service  # expect: active
```

~5-second rollback to pre-fix state. Backup retained on spark-2 until operator confirms the fix can be considered durable.

---

## 6. Wave 2 sequence position

| # | PR | Status |
|---|---|---|
| 1 | Wave 2 alias-surgery brief | ✓ MERGED via PR #337 (`cfb744e97`) |
| 2 | **Schema fix (this PR)** | ratifies live-config edit + post-fix verdict |
| 3 | Template sync (`deploy/litellm_config.yaml`) | separate PR — fold-able into #2 per brief §0.7 if operator chooses; this PR keeps step 2 small per kickoff "could fold into #2" escape hatch |
| 4 | ADR-007 / Wave 2 ratification | BRAIN-49B retirement runbook commit, ADR acceptance, Council seat comment cleanup |

---

## 7. References

- PR #337 (Wave 2 alias-surgery brief, §0.2 schema-fix scope, layer-attribution caveat)
- PR #336 (Wave 1 close — EMBED post-restart verification — same doc-only ratification pattern)
- PR #335 (Wave 4 §5 — `force_nonempty_content` empirical proof)
- PR #331 (`reasoning_effort` deprecation + dual response-shape parsing in BrainClient)
- PR #330 (vLLM `extra_body` Probe E — silent-drop established for direct vLLM)
- `docs/research/nemotron-3-super-deep-research-2026-04-30.md` §1 (chat template variables)
- `docs/operational/phase-9-wave-2-alias-surgery-brief.md` (committed via PR #337)
- Kickoff: `/home/admin/claude-code-kickoff-wave-2-schema-fix-2026-05-01.md`

---

End of verification record.
