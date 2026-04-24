# LiteLLM Gateway Master Key Rotation Runbook

The LiteLLM gateway (`litellm-gateway.service`, `127.0.0.1:8002`) authenticates
every Fortress caller with a single shared bearer token. That token has **two
physical locations that must stay in lockstep**:

| Location | Consumer | Reload requirement |
|---|---|---|
| `general_settings.master_key` in `/home/admin/Fortress-Prime/litellm_config.yaml` | `litellm-gateway.service` (enforcer) | Gateway loads the value at process start. Edits to the YAML do **not** take effect until the service is restarted. |
| `LITELLM_MASTER_KEY=` in `fortress-guest-platform/.env` | `fortress-backend.service` Council seats (`backend/services/legal_council.py:101`) and all labeling/godhead pipelines | Backend loads the value at process start via pydantic-settings. Edits to `.env` do **not** take effect until `fortress-backend` is restarted. |

Any drift between the two values causes every Council seat (nine frontier
providers: Claude Sonnet/Opus, GPT-4o, Grok-4, Gemini 2.5, DeepSeek chat,
DeepSeek reasoner) and every labeling call to receive HTTP 400 from the
gateway. The backend's legal_council falls back silently to local Ollama
(`qwen2.5:7b` via the HYDRA_120B path), so deliberations continue to return
answers — but those answers are local model output masquerading as frontier
consensus, and they land in `llm_training_captures` as training fodder.

## Incident 2026-04-23 — the motivating example

- **2026-04-16 20:17:54 EDT** — `litellm_config.yaml` edited, `master_key`
  rotated from `sk-fortress-master-123` (dev) to a 60-character
  `sk-fortress-<52-hex>` value. No corresponding `.env` update.
- **2026-04-23 06:39:38 EDT** — `litellm-gateway.service` restarted
  (`ExecMainStartTimestamp`); the new key took effect in memory and began
  rejecting all callers carrying the old token. This is the true start of
  the broken window. No alarms fired.
- **2026-04-24 ~17:13 EDT** — detected via the A1 verification grep
  (`journalctl -u litellm-gateway | grep user_api_key_auth`), which surfaced
  72 matched failures over the preceding 24 hours: 36 gateway-side
  `user_api_key_auth.py:1176 ProxyException` entries plus 36 paired backend
  warnings (`legal_council: Primary LLM ... returned 400, falling back`,
  `labeling_pipeline: godhead_call_failed`). Zero successful 200 responses
  to `/v1/chat/completions` were recorded in either journal during the
  window.
- **Symptom masking** — Council deliberations completed successfully from
  the caller's perspective because every seat fell through to local
  `qwen2.5:7b`. The only visible trace was the `served_by_endpoint` field
  on capture rows all pointing at HYDRA/local Ollama endpoints instead of
  anthropic/openai/xai/deepseek/google.

## Detection

Run these on `spark-node-2`:

```bash
# Gateway-side auth failures (any 400 on /v1/chat/completions is almost
# always a key mismatch; real validation errors are rare on this path).
sudo journalctl -u litellm-gateway --since "1 hour ago" --no-pager \
  | grep -E 'user_api_key_auth|HTTP/1.1" (400|401|403)'

# Backend-side evidence (paired warnings from legal_council / labeling).
sudo journalctl -u fortress-backend --since "1 hour ago" --no-pager \
  | grep -iE "legal_council.*returned 400|godhead_call_failed|HYDRA"
```

If either command emits output, the two keys are out of sync.

A passive check that does **not** require a live request:

```bash
diff <(awk -F= '/^LITELLM_MASTER_KEY=/{print $2}' \
        /home/admin/Fortress-Prime/fortress-guest-platform/.env) \
     <(python3 -c 'import yaml; \
print(yaml.safe_load(open("/home/admin/Fortress-Prime/litellm_config.yaml"))["general_settings"]["master_key"])')
```

Empty diff = in sync. Any diff = rotation-in-progress or drift.

## Rotation protocol — the standing rule

Rotating the LiteLLM master key is a **single atomic operation across three
artefacts**. Do all three, in this order, without a pause that leaves the
services drifted:

1. **Edit `litellm_config.yaml`** — update `general_settings.master_key` to
   the new value. Do not restart the gateway yet; the old key is still the
   one callers hold.
2. **Edit `fortress-guest-platform/.env`** — update the `LITELLM_MASTER_KEY=`
   line to the same new value. Back up first with the project convention:
   `cp .env .env.bak.litellm-keysync-$(date +%Y%m%d_%H%M%S)`.
3. **Restart both services in order:**
   ```bash
   sudo systemctl restart litellm-gateway
   sudo systemctl restart fortress-backend
   ```
   Gateway first so there is never a moment where the backend is presenting
   the new token to a gateway that still holds the old one (that direction
   is the silent-failure direction; the reverse is a loud 400 that heals as
   soon as the backend restart completes).

4. **Verify with a live Council probe.** Send a single low-stakes
   deliberation (e.g. the standard Georgia insurance A1 prompt) through
   the Paperclip bridge and confirm:
   - `journalctl -u litellm-gateway` shows multiple HTTP 200 entries on
     `POST /v1/chat/completions`, not 400.
   - The resulting `llm_training_captures` row's
     `capture_metadata->>'served_by_endpoint'` resolves to real frontier
     providers (`anthropic`, `openai`, `xai`, `deepseek`, `google`), not
     HYDRA / local Ollama.

5. **If the probe still shows 400s** — the diagnosis is incomplete. Do not
   proceed to another rotation attempt. Check whether a third consumer
   holds the key (the systemd unit's optional `.litellm.env` drop-in, or
   `/etc/fortress/secrets.env` once the hardening step below ships).

## Future hardening

The `.env`/YAML split is the root cause of this incident. The target state
is a single source of truth:

- Move `LITELLM_MASTER_KEY` into `/etc/fortress/secrets.env` via the
  `fortress-load-secrets` loader (see PR #159 for the pattern — IMAP
  mailbox passwords already live there, backed by `pass`).
- Drop the key from `fortress-guest-platform/.env` entirely. The gateway
  can continue to read `litellm_config.yaml` for now, but the longer-term
  goal is to have the gateway service also source its `master_key` from
  `secrets.env` via `EnvironmentFile=/etc/fortress/secrets.env` and a
  thin YAML wrapper (`master_key: os.environ/LITELLM_MASTER_KEY`).
- At that point the rotation protocol collapses to: update `pass`, run
  `fortress-load-secrets`, restart both services. No on-disk value in any
  file tracked or ignored by git.

Until that hardening merges, the three-artefact protocol above is the
standing rule.
