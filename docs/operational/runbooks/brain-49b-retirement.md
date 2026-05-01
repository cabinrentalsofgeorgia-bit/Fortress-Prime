# BRAIN-49B Retirement Runbook

**Status:** RETIRED — operator decision 2026-04-30 13:16:39 EDT
**Authoritative reference:** `docs/operational/phase-9-wave-2-alias-surgery-brief.md` §7 (retirement record), §0.6 (reconciled state)
**ADR reference:** ADR-007 (TP=2 frontier as Fortress Legal synthesizer; the architectural direction that retired BRAIN-49B)

---

## Summary

The `fortress-nim-brain.service` (Llama-3.3-Nemotron-Super-49B-v1.5-FP8 NIM on
spark-5:8100) was retired in favor of the Nemotron-3-Super-120B-A12B-NVFP4
TP=2 frontier on spark-3 + spark-4. Wire-level differentiation across the
five legal-* LiteLLM aliases (`legal-reasoning`, `legal-drafting`,
`legal-summarization`, `legal-brain` transitional, `legal-classification`
transitional) was empirically verified in PR #338.

Image and systemd unit are preserved on spark-5 to keep an emergency
rollback path open during the 14-day soak (active to 2026-05-14).

---

## Current state (post-retirement)

> **Verification note:** Image tag, env file path, and unit details below are
> sourced from `phase-9-wave-2-alias-surgery-brief.md` §7 (committed) and
> `CLAUDE.md` DEFCON 3 section. Live spark-5 inspection was not performed
> during this PR (SSH access not exercised). Pre-rollback verification step
> (§5 step 2 of the rollback procedure) confirms image presence directly
> before any restart.

| Item | Value |
|---|---|
| Host | spark-5 (192.168.0.109) |
| Service | `fortress-nim-brain.service` |
| State | inactive (clean stop), still `enabled` (not yet `disabled`) |
| Stop time | 2026-04-30 13:16:39 EDT (clean `systemctl stop`, exit 0) |
| Unit RAM at stop | 28.7 MiB peak |
| Container | removed at last run (`--rm` flag) |
| Port 8100 | free |
| Image (preserved) | `nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8` |
| NIM container | `nvcr.io/nim/nvidia/llm-nim:latest` (vLLM backend) |
| HF weights cache | `/mnt/fortress_nas/nim-cache/hf/nvidia-Llama-3_3-Nemotron-Super-49B-v1_5-FP8/` |
| Systemd unit path | `/etc/systemd/system/fortress-nim-brain.service` |
| Env file (per repo convention) | `/etc/fortress/fortress-nim-brain.env` |
| spark-5 GPU | available for Wave 3 retrieval host repurpose |

---

## Why retired

Wave 2 alias surgery (PR #337 brief, PR #338 schema fix, PR #339 template
sync) rerouted all Fortress Legal LLM aliases to the existing TP=2 frontier
with differentiated `chat_template_kwargs` per alias. BRAIN-49B was redundant
once per-alias differentiation reached the model on the wire (PR #338 post-fix
probes: `legal-summarization` `reasoning_content` 105 → 0 chars).

ADR-007 (LOCKED 2026-05-01 via the Wave 2 ratification PR) records the
architectural decision: a single TP=2 frontier serves all five legal-* aliases
on differentiated invocation profiles; spark-5 is freed for Wave 3 retrieval.

### Architectural lineage

BRAIN-49B's retirement is the terminal event of a multi-ADR arc; each ADR was
a partial answer, and the full arc explains why the single-node-on-spark-5
deployment direction is no longer current.

- **ADR-001** (LOCKED 2026-04-26): one spark per division (aspirational).
- **ADR-003** (LOCKED 2026-04-29): inference is a shared cross-division
  resource; the app-vs-inference split begins.
- **ADR-004** (LOCKED 2026-04-29): division-per-spark abandoned except
  Fortress Legal; inference-cluster designation expands to Sparks 3/4/5/6.
- **ADR-006** (LOCKED 2026-04-30): Phase 2 partner reassignment — TP=2 lands
  on spark-3+4 instead of spark-5+6.
- **ADR-007** (LOCKED 2026-05-01, the Wave 2 ratification PR):
  Nemotron-3-Super-120B-A12B-NVFP4 TP=2 frontier serves all Fortress Legal
  reasoning; BRAIN-49B retired.

---

## Rollback procedure (emergency only)

If the TP=2 frontier becomes unavailable for legal-* workload and the
incident requires immediate transitional reasoning capacity:

1. **SSH to spark-5:**

   ```bash
   ssh admin@192.168.0.109
   ```

