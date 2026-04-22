# NGC ARM64 NIM Discovery — 2026-04-22

**Branch:** `audit/nim-cache-arm64-verification-2026-04-22`  
**Scope:** Find genuine aarch64 / Grace-Hopper NIM builds for the three Fortress target models  
**Auth path used:** Existing `nvcr.io` session on spark-4 (`192.168.0.106`) via `sudo docker manifest inspect`

---

## Summary

| Model | Genuine arm64 in `nvcr.io/nim/nvidia/`? | Best Available Tag | arm64 Manifest Digest |
|-------|----------------------------------------|--------------------|-----------------------|
| `nvidia-nemotron-nano-9b-v2` | ❌ **NO** — packaging bug, all tags broken | None usable | `sha256:a8ec96...` (mislabeled) |
| `nemotron-nano-12b-v2-vl` | ✅ Yes — `latest` / `1.6.0` | `:1.6.0` | `sha256:e4e771dfa7b98b4a648ec13c0667e9a42f00b386a1b355f2a250640d6d68ebbd` |
| `llama-nemotron-embed-1b-v2` | ✅ Yes — `latest` / `1.13.0` | `:1.13.0` | `sha256:3b7fb0f2a14b585a9b3a13a66943be682971cf61bd79d55fabd17aca8331c471` |

---

## Per-Model Detail

### 1. `nvidia-nemotron-nano-9b-v2` — ❌ No genuine arm64 available

**Tags enumerated:** `latest`, `1`, `1.12`, `1.12.2` — all four resolve to the same index digest.

**Platforms per manifest index:**
```
linux/amd64   — sha256:bdd975...  (23344 bytes)
linux/arm64   — sha256:a8ec96...  (23344 bytes)  ← identical byte size — red flag
unknown/unknown × 2  (attestation blobs, normal)
```

**Layer-level analysis of arm64 vs amd64 sub-manifests:**

| Layer range | Count | Status |
|-------------|-------|--------|
| Layers 0–101 | 102 | **IDENTICAL digests** — same x86-64 CUDA base, CUDA runtime (3.2 GB layer), NIM framework, model weights |
| Layers 102–121 | 20 | Different — NIM config/script tail layers only |
| **Total shared** | **102 / 122** | **83% of layers are x86-64 binaries shared verbatim** |

The arm64 and amd64 sub-manifests are also byte-for-byte identical in size (23344 bytes each), consistent with the arm64 entry being copied from the amd64 manifest with only the tail layer section swapped.

**Alternate paths checked:**

| Path | Result |
|------|--------|
| `nvcr.io/nvaie/nvidia/nvidia-nemotron-nano-9b-v2:latest` | **HTTP 402 Payment Required** — image may exist but requires higher NVAIE entitlement tier |
| `nvcr.io/nvidia/nim/nvidia-nemotron-nano-9b-v2:latest` | Access Denied |
| `nvcr.io/ngc/nvidia/nvidia-nemotron-nano-9b-v2:latest` | Access Denied |
| Variant tags: `grace-hopper`, `gh200`, `aarch64`, `1.0.0-grace-hopper`, etc. | All: "no such manifest" |

**Recommendation:**
1. File an NGC support ticket with evidence: arm64 sub-manifest digest `sha256:a8ec96dc...`, layer overlap proof (102/122 shared), and exec format error on aarch64 host. Reference NVAIE entitlement.
2. Investigate whether `nvcr.io/nvaie/nvidia/` contains a corrected build — requires escalating the NGC API key to NVAIE tier or contacting NVIDIA account team.
3. VRS concierge (`fortress-nim-vrs-concierge.service`) is **blocked** until a genuine arm64 build is confirmed and re-pulled to NAS.

---

### 2. `nemotron-nano-12b-v2-vl` — ✅ Genuine arm64 confirmed

**Tags enumerated:** `latest`/`1`/`1.6`/`1.6.0` (same digest), `1.5`/`1.5.0` (older digest)

**Platforms in `latest` / `1.6.0`:**
```
linux/arm64   — sha256:e4e771dfa7b98b4a648ec13c0667e9a42f00b386a1b355f2a250640d6d68ebbd  (14968 bytes)
linux/amd64   — sha256:f926731...  (14965 bytes)
```

**Layer-level analysis (`1.6.0` arm64 vs amd64):**
- Layer 0: `b8a35db4...` (arm64) vs `4b3ffd8...` (amd64) — **diverge from the very first layer** (separate Ubuntu base images)
- 69 of 75 layers differ across architectures
- Only 6 shared layers (all are the `4f4fb700...` empty whiteout blobs, architecture-neutral)
- **Confirmed: independent aarch64 build from the OS layer up**

