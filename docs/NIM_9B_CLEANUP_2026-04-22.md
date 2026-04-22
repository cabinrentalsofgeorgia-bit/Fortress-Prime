# NIM 9B Mislabeled Image Cleanup — 2026-04-22

**Branch:** `chore/cleanup-9b-arm64-mismatch`  
**Audit reference:** `docs/NIM_CACHE_AUDIT_2026-04-22.md`, `docs/NIM_ARM64_DISCOVERY_2026-04-22.md`  
**Stop condition origin:** 2026-04-22 ~07:56 UTC — `exec /opt/nvidia/nvidia_entrypoint.sh: exec format error` on spark-4

---

## Actions Executed

### NAS

| Action | Path | Result |
|--------|------|--------|
| `rm -rf` | `/mnt/fortress_nas/nim-cache/nim/nvidia-nemotron-nano-9b-v2/` | Removed (8.1 GB freed) |

Remaining NAS cache after cleanup:
```
/mnt/fortress_nas/nim-cache/nim/
  llama-nemotron-embed-1b-v2/     ← MATCH (genuine arm64, keep)
  llama-nemotron-embed-vl-1b-v2/
  nemotron-3-nano-30b-a3b/
  nemotron-nano-12b-v2-vl/        ← MATCH (genuine arm64, keep)
```

### spark-4 Docker daemon (`192.168.0.106`)

| Action | Target | Result |
|--------|--------|--------|
| `docker image rm` | `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:latest` | 5 layers deleted |
| `docker image rm` | `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:sha-3e20559d2fe1` | (same image, already gone) |

### spark-4 systemd

| Action | Unit | Result |
|--------|------|--------|
| `systemctl disable` | `fortress-nim-vrs-concierge.service` | Already disabled — no-op |
| `rm -f` | `/etc/systemd/system/fortress-nim-vrs-concierge.service` | Removed |
| `systemctl daemon-reload` | — | OK |

---

## Root Cause (Summary)

`nvidia-nemotron-nano-9b-v2:latest` at `nvcr.io/nim/nvidia/` has a packaging defect: the arm64 sub-manifest (`sha256:a8ec96...`) contains 102/122 layers that are byte-for-byte identical to the amd64 manifest, including the 3.2 GB CUDA runtime layer. ELF check of `/bin/ls` confirmed `x86-64`. All four available tags (`latest`, `1`, `1.12`, `1.12.2`) resolve to the same broken index. No usable arm64 build at accessible paths.

NVAIE path (`nvcr.io/nvaie/`) returns HTTP 402 — separate NVIDIA account action required.

---

## Outstanding

- [ ] Gary to file NGC support ticket with manifest digest evidence
- [ ] Gary to contact NVIDIA account team re: NVAIE path 402
- [ ] VRS unit file preserved on `feat/nim-deployments-a-c` for when a genuine arm64 build becomes available
- [ ] Re-pull once NVIDIA ships corrected image — must pass new two-stage ELF gate (`fix/nim-pull-arm64-verification`)
