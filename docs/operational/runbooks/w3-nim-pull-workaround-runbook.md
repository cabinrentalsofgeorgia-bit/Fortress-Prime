# W3 — NIM Weight Pull Workaround Runbook

**Purpose:** Canonical procedure for pulling NIM weights into the cluster while F5 (cluster-egress sustained-transfer failure to `xfiles.ngc.nvidia.com`) is unresolved.

**Status:** ACTIVE STANDARD until F5 lands. All NIM weight pulls go through W3.
**Owner:** Operator (only operator-side internet egress works for sustained NGC weight pulls).
**Cross-references:**
- F5 investigation: `docs/operational/briefs/f5-root-cause-investigation-2026-04-29.md`
- F2 fix (related TLS handshake): `docs/operational/briefs/iptables-mss-persistence-brief.md`

---

## 1. When to use this runbook

Trigger conditions:
- Any NIM model needs weights resident in `/mnt/fortress_nas/nim-cache/...`
- Any per-NIM deployment brief calls for weight materialization on NAS
- TIER 1 NeMo Retriever family batch-pull (until F5 lands, executed sequentially through W3)
- Cluster-side `ngc registry model download-version` returns `DownloadFileSizeMismatch`

Do NOT trigger if:
- Weights already on NAS (verify first with `ls /mnt/fortress_nas/nim-cache/<model>/...`)
- The artifact is an *image* not a weights blob — image pulls from `nvcr.io` work on cluster with retries

## 2. Prerequisites (one-time on operator Mac)

1. NGC CLI installed:
   ```sh
   brew install ngc-cli   # or download from ngc.nvidia.com
   ngc --version
   ```
2. NGC CLI configured:
   ```sh
   ngc config set
   # paste API key when prompted; org = `nvidia`; team = `nvidia` (or as scoped)
   ```
3. SSH alias to NAS-accessible cluster spark in `~/.ssh/config`:
   ```sshconfig
   Host spark-1
       HostName 10.10.10.2
   ```
4. NAS path writable from cluster (already standard): `/mnt/fortress_nas/nim-cache/`

## 3. Procedure

For each NIM weights pull:

### 3.1 On operator Mac — pull from NGC

```sh
NIM_NAME="<model-short-name>"     # e.g., llama-nemotron-embed
NIM_VERSION="<org>/<team>/<repo>:<profile>"  # e.g., nim/nvidia/llama-nemotron-embed-1b-v2:cc_12_0-fp16-6d747e0e

mkdir -p ~/Downloads/${NIM_NAME}-weights/
cd ~/Downloads/${NIM_NAME}-weights/

ngc registry model download-version "${NIM_VERSION}"
```

Verify the extracted folder contents — should include:
- `*.safetensors` or `*.bin` weight shards
- `config.json`, `tokenizer*.json`, `generation_config.json` (HF-style metadata)
- A `manifest.json` or model card (if NIM-specific)

### 3.2 On operator Mac — scp to NAS canonical cache

```sh
NAS_CACHE_BASE="/mnt/fortress_nas/nim-cache/nim/<model>/nim-weights-cache/ngc/hub"
EXTRACTED_DIR=$(ls -d ~/Downloads/${NIM_NAME}-weights/*/ | head -1)

# Create canonical HF-cache layout target on NAS via the cluster spark (NAS is mounted there)
ssh spark-1 "mkdir -p ${NAS_CACHE_BASE}/<canonical-hf-layout>/"

# scp the extracted contents
scp -r "${EXTRACTED_DIR}"/* spark-1:${NAS_CACHE_BASE}/<canonical-hf-layout>/
```

Replace `<canonical-hf-layout>` with the layout the per-NIM deployment brief specifies (typically `models--<org>--<repo>/snapshots/<rev>/` for HF-cache compatibility).

### 3.3 On cluster (spark) — verify and consume

```sh
ssh spark-1 "ls -la ${NAS_CACHE_BASE}/<canonical-hf-layout>/ | head -10"
```

Expected: full weight set present, sizes match NGC manifest.

Cluster reads from NAS-mounted cache; the NIM container is configured (per per-NIM deployment brief) to set `HF_HOME` / `NIM_CACHE_PATH` to the NAS path. **No NGC fetch from sparks.** This is the sovereign-cache property — once weights on NAS, cluster is offline-capable for that model.

### 3.4 Cleanup on Mac

```sh
rm -rf ~/Downloads/${NIM_NAME}-weights/
```

## 4. Limitations

- **Manual operator step** — does not scale to dozens of NIMs without operator hands-on time
- **Operator's home internet capacity is the pull bottleneck** — multi-GB downloads pace at home ISP speed
- **Operator availability blocks fully-automated TIER 1 batch-pull** — no agent can autonomously trigger this
- **Each pull requires correct HF-cache layout reconstruction on NAS** — operator must know the per-NIM layout convention
- **No retry-on-failure automation** — if the pull fails midway on Mac (rare, but possible), operator restarts manually

## 5. Advantages

- **Works today** — no infrastructure access required
- **Bypasses cluster's broken egress entirely** — independent of F5 root cause
- **Sovereign** — once weights on NAS, cluster never touches NGC again for that model
- **Cleanly reproducible** — same procedure for any NIM
- **Auditable** — operator can capture timestamps, file sizes, and SHAs at each step

## 6. When F5 lands

This runbook becomes obsolete (or downgraded to a fallback for environments without internet). All callers — TIER 1 batch-pull brief, per-NIM deployment briefs, master plan §6.5 — should be updated to remove the W3 dependency once F5 fix is verified.

Verification that F5 is fixed:
```sh
ssh spark-1 'curl -sS --max-time 60 -o /tmp/test.bin -w "size=%{size_download} time=%{time_total}\n" \
  -H "Authorization: Bearer $NGC_CLI_API_KEY" \
  "https://xfiles.ngc.nvidia.com/<known-multi-MB-artifact>"'
```

If `size` matches expected and no `DownloadFileSizeMismatch`, F5 is resolved. Re-run the TIER 1 batch-pull from the cluster directly to confirm at scale.

## 7. References

- F5 investigation surface: `docs/operational/briefs/f5-root-cause-investigation-2026-04-29.md`
- F2 fix (TLS handshake MSS clamp, retained): `docs/operational/briefs/iptables-mss-persistence-brief.md`
- Cluster network topology: `docs/architecture/shared/cluster-network-topology.md`
- NGC CLI docs: `https://docs.ngc.nvidia.com/cli/`

---

End of runbook.
