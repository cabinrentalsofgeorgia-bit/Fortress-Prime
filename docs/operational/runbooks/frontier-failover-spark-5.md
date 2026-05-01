# Runbook — Frontier Failover to Single-Spark on spark-5

**Status:** DRAFTED, NOT ACTIVE. Insurance for tail-risk only.
**Triggered by:** dual-Spark TP=2 NCCL all-reduce deadlock on spark-3+spark-4 frontier ([forums 366127](https://forums.developer.nvidia.com/t/nccl-all-reduce-deadlock-on-dual-dgx-spark-after-successful-channel-establishment-affects-both-vllm-and-trt-llm/366127)) — sustained, not transient.
**Service unit:** [`deploy/systemd/spark-5/fortress-frontier-failover.service`](../../../deploy/systemd/spark-5/fortress-frontier-failover.service)
**Model:** `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` (weights pre-staged at `/mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/`, 75 GB, 17 safetensors shards)
**Throughput target on single Spark:** ~24 tok/s (vs production TP=2 baseline) — degraded but functional. Use as failover, not primary.

---

## When to fail over

**Fail over only if ALL of these are true:**

1. `curl http://10.10.10.3:8000/health` returns non-200 sustained for **>5 minutes** (NOT brief §3.3's 60-second hard-stop window — that triggers Wave-execution halt, not failover).
2. `nvidia-smi` on spark-3 AND spark-4 shows the vLLM frontier process either (a) hung at 100% GPU but no TX, or (b) crashed and restart loop is failing.
3. Soak collector shows `endpoint_health` stuck at non-200 for >5 consecutive ticks.
4. NCCL log on spark-3 or spark-4 shows the deadlock fingerprint from forums 366127 (look for `ncclCommAbort` calls, `proxy.cc` stuck in `FREE_RESOURCE`, or all-reduce timeouts on a specific channel).

**Do NOT fail over for:**
- Single transient 502/504 from gateway (LiteLLM retry, transient network blip).
- Frontier high latency without errors (capacity issue, not deadlock).
- Operator-initiated frontier restart in flight.

If unsure, **do NOT fail over** — degraded TP=2 throughput is preferable to fragmented retrieval/reasoning paths.

---

## Activation procedure

### Step 0 — Verify weights still intact

```bash
ssh admin@spark-5 '
  cd /mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/
  sha256sum -c MANIFEST.sha256 2>/dev/null | grep -v ": OK$" | head
  # Expected: zero output (all OK)
'
```

If MANIFEST mismatch on >0 files: re-pull the failed shards from HF before continuing. Do NOT proceed with corrupted weights.

### Step 1 — Verify spark-5 has GPU headroom

```bash
ssh admin@spark-5 '
  nvidia-smi --query-gpu=memory.free,memory.total --format=csv
  # GB10 reports N/A for unified memory — use docker stats instead:
  docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}" \
    | grep -E "fortress-rerank-llamacpp|fortress-frontier-failover"
'
```

Reranker idle uses ~600 MB. Failover model needs ~85% × 124 GB ≈ 105 GB. Net: only run the failover if spark-5's GPU is free enough (no other co-tenants).

### Step 2 — Stage and start the unit

```bash
ssh admin@spark-5 '
  sudo cp /home/admin/Fortress-Prime/deploy/systemd/spark-5/fortress-frontier-failover.service \
          /etc/systemd/system/
  sudo systemctl daemon-reload

  # IMPORTANT: do NOT enable. Single-shot failover. We do not want
  # this auto-starting on boot — operator must consciously activate.
  sudo systemctl start fortress-frontier-failover.service

  # Watch startup
  sudo journalctl -u fortress-frontier-failover.service -f
'
```

vLLM cold start with 120B/NVFP4 model + 1M context will take 5-15 minutes (weight load from NAS + KV cache allocation + CUDA graph capture).

### Step 3 — Verify endpoint

```bash
ssh admin@spark-5 '
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 60
    CODE=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/health 2>/dev/null)
    echo "minute $i: http=$CODE"
    if [ "$CODE" = "200" ]; then break; fi
  done
  curl -fsS http://localhost:8000/v1/models | jq .
'
```

### Step 4 — Cut LiteLLM aliases over

Edit `/home/admin/Fortress-Prime/litellm_config.yaml` on CAPTAIN. For each of `legal-reasoning`, `legal-drafting`, `legal-summarization`, `legal-brain`, `legal-classification`, replace `api_base` from the TP=2 frontier endpoint to:

```yaml
      api_base: http://192.168.0.109:8000/v1
```

Then:

```bash
ssh admin@captain '
  cp /home/admin/Fortress-Prime/litellm_config.yaml \
     /home/admin/Fortress-Prime/litellm_config.yaml.bak.failover-$(date +%Y%m%dT%H%M%SZ)
  # ... apply edits ...
  sudo systemctl restart litellm-gateway.service
  sleep 8
  MASTER_KEY=$(grep "^  master_key:" /home/admin/Fortress-Prime/litellm_config.yaml | awk "{print \$2}")
  curl -fsS http://127.0.0.1:8002/v1/models -H "Authorization: Bearer $MASTER_KEY" \
    | jq ".data[] | select(.id|startswith(\"legal-\"))"
'
```

### Step 5 — Smoke through gateway

```bash
ssh admin@captain '
  MASTER_KEY=$(grep "^  master_key:" /home/admin/Fortress-Prime/litellm_config.yaml | awk "{print \$2}")
  curl -fsS http://127.0.0.1:8002/v1/chat/completions \
    -H "Authorization: Bearer $MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"legal-summarization\",
      \"messages\": [{\"role\":\"system\",\"content\":\"detailed thinking on\"},
                     {\"role\":\"user\",\"content\":\"Two-sentence summary of: warranty deeds in Georgia.\"}],
      \"max_tokens\": 200
    }" | jq .
'
```

If 200 with sensible output: failover live. Notify users that throughput is degraded (~24 tok/s vs TP=2 baseline) but service is restored.

---

## Deactivation (fail back) procedure

When spark-3+spark-4 TP=2 frontier is healthy again and you want to revert:

```bash
# 1. On spark-5: stop and remove the failover service
ssh admin@spark-5 '
  sudo systemctl stop fortress-frontier-failover.service
  sudo rm /etc/systemd/system/fortress-frontier-failover.service
  sudo systemctl daemon-reload
'

# 2. On CAPTAIN: restore original LiteLLM config from the most recent
#    pre-failover backup
ssh admin@captain '
  cd /home/admin/Fortress-Prime
  ls -t litellm_config.yaml.bak.failover-* | head -1 | xargs -I {} cp {} litellm_config.yaml
  sudo systemctl restart litellm-gateway.service
  sleep 8
  MASTER_KEY=$(grep "^  master_key:" litellm_config.yaml | awk "{print \$2}")
  curl -fsS http://127.0.0.1:8002/v1/models -H "Authorization: Bearer $MASTER_KEY" \
    | jq ".data[] | select(.id|startswith(\"legal-\"))"
'

# 3. Smoke a short legal-summarization request to confirm TP=2 frontier
#    is serving again (same curl as activation step 5)
```

---

## Co-tenancy notes

- **BGE reranker (`fortress-rerank-llamacpp.service`)** runs on the same spark-5 GPU. The failover unit's `--gpu-memory-utilization 0.85` (instead of vLLM default 0.9) leaves ~19 GB headroom for OS + reranker. **Do NOT stop the reranker** when failing over — `legal-rerank` is still served from spark-5:8103 and is independent of `legal-reasoning` traffic.
- If failover triggers OOM despite 0.85, drop reranker temporarily (`sudo systemctl stop fortress-rerank-llamacpp.service`) and accept that retrieval reranking is offline until fail-back.

## Why TP=1 instead of attempting TP=2 across spark-5 + another node

- spark-3 and spark-4 are presumed-failing in the deadlock scenario; not viable as TP partners.
- spark-1 is occupied by other Tier 4/5 services; not freed yet.
- Single-Spark TP=1 with NVFP4 + 1M context is the documented recipe per the HF model card "DGX Spark" instructions and is the lowest-risk path under the assumption that the deadlock is in NCCL across hosts, not in vLLM itself.

## Audit trail

When activating: capture `nvidia-smi`, frontier `/health` status, NCCL log fingerprint, and timestamp into `docs/operational/INC-YYYY-MM-DD-frontier-deadlock.md` for postmortem.

## References

- [forums 366127 — NCCL all-reduce deadlock dual-Spark](https://forums.developer.nvidia.com/t/nccl-all-reduce-deadlock-on-dual-dgx-spark-after-successful-channel-establishment-affects-both-vllm-and-trt-llm/366127)
- [forums 364862 — Leon Gibat dual-Spark TP=2 NVFP4 24 tok/s baseline](https://forums.developer.nvidia.com/t/nemotron-3-super-nvfp4-via-vllm-tp-2-on-2x-dgx-spark-24-tok-s-abi-fix-for-cu130-cu132-mismatch/364862)
- ADR-007 (LOCKED 2026-05-01) — frontier serving plan
- `docs/operational/cluster-nim-deployment-conventions.md` — systemd unit conventions
- HF model card: `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` "DGX Spark" deployment section
