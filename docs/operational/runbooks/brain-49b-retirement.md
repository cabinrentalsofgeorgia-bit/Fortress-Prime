# BRAIN-49B Retirement Runbook

**Date retired:** 2026-04-30 (Phase 9 — Wave 2 alias surgery)
**Reason:** Replaced by Nemotron-3-Super-120B-A12B-NVFP4 (TP=2 spark-3+spark-4) per ADR-007 (PROPOSED in PR #321) — see `docs/operational/nemotron-3-super-tp2-deployment.md`. ADR-005 amendment deferred per Phase 9 PR (numbering reconciliation pending; see follow-up issue "ADR-005 numbering reconciliation").
**State after retirement:** Service stopped. Image preserved. Unit files preserved with `.retired-2026-04-30` suffix.
**Operator authorization:** Phase 9 brief §7, executed 2026-04-30.

---

## What was retired

Three units on **spark-5** (`192.168.0.109`):

| Unit | Active state | Pre-retirement role |
|---|---|---|
| `fortress-nim-brain.service` | active running 32+ hours → **inactive** | NIM container serving Nemotron-Super-49B-FP8 on `:8100` (Tier 2 sovereign reasoning) |
| `fortress-nim-brain-drift-check.service` | timer-driven probe → **inactive** | Periodic health check against BRAIN endpoint |
| `fortress-nim-brain-drift-check.timer` | active enabled → **inactive + disabled** | Cadence trigger for drift-check |

Docker container `fortress-nim-brain` (image `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:2.0.1`, 21.3 GB) was running under the service unit and stopped with it.

## What was preserved

- `/etc/systemd/system/fortress-nim-brain.service.retired-2026-04-30` (2638 B)
- `/etc/systemd/system/fortress-nim-brain-drift-check.service.retired-2026-04-30` (430 B)
- `/etc/systemd/system/fortress-nim-brain-drift-check.timer.retired-2026-04-30` (292 B)
- Active unit files at original path (still present, just inactive — restoration uses these as canonical)
- Docker image `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:2.0.1` — **NOT removed** (`docker rmi` not run)
- 3 historical `.bak-*` unit files (`bak-perhost-20260426`, `bak-pre-overnight-20260427`, `bak-pre-r1-20260427`) — untouched per operator directive
- Pre-retirement state captured to `/tmp/brain-49b-pre-retirement-state.txt` on spark-5

## Pre-retirement evidence

```
spark-5:/tmp/brain-49b-pre-retirement-state.txt — 4898 bytes
  - Pre-stop systemctl status (BRAIN + drift-check service + drift-check timer)
  - Docker ps -a output
  - :8100 health response (was 'ready' immediately before stop)
```

## Restart procedure (rollback)

If TITAN endpoint becomes unavailable for an extended period and BRAIN-49B needs to come back, follow this in order. **Restoration is symmetric to retirement** — restart BRAIN first, then drift-check.

### 1. SSH to spark-5

```bash
ssh admin@192.168.0.109
```

### 2. Confirm nothing else has bound `:8100` since retirement

```bash
sudo ss -tlnp | grep ':8100'   # expect: empty
```

If something else now uses `:8100`, stop that first — `fortress-nim-brain.service` will fail to start otherwise.

### 3. Verify image still present

```bash
docker images nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5
# expected: 2.0.1 tag, ~21.3 GB
```

If absent, repull:

```bash
docker pull nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:2.0.1
```

(NGC auth required; `~/.docker/config.json` should already have `nvcr.io` entry.)

### 4. Start BRAIN-49B service

The active unit file is still in place at `/etc/systemd/system/fortress-nim-brain.service`. Just start it:

```bash
sudo systemctl start fortress-nim-brain.service
```

Wait ~30s for NIM container to come up.

### 5. Verify BRAIN health

```bash
curl -fsS --max-time 10 http://192.168.0.109:8100/v1/health/ready
# expected: {"object":"health.response","message":"ready","status":"ready"}
```

### 6. Restart drift-check (symmetric)

```bash
sudo systemctl start fortress-nim-brain-drift-check.service
sudo systemctl enable fortress-nim-brain-drift-check.timer
sudo systemctl start fortress-nim-brain-drift-check.timer
```

Verify:

```bash
sudo systemctl is-active fortress-nim-brain-drift-check.service   # inactive (oneshot; runs on timer)
sudo systemctl is-enabled fortress-nim-brain-drift-check.timer    # enabled
sudo systemctl is-active fortress-nim-brain-drift-check.timer     # active
```

### 7. Update LiteLLM config to route legal-* aliases at BRAIN endpoint temporarily

Live config is `/home/admin/Fortress-Prime/litellm_config.yaml` on **spark-2**. Backups from Phase 9 mutation:

- `/home/admin/Fortress-Prime/litellm_config.yaml.bak.phase-9-20260430_131140` ← Phase 9 pre-mutation
- `/home/admin/Fortress-Prime/litellm_config.yaml.bak.20260429-210559` ← earlier
- `/home/admin/Fortress-Prime/litellm_config.yaml.bak` ← earlier

To roll back to BRAIN routing (point all 5 legal-* aliases at `http://spark-5:8100/v1`):

```bash
ssh admin@192.168.0.100 'cd /home/admin/Fortress-Prime && \
  cp litellm_config.yaml litellm_config.yaml.bak.rollback-$(date +%Y%m%d_%H%M%S) && \
  cp litellm_config.yaml.bak.phase-9-20260430_131140 litellm_config.yaml && \
  sudo systemctl restart litellm-gateway.service && \
  sleep 5 && \
  sudo systemctl is-active litellm-gateway.service'
```

The Phase 9 backup file is the canonical rollback target — it has the original 4-alias spark-5 BRAIN-49B routing.

### 8. Smoke each alias against the rolled-back gateway

```bash
ssh admin@192.168.0.100 'MK=$(grep "^  master_key" /home/admin/Fortress-Prime/litellm_config.yaml | awk "{print \$2}")
for ALIAS in legal-reasoning legal-classification legal-summarization legal-brain; do
  echo "=== $ALIAS ==="
  curl -fsS --max-time 60 http://127.0.0.1:8002/v1/chat/completions \
    -H "Authorization: Bearer $MK" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"$ALIAS\", \"messages\": [{\"role\":\"user\",\"content\":\"Reply with only PONG.\"}], \"max_tokens\": 400}" \
    | jq ".choices[0].message.content"
done'
```

### 9. File P0 incident

```
Title: BRAIN-49B emergency restart from retired state — TITAN unavailable
Body:
  Date: <YYYY-MM-DD HH:MM>
  Trigger: <what failed on TITAN>
  Action: BRAIN-49B restarted on spark-5 per
    docs/operational/runbooks/brain-49b-retirement.md
  LiteLLM rolled back to pre-Phase-9 alias map
  Next: investigate TITAN failure root cause, plan re-cutover
```

## Note about unit file Description text

The `fortress-nim-brain.service` unit file currently has:

```
Description=Fortress NIM Brain — nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8 on spark-1 (Tier 2 sovereign reasoning)
```

The "**on spark-1**" text is **stale** — service has run on spark-5 since the 2026-04-28 BRAIN topology shift (per CLAUDE.md update), not spark-1. This is a cosmetic doc-debt item only. **When restoring, also fix the Description text** — should read "on spark-5". Edit:

```bash
sudo sed -i 's|on spark-1|on spark-5|' /etc/systemd/system/fortress-nim-brain.service
sudo systemctl daemon-reload
```

(The `daemon-reload` doesn't restart the service; safe to run while BRAIN is up.)

## Permanent removal

After 14-day soak (target 2026-05-14) plus operator confirmation that TITAN remains stable:

```bash
ssh admin@192.168.0.109 '
  # Image removal
  docker rmi nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:2.0.1
  # Unit file deletion (active + .retired versions)
  sudo rm /etc/systemd/system/fortress-nim-brain.service
  sudo rm /etc/systemd/system/fortress-nim-brain.service.retired-2026-04-30
  sudo rm /etc/systemd/system/fortress-nim-brain-drift-check.service
  sudo rm /etc/systemd/system/fortress-nim-brain-drift-check.service.retired-2026-04-30
  sudo rm /etc/systemd/system/fortress-nim-brain-drift-check.timer
  sudo rm /etc/systemd/system/fortress-nim-brain-drift-check.timer.retired-2026-04-30
  # NOTE: 3 historical .bak files (bak-perhost-20260426, bak-pre-overnight-20260427,
  # bak-pre-r1-20260427) are operator decision — preserve as forensic record OR
  # remove together. Default: remove with the rest at permanent-removal time.
  sudo systemctl daemon-reload
'
# On spark-2:
ssh admin@192.168.0.100 '
  # Remove this runbook + the Phase 9 backup config
  rm /home/admin/Fortress-Prime/litellm_config.yaml.bak.phase-9-20260430_131140
  cd /home/admin/Fortress-Prime
  rm docs/operational/runbooks/brain-49b-retirement.md
'
```

Update ADR-005 (when filed) consequences section to reflect permanent removal.

## Cross-references

- Phase 9 PR: `feat/phase-9-wave-2-alias-surgery-2026-04-30` (introduces this runbook)
- Phase 8 PR: PR #321 (ADR-007 PROPOSED — TP=2 deployment evidence)
- LiteLLM Phase 9 mutation backup: `litellm_config.yaml.bak.phase-9-20260430_131140` on spark-2
- Pre-retirement state capture: `/tmp/brain-49b-pre-retirement-state.txt` on spark-5