2. **Confirm preserved image is still present:**

   ```bash
   docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' \
     | grep -iE 'nemotron-super-49b|llm-nim'
   ```

   Expect at least the `nvcr.io/nim/nvidia/llm-nim` base image and the
   `nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8` weight reference. If
   missing, abort — image was reaped after the 14-day soak; deeper
   re-deploy is required (see "Re-deployment criteria" below).

3. **Verify unit file is in place:**

   ```bash
   sudo systemctl cat fortress-nim-brain.service
   ```

4. **Start the unit:**

   ```bash
   sudo systemctl start fortress-nim-brain.service
   sudo systemctl is-active fortress-nim-brain.service   # expect: active
   ```

5. **Wait for health:**

   ```bash
   curl -fsS http://localhost:8100/v1/health/ready
   ```

6. **On spark-2, restore prior LiteLLM config from backup:**

   ```bash
   cp /home/admin/Fortress-Prime/litellm_config.yaml.bak.pre-schema-fix.20260430-214559 \
      /home/admin/Fortress-Prime/litellm_config.yaml
   ```

7. **Restart gateway:**

   ```bash
   sudo systemctl restart litellm-gateway.service
   sudo systemctl is-active litellm-gateway.service   # expect: active
   ```

8. **Verify gateway health:**

   ```bash
   curl -fsS http://localhost:8002/v1/models
   ```

9. **Probe one legal alias** to confirm end-to-end routing:

   ```bash
   curl -fsS http://localhost:8002/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
     -d '{"model":"legal-reasoning","messages":[{"role":"user","content":"healthcheck"}],"max_tokens":16}'
   ```

10. **File an incident issue** documenting the restart (cause, scope,
    expected reversion timeline) so the rollback state has durable
    operator visibility.

The rollback restores the 13:12 EDT pre-fix wiring (which routed legal-*
aliases to the TP=2 frontier with the broken `extra_body` schema). To restore
the BRAIN-49B path that pre-dates the 2026-04-30 cutover entirely, deeper
rollback to a config from before PR #322 is required — out of scope for this
runbook.

Rollback is a transitional safety net, not a production reversion path.
Wave 2 architectural direction (TP=2 frontier per ADR-007) is the canonical
decision.

---

## Re-deployment criteria

Re-deploy BRAIN-49B as production reasoning endpoint only if ALL of:

1. The TP=2 frontier proves structurally unable to serve sustained legal-*
   load with per-alias differentiation, AND
2. A second TP=2 frontier (Pattern 1 hot replica) is not viable given spark
   inventory at the time of the decision, AND
3. Operator authorizes the architectural reversal via amendment to ADR-007
   (status: AMENDED) or a new ADR superseding ADR-007.

Document the operational evidence motivating re-deployment as part of the
authorization decision.

---

## Permanent removal (post-soak)

After 2026-05-14 soak completion, BRAIN-49B image + unit MAY be permanently
removed if AND ONLY IF:

1. Soak window completed without any halt event firing.
2. No alias surgery rollback occurred during the soak window.
3. Operator explicitly authorizes permanent removal (separate decision —
   soak completion is necessary but not sufficient).

The procedure below executes only after step 3. Until step 3 is authorized,
image + unit remain in cold storage indefinitely. Soak-ending alone is not
a green light.

**Procedure (only after the three preconditions are satisfied):**

1. `sudo systemctl disable fortress-nim-brain.service`
2. `docker rmi <preserved image tags>`
3. Delete unit file: `sudo rm /etc/systemd/system/fortress-nim-brain.service`
4. Reclaim env file: `sudo rm /etc/fortress/fortress-nim-brain.env`
5. Drop HF weights cache:
   `rm -rf /mnt/fortress_nas/nim-cache/hf/nvidia-Llama-3_3-Nemotron-Super-49B-v1_5-FP8/`
6. Update this runbook header to status `RETIRED — PERMANENT`, or delete
   the runbook and reference the deletion commit from ADR-007 implications.

---

## Cross-references

- PR #337 — Wave 2 alias-surgery brief (canonical Wave 2 direction)
- PR #338 — schema fix wire-level verification (105 → 0 chars proof)
- PR #339 — `deploy/litellm_config.yaml` template sync
- ADR-007 — TP=2 frontier as Fortress Legal synthesizer (LOCKED, Wave 2 ratification PR)
- `docs/operational/phase-9-wave-2-alias-surgery-brief.md` §7 (retirement record)
- `docs/operational/wave-2-schema-fix-verification-2026-05-01.md` (post-fix probe matrix)
- `docs/research/nemotron-3-super-deep-research-2026-04-30.md`
- `docs/research/llama-nemotron-embed-1b-v2-deep-research-2026-04-30.md`
- MASTER-PLAN §8 Q1 — ADR-005 reservation (per-service postgres role pattern; preserved, unrelated to this retirement)
