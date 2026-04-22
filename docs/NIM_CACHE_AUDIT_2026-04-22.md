# NIM Cache Architecture Audit — 2026-04-22

**Branch:** `audit/nim-cache-arm64-verification-2026-04-22`  
**Triggered by:** `exec format error` on spark-4 when starting `fortress-nim-vrs-concierge.service`  
**Method:** Config JSON arch claim vs. actual ELF binary check on extracted layer content

---

## Summary Table

| Model | NAS Tar | Config Arch | Binary ELF | Verdict |
|-------|---------|-------------|------------|---------|
| `nvidia-nemotron-nano-9b-v2` | `nim-cache/nim/nvidia-nemotron-nano-9b-v2/latest/image.tar` (8.1 GB) | `arm64 / linux` | **x86-64** | ❌ MISMATCH |
| `nemotron-nano-12b-v2-vl` | `nim-cache/nim/nemotron-nano-12b-v2-vl/latest/image.tar` (9.8 GB) | `arm64 / linux` | **aarch64** | ✅ MATCH |
| `llama-nemotron-embed-1b-v2` | `nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar` (2.5 GB) | `arm64 / linux` | **aarch64** | ✅ MATCH |

---

## Per-Image Detail

### 1. `nvidia-nemotron-nano-9b-v2` — ❌ MISMATCH

**NAS path:** `/mnt/fortress_nas/nim-cache/nim/nvidia-nemotron-nano-9b-v2/latest/`  
**Tar size:** 8.1 GB  
**Pulled:** 2026-04-21 via `nim_pull_to_nas.py`

**Config JSON (`b48103d2cf3aa08b7fcb6f3cd6ba65aa41d6d36d5ec82e364cc1d5467a3ae66c.json`):**
```
architecture: arm64
os:           linux
variant:      (null)
```

**ELF check** (`/bin/ls` via `docker cp` from existing load on spark-4):
```
ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV),
dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2,
BuildID[sha1]=3eca7e3905b37d48cf0a88b576faa7b95cc3097b,
for GNU/Linux 3.2.0, stripped
```

**`image.sha256`:** `3e20559d2fe1603e4c2683eeb3a13b6e032a8b6f1ebb0de15ddbe902aafc0bb4`

**Root cause (from Track 2 layer analysis):**  
102 of 122 layers in the NGC `arm64` sub-manifest are byte-for-byte identical to the `amd64` sub-manifest, including the 3.2 GB CUDA runtime layer (`sha256:4a39b63a...`). Only the final 20 tail layers differ. NVIDIA's arm64 manifest entry for this model is a packaging bug — the bulk of the image (OS, CUDA, NIM base, model weights) was never compiled for aarch64.

**Status:** Loaded on spark-4 as `:latest` and `:sha-3e20559d2fe1`. Unit file installed but disabled.  
**NAS tar action:** Flagged for deletion — awaiting Gary greenlight. (8.1 GB of confirmed x86-64 content is no-op on an aarch64 cluster.)

---

### 2. `nemotron-nano-12b-v2-vl` — ✅ MATCH

**NAS path:** `/mnt/fortress_nas/nim-cache/nim/nemotron-nano-12b-v2-vl/latest/`  
**Tar size:** 9.8 GB  
**Pulled:** 2026-04-21 via `nim_pull_to_nas.py`

**Config JSON (`f63af248c481147a8a9fd4b69df01e0b3f637c6b6ef55e29912101a4d8674ef9.json`):**
```
architecture: arm64
os:           linux
variant:      (null)
```

**ELF check** (`/usr/bin/ls` extracted from layer `b8a35db4.../layer.tar`, index 0, gzip-compressed):
```
ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV),
dynamically linked, interpreter /lib/ld-linux-aarch64.so.1,
BuildID[sha1]=19a53698c72a1d765f961ccd04bff6665434c0f5,
for GNU/Linux 3.7.0, stripped
```

**`image.sha256`:** `33032f00aed954b6d479b9223485eb389e147bb7e76e4a6187339fbbf112a80e`

**Root cause (from Track 2):** The NGC `1.6.0`/`latest` arm64 manifest has a distinct base layer from amd64 from layer 0 (`b8a35db4...` vs `4b3ffd8...`). 69 of 75 layers differ between architectures, confirming a genuine separate aarch64 build.

**Status:** Not loaded on any node. NAS tar is valid for Deployment C (spark-3, `:8101`).  
**NAS tar action:** Retain. Ready to deploy.

---

### 3. `llama-nemotron-embed-1b-v2` — ✅ MATCH

**NAS path:** `/mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/`  
**Tar size:** 2.5 GB  
**Pulled:** 2026-04-21 via `nim_pull_to_nas.py`

**Config JSON (`c559ea6367afdab29d6ce6d9d345668d9c641fdee4c268fdbf8f5cf2053ada7c.json`):**
```
architecture: arm64
os:           linux
variant:      (null)
```

**ELF check** (`/usr/bin/ls` extracted from layer `cc43ec4c.../layer.tar`, index 0, gzip-compressed):
```
ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV),
dynamically linked, interpreter /lib/ld-linux-aarch64.so.1,
BuildID[sha1]=fec30f5745c2582aaf143e7079d3bb46ca7a010f,
for GNU/Linux 3.7.0, stripped
```

**`image.sha256`:** `f07afc8f7b59c5e9668681ad2fed54313af74ce0df6ffd261549efb091768fc6`

**Root cause (from Track 2):** Base layer `cc43ec4c...` (28.8 MB) diverges from amd64 base `76249c7c...` (29.7 MB) at layer 0. 49 of 61 substantive layers are architecture-distinct. Genuine aarch64 build confirmed.

**Status:** Not loaded on any node. NAS tar is valid.  
**NAS tar action:** Retain.

---

## Methodology Notes

- Images 2 and 3 were not docker-loaded for the audit. ELF check performed by streaming layer 0 out of each NAS tar (`tar -xOf outer.tar layer.tar | tar -xzOf - ./usr/bin/ls`) — faster and avoids unnecessary NAS-to-Docker-daemon traffic.
- Image 1 was already loaded on spark-4 from the failed deployment attempt; `docker create`/`docker cp` used.
- The `nim_pull_to_nas.py` script correctly selected the NGC arm64 sub-manifest digest for all three images. The bug is in NVIDIA's NGC packaging for `nvidia-nemotron-nano-9b-v2`, not in the pull script.