**Cross-check with NAS cache:**  
The NAS tar (`latest/image.tar`) was verified as genuine aarch64 in Track 1 (ELF check: `ARM aarch64`). The NAS-cached image corresponds to the `1.6.0` / `latest` arm64 build. **NAS tar is valid. No re-pull needed.**

**Deployment path:** `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:1.6.0`  
Pin tag for unit file: `:sha-33032f00aed9` (current pinning is correct — manifest digest was a genuine arm64 arm64 at pull time)

---

### 3. `llama-nemotron-embed-1b-v2` — ✅ Genuine arm64 confirmed

**Tags enumerated:** `latest`/`1`/`1.13`/`1.13.0` — all resolve to the same digest

**Platforms in `latest` / `1.13.0`:**
```
linux/arm64   — sha256:3b7fb0f2a14b585a9b3a13a66943be682971cf61bd79d55fabd17aca8331c471  (11987 bytes)
linux/amd64   — sha256:34fc9b...  (11987 bytes)
```

Note: identical byte size in the platform sub-manifests (same as the VRS model red flag). However, Track 1 ELF verification confirms the NAS-cached version IS genuine aarch64 — NVIDIA apparently fixed the issue for this model (or built it correctly to begin with) despite the same outer index structure.

**Layer-level analysis (`1.13.0` arm64 vs amd64):**
- Layer 0: `cc43ec4c...` (28.8 MB, arm64) vs `76249c7c...` (29.7 MB, amd64) — diverge from layer 0
- 49 of 61 substantive layers differ
- Only 12 shared layers (all `4f4fb700...` empty whiteout blobs)
- **Confirmed: independent aarch64 build**

**Cross-check with NAS cache:**  
NAS tar verified as genuine aarch64 in Track 1. **NAS tar is valid. No re-pull needed.**

---

## Tag Universe (Complete)

| Model | All Tags | Notes |
|-------|----------|-------|
| `nvidia-nemotron-nano-9b-v2` | `latest`, `1`, `1.12`, `1.12.2` | All broken — same index |
| `nemotron-nano-12b-v2-vl` | `latest`, `1`, `1.6`, `1.6.0`, `1.5`, `1.5.0` | All valid arm64; use `1.6.0` |
| `llama-nemotron-embed-1b-v2` | `latest`, `1`, `1.13`, `1.13.0` | All valid arm64; use `1.13.0` |

No `grace-hopper`, `gh200`, `aarch64`, `ea`, or `dev` variant tags exist for any model.

---

## Alternate NGC Org Paths

| Org prefix | Result for all three models |
|------------|-----------------------------|
| `nvcr.io/nim/nvidia/` | As above — mix of valid and broken |
| `nvcr.io/nvaie/nvidia/` | HTTP 402 for all models — NVAIE entitlement required |
| `nvcr.io/nvidia/nim/` | Access Denied |
| `nvcr.io/ngc/nvidia/` | Access Denied |

---

## Recommendations

### Immediate (unblocked)
- **Deployment C (spark-3, vision concierge):** Proceed. NAS tar for `nemotron-nano-12b-v2-vl` is genuine arm64. No re-pull needed.
- **Embed model:** NAS tar is valid. Proceed when scheduled.

### Blocked — requires resolution
- **Deployment A (spark-4, VRS concierge):** Blocked on `nvidia-nemotron-nano-9b-v2`. No usable arm64 build at accessible paths.

### Actions for Gary
1. **File NGC support ticket** for `nvidia-nemotron-nano-9b-v2` arm64 packaging bug. Evidence: arm64 sub-manifest `sha256:a8ec96dc`, 102/122 layers shared with amd64, exec format error on aarch64 host (DGX Spark, kernel `aarch64`).
2. **Contact NVIDIA account team** re: `nvcr.io/nvaie/nvidia/nvidia-nemotron-nano-9b-v2` — the 402 response suggests a build exists at the NVAIE tier. Confirm availability and whether current NVAIE subscription covers access.
3. **Delete NAS tar** for `nvidia-nemotron-nano-9b-v2` (8.1 GB, confirmed x86-64): `/mnt/fortress_nas/nim-cache/nim/nvidia-nemotron-nano-9b-v2/latest/` — confirm greenlight and Claude Code will execute.
4. **Clean spark-4 Docker daemon** of the loaded mislabeled image (`:latest` and `:sha-3e20559d2fe1`) once NAS tar is deleted.
