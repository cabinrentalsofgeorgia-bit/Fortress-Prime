# Post-Soak Verification Runbook — 2026-05-14

**Window:** 2026-04-30 23:00 UTC → 2026-05-14 13:00 UTC (14 days, opened on PR #331 + PR #332 merge)
**Pairs with:** scheduled remote agent `trig_011Epc3mHBX1oLMdetTj5hkt` ([routine](https://claude.ai/code/routines/trig_011Epc3mHBX1oLMdetTj5hkt)), which fires at the same wall and posts the GitHub-side verification comment on PR #332. This file is the **cluster-side counterpart** that requires private-LAN access to spark-2 / spark-3 and so cannot be automated remotely.

The remote agent's comment will list these checks as "operator required." Run them in order, capture the outputs, and reply to the agent's comment with a one-line per-check summary or paste the raw outputs.

---

## 0. Where to run

From spark-2 (this host, `192.168.0.100`). Frontier is `http://10.10.10.3:8000` on spark-3, reachable over fabric A.

```sh
ssh admin@192.168.0.100   # only if running from elsewhere; if already on spark-2, skip
```

---

## 1. Frontier health throughout the window

```sh
# Live health (must be 200 right now)
curl -fsS http://10.10.10.3:8000/health
curl -fsS http://10.10.10.3:8000/v1/models | jq '.data[0].id'   # expect "nemotron-3-super"

# Container is Docker-managed (no systemd unit on either spark-2 or spark-3),
# so the journal is in `docker logs`, not `journalctl -u vllm*`.
ssh admin@10.10.10.3 \
  "docker logs vllm_node --since=2026-04-30T23:00:00Z --until=2026-05-14T13:00:00Z 2>&1" \
  | grep -iE "halt|degrade|error|hang|oom|killed|cuda fail|ray.*died" \
  | head -50

# Spot-check vLLM build hasn't drifted from the PR #330 inventory baseline
ssh admin@10.10.10.3 'docker exec vllm_node vllm --version'
# expected: 0.20.1rc1.dev96+gefdc95674.d20260430.cu132 (or, if container was
# rebuilt during the window, capture the new version and surface the change)

ssh admin@10.10.10.3 'ps -p $(docker inspect vllm_node --format "{{.State.Pid}}") -o etime --no-headers'
# uptime — if shorter than 14 days, the container restarted; investigate
```

**Clean signal:** `/health` 200 now, zero error/halt lines from the docker-logs grep, vllm version unchanged, container uptime ≥ 14 days.

**Surfaces concern if:** non-200 status, halt/error lines present, version drift, or a restart inside the window.

---

## 2. Soak halt-event count

The Phase 9 soak collector's halt-state file location wasn't pinned at runbook-write time (operator memory was "wherever sentinel writes it"). Candidates I enumerated on 2026-04-30:

```sh
ls -la /home/admin/.fortress_sentinel_state.json    # 82 MB — file-integrity sentinel, NOT soak
ls -la /home/admin/.fortress_archiver_state.json    # 144 B — archiver, NOT soak
ls -la /home/admin/.fortress_sync_health.json       # 162 B — sync health, NOT soak
ls -la /home/admin/.fortress_*soak* /home/admin/soak-* 2>/dev/null  # nothing on 2026-04-30
```

None of the files visible at the runbook write match the Phase 9 soak collector. Confirm at runtime where it actually writes:

```sh
# Discover the live file:
sudo lsof -p $(systemctl show -p MainPID --value fortress-soak-collector 2>/dev/null) 2>/dev/null \
  | awk '/REG/ && /home/'   # if collector runs under systemd
ps -ef | grep -i soak | grep -v grep   # find the process
find /home/admin /var/lib /var/log -maxdepth 4 -iname '*soak*' -mtime -15 2>/dev/null
```

Once located, halt count is:

```sh
SOAK_STATE=<path-from-discovery-above>
jq '.halt_events // [] | length' "$SOAK_STATE"
jq '.halt_events // [] | .[] | {ts, reason, section}' "$SOAK_STATE"   # detail any halts
```

**Clean signal:** halt count = 0.
**Surfaces concern if:** halt count ≥ 1 — capture each halt's ts/reason/section, decide whether retired Phase 4 needs to revisit.

---

## 3. Track A v3 traffic samples — per-section policy adherence

Confirm any new Track A runs since 2026-04-30 still routed §2/§7 to `enable_thinking=False` and §4/§8/§9 to `low_effort=True` and §5 to `low_effort=False` (per PR #332 SECTION_REASONING_POLICY).

```sh
# Recent runs (skip the ones from 2026-04-30 itself — those are Phase 3 baseline)
ls -dt /tmp/track-a-case-i-v3-* 2>/dev/null | head -10

# For each recent run, dump the per-section reasoning kwargs as recorded by
# MetricCapturingBrainClient.metrics_log:
for DIR in $(ls -dt /tmp/track-a-case-i-v3-2026-05-* 2>/dev/null | head -5); do
  echo "=== $DIR ==="
  jq '.brain_client_call_metrics[] | {
        section_id,
        enable_thinking,
        low_effort,
        reasoning_chars,
        finish_reason,
        wall_seconds
      }' "$DIR/metrics/run-summary.json" 2>/dev/null
done
```

**Clean signal — per-section reasoning policy still in effect:**

| section_id | enable_thinking | low_effort | reasoning_chars (typical) | finish |
|---|---|---|---:|---|
| section_02_critical_timeline | False | None | 0 | stop |
| section_04_claims_analysis | True | True | ~500 | stop |
| section_05_key_defenses_identified | True | False | ~19,000 | stop |
| section_07_email_intelligence_report | False | None | 0 | stop |
| section_08_financial_exposure_analysis | True | True | ~1,200 | stop |

**Surfaces concern if:** any synthesis section shows `enable_thinking=None` (policy lookup broke, falling back to BrainClient default) or `finish=length` (reasoning runaway re-emerging) or §5 with `low_effort=True` (the §5 isolation regression — see PR #332 §3 of run report).

If no Track A runs happened during the window, that itself is a soft signal worth noting (no production traffic exercised the wiring).

---

## 4. /metrics scrape — reasoning_chars distribution sanity

```sh
curl -fsS http://10.10.10.3:8000/metrics | grep -E "reasoning|finish_reason|generation_tokens" | head -30
# vLLM 0.20.1rc1 may not expose per-completion reasoning_chars histograms
# directly; if the grep is empty, fall back to:
curl -fsS http://10.10.10.3:8000/metrics | grep -E "vllm:e2e|vllm:request_generation|vllm:tokens" | head -30
```

If reasoning-specific metrics are exposed: confirm distribution shapes are consistent with Phase 3 expected ranges (productive synthesis sections in the 1k–5k reasoning_token range; mechanical/categorization sections at 0).

If not exposed: this check degrades to "rough sanity on overall generation token counts" — accept that and note it. The substantive per-section reasoning data lives in step 3 (per-run JSONs), not /metrics.

**Surfaces concern if:** generation token rates spiked (KV cache pressure), or reasoning-specific histograms show a long tail above 10k tokens (suggests routing fell back to unbounded reasoning somewhere).

---

## 5. Decision

After steps 1–4:

- **Cluster-side clean** (frontier 200 throughout, halt count 0, per-section policy still routing as expected, /metrics consistent): **Phase 4 stays retired. 4-phase plan complete.** Reply to the remote agent's comment with "Cluster-side clean. Plan complete."
- **Cluster-side surfaced X** (any of the "Surfaces concern if" triggers above fired): file the specific concern as a new issue or a Phase 4 reactivation brief. Reply to the remote agent's comment with the specific concern, severity, and link to the new issue.

---

## 6. References

- PR #330 — frontier inventory baseline (vLLM 0.20.1rc1, no `--reasoning-config`, no MTP)
- PR #331 — BrainClient Phase 2 wiring
- PR #332 — Phase 3 per-section routing (this PR's parent)
- Plan v2 doc — `/home/admin/nemotron-3-super-tp2-stabilization-4-phase-plan-v2-2026-04-30.md` (retired Phase 4 retired-unless-soak-surfaces clause)
- Scheduled remote agent — [`trig_011Epc3mHBX1oLMdetTj5hkt`](https://claude.ai/code/routines/trig_011Epc3mHBX1oLMdetTj5hkt) (GitHub-side counterpart)
