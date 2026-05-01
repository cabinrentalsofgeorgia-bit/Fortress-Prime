# Runbook — Wave 3.5 BGE Reranker on spark-5

**Status:** ACTIVE
**Service:** `fortress-rerank-llamacpp.service` on spark-5
**Endpoint:** `http://192.168.0.109:8103` (also routed via LiteLLM gateway alias `legal-rerank` on spark-2:8002)
**Model:** `bge-reranker-v2-m3` Q8_0 GGUF (567M params, n_embd=1024, public model from `gpustack/bge-reranker-v2-m3-GGUF`)
**Backend:** llama.cpp version 8994 (aab68217b), CUDA arch 121 (GB10), `--rerank` mode

Replaces the failed NemoGuard reranker NIM `llama-3.2-nv-rerankqa-1b-v2:1.8.0` (cudaErrorSymbolNotFound on GB10; deferred to Wave 3.5 watchlist via PR #343).

---

## What lives where

| Asset | Location |
|---|---|
| llama.cpp build | `/home/admin/llama.cpp/build/bin/llama-server` (built out-of-band by operator with `cmake -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=121 -DLLAMA_CURL=ON`) |
| GGUF model | `/mnt/fortress_nas/models/bge-reranker-v2-m3/bge-reranker-v2-m3-Q8_0.gguf` (607 MB, public download from HF CDN; no HF_TOKEN needed) |
| systemd unit (live) | `/etc/systemd/system/fortress-rerank-llamacpp.service` |
| systemd unit (repo copy) | `deploy/systemd/spark-5/fortress-rerank-llamacpp.service` |
| LiteLLM alias | `legal-rerank` in `litellm_config.yaml` on CAPTAIN, provider `infinity/bge-reranker-v2-m3` (NOT `openai/` — LiteLLM rerank API rejects `openai/`; see "Provider gotcha" below) |
| Disabled-forensic NIM unit | `deploy/systemd/spark-5/fortress-nim-rerank.service` (kept from PR #343 for re-enable when NIM ONNX/CUDA bug fixed) |

---

## Operating

### Health
```bash
ssh admin@spark-5 'curl -sS http://localhost:8103/health'
# {"status":"ok"}

ssh admin@spark-5 'curl -sS http://localhost:8103/v1/models | jq .'
# Returns BGE model metadata (n_vocab, n_embd, n_params, etc.)
```

### Direct rerank smoke
```bash
ssh admin@spark-5 'curl -sS -X POST http://localhost:8103/v1/rerank \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"bge-reranker-v2-m3\",
    \"query\": \"easement on River Heights\",
    \"documents\": [
      \"The plaintiff alleges Knight recorded an easement on River Heights in March 2025 burdening the property in favor of Thor James.\",
      \"The Atlanta Hawks won the 1958 NBA Championship.\",
      \"Knight argues the easement was within his rights as titleholder pre-closing.\"
    ]
  }" | jq .'
```

Expected: index 0 (legal) and index 2 (legal) outrank index 1 (basketball). Score gap ~10-15 points. If the order inverts → service degraded; check journal.

### Through LiteLLM gateway
```bash
ssh admin@captain '
  MASTER_KEY=$(grep "^  master_key:" /home/admin/Fortress-Prime/litellm_config.yaml | awk "{print \$2}")
  curl -sS -X POST http://127.0.0.1:8002/v1/rerank \
    -H "Authorization: Bearer $MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"legal-rerank\",
      \"query\": \"...\",
      \"documents\": [\"...\", \"...\"]
    }" | jq .
'
```

Returns same shape as direct call (Cohere-compatible: `id`, `results[]` with `index` + `relevance_score`, `meta`).

---

## Deploying / restarting

### Restart
```bash
ssh admin@spark-5 'sudo systemctl restart fortress-rerank-llamacpp.service'
```

### Rebuild llama.cpp (only when model architecture or major llama.cpp version change)
**Operator-only** — Claude Code / agents do not rebuild llama.cpp from source on this cluster (per Wave 3.5 sandbox boundary; the source build is a security trust point):
```bash
cd /home/admin/llama.cpp
git pull
cd build
cmake .. -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=121 -DLLAMA_CURL=ON
make -j8 llama-server
sudo systemctl restart fortress-rerank-llamacpp.service
```

CUDA arch `121` is GB10-specific; without it llama.cpp compiles but falls back to CPU inference. Per Saiyam Pathak's Medium article on DGX Spark + llama.cpp.

### Swap model
1. Pull new GGUF to `/mnt/fortress_nas/models/<new-model>/`.
2. Update `ExecStart -m` path in `/etc/systemd/system/fortress-rerank-llamacpp.service`.
3. `sudo systemctl daemon-reload && sudo systemctl restart fortress-rerank-llamacpp.service`.
4. Update LiteLLM alias `model_name: legal-rerank` `litellm_params.model` to `infinity/<new-model-served-name>`.
5. `sudo systemctl restart litellm-gateway.service` on CAPTAIN.

---

## Provider gotcha — DO NOT use `openai/` in the LiteLLM alias

LiteLLM's `/v1/rerank` API surface rejects `openai/` as a provider (file `litellm/rerank_api/main.py` line 547: `Unsupported provider: openai`). Supported providers for rerank are: `cohere`, `litellm_proxy`, `azure_ai`, `infinity`, `together_ai`, `jina_ai`, `nvidia_nim`, `bedrock`, `hosted_vllm`, `deepinfra`, `fireworks_ai`, `voyage`, `watsonx`.

llama.cpp's `--rerank` API surface (`/v1/rerank` with `query`+`documents`, returns `results` with `index`+`relevance_score`) matches **Infinity**'s shape exactly, so use `infinity/<model>` as the LiteLLM `model:` field.

The Wave 3.5 brief literally specified `openai/bge-reranker-v2-m3` — the gateway returned `Unsupported provider` until I switched to `infinity/`. This is documented inline in the LiteLLM config comment block.

### Note on api_base path
For `infinity/` provider, `api_base` is the **service root**, not `/v1` (Infinity prepends `/rerank` itself). Use `http://192.168.0.109:8103`, NOT `http://192.168.0.109:8103/v1`. (The brief's `/v1` suffix would have failed silently.)

---

## Capacity & co-tenancy

- BGE Q8 reranker uses ~600 MB GPU memory. Negligible vs spark-5's 124 GB unified memory.
- Spark-5 is currently otherwise idle (BRAIN retired Wave 2). Plenty of headroom for the failover frontier (`fortress-frontier-failover.service`, drafted-disabled) co-tenancy.

## Troubleshooting

### Service won't start
- Check llama-server binary exists: `ls -la /home/admin/llama.cpp/build/bin/llama-server`. If missing → operator rebuild needed.
- Check GGUF integrity: `file /mnt/fortress_nas/models/bge-reranker-v2-m3/bge-reranker-v2-m3-Q8_0.gguf` should report `data` and the first 4 bytes should be `GGUF` (`head -c 4 ... | xxd`).
- Check journal: `sudo journalctl -u fortress-rerank-llamacpp.service -n 100`.

### Rerank returns wrong order
- Re-run direct smoke (legal vs basketball above). If still wrong → model corruption; re-pull GGUF.
- If direct smoke works but gateway smoke wrong → LiteLLM alias misrouted. Check `litellm_config.yaml` `legal-rerank` entry; verify `api_base` is `http://192.168.0.109:8103` (no `/v1` suffix) and provider is `infinity/`.

### Latency regression
- BGE Q8 is small; most latency is HTTP+LiteLLM overhead. Expected: <200 ms warm for 10 documents. If >1s → check spark-5 GPU is not over-allocated by other workloads (e.g., failover frontier was activated).

---

## References

- llama.cpp `--rerank` mode: https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md
- BGE model card: https://huggingface.co/BAAI/bge-reranker-v2-m3
- GGUF source: https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF
- LiteLLM rerank providers: source at `litellm/rerank_api/main.py`
- `docs/operational/cluster-nim-deployment-conventions.md` — systemd/cache/port conventions
- `wave-3-final-report.md` — context on the failed NemoGuard NIM this replaces
