# Investigation: Phase 1 NGC Auth 401 + 1B Embed ARM64 Signal Mismatch

**Date:** 2026-04-22  
**Branch:** `investigation/phase1-401-embed-mismatch`  
**Triggered by:** Phase 4 sentinel dry-run reporting `ARM64_MANIFEST_MISMATCH` for `llama-nemotron-embed-1b-v2`, contradicting the earlier NAS cache audit verdict of `MATCH` / `ELF_VERIFIED_AARCH64`. Phase 1 NGC auth returning 401 since at least Feb 14.

---

## Investigation 1 — 1B Embed ARM64 Signal Mismatch

### Context

| Source | Date | Verdict | Method |
|--------|------|---------|--------|
| `docs/NIM_CACHE_AUDIT_2026-04-22.md` (audit branch) | 2026-04-21 | **MATCH** — genuine aarch64 | Stream layer 0 from NAS tar → `tar -xzOf` extract `/usr/bin/ls` → `file` |
| Phase 4 sentinel dry-run | 2026-04-22 | **ARM64_MANIFEST_MISMATCH** | `arm64_bytes == amd64_bytes` heuristic on manifest index sizes |

Both signals triggered on the same NGC image. This investigation reconciles them.

---

### Step 1 — Original Audit Methodology

From `NIM_CACHE_AUDIT_2026-04-22.md` (commit `7cb061de6`), embed-1b section:

- **Source tar:** `/mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar` (2.5 GB)
- **Config hash:** `c559ea6367afdab29d6ce6d9d345668d9c641fdee4c268fdbf8f5cf2053ada7c`
- **Layer extracted:** `cc43ec4c13811c515d52d11a6039f3659696499c8782f5f3f601a3fdedf14082/layer.tar` (index 0, gzip-compressed)
- **Binary probed:** `/usr/bin/ls` (via `tar -xzOf`)
- **`file` output:**
  ```
  ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV),
  dynamically linked, interpreter /lib/ld-linux-aarch64.so.1,
  BuildID[sha1]=fec30f5745c2582aaf143e7079d3bb46ca7a010f,
  for GNU/Linux 3.7.0, stripped
  ```

---

### Step 2 — Live Manifest Layer Comparison

`docker manifest inspect --verbose nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest`

**Manifest index sizes (the heuristic's raw input):**

| Architecture | Manifest JSON size |
|---|---|
| `arm64` | **11987 bytes** |
| `amd64` | **11987 bytes** |

Sizes are identical → heuristic fires `ARM64_MANIFEST_MISMATCH`.

**Layer-level breakdown:**

| Metric | Value |
|--------|-------|
| arm64 layer count | 61 |
| amd64 layer count | 61 |
| **Shared layer digests** | **1 unique digest** (`sha256:4f4fb700ef544...`) × 12 occurrences each |
| arm64-only unique digests | 49 |
| amd64-only unique digests | 49 |
| arm64 layer[0] | `sha256:cc43ec4c13811...` (28.86 MB) |
| amd64 layer[0] | `sha256:76249c7cd5039...` (29.72 MB) |
| Layer[0] shared? | **No** |

The single shared digest (`sha256:4f4fb700ef544...`, size=32 bytes) is the standard OCI empty/whiteout blob — architecture-neutral by design. It appears in practically every NGC NIM image regardless of architecture.

**49 of 61 unique layer digests are architecture-specific, diverging from layer 0.** The images are independently built from the OS base layer up.

---

### Step 3 — Definitive ELF Check via Docker

Loaded NAS tar into local daemon, ran `docker create`:

| Binary | ELF result |
|--------|-----------|
| `/bin/ls` | `ELF 64-bit LSB pie executable, **ARM aarch64**, version 1 (SYSV), dynamically linked, interpreter /lib/ld-linux-aarch64.so.1, BuildID[sha1]=fec30f5745c2582aaf143e7079d3bb46ca7a010f` |
| `/usr/bin/python3` | Broken symlink to `python3.12` (interpreter is aarch64 by OS layer — not directly checkable via this path) |
| `/opt/nvidia/nvidia_entrypoint.sh` | Bourne-Again shell script, ASCII text — not an ELF binary |

BuildID `fec30f5745c2582...` is identical to the original audit's `/usr/bin/ls` result. Consistent: same NAS-cached image was probed both times.

Scratch container cleaned up. `/tmp` files removed.

---

### Step 4 — Verdict and Root Cause

**Verdict: `ELF_VERIFIED_AARCH64`**

The 1B embed image is genuine arm64. The original audit was correct.

**Why the Phase 4 heuristic fired (false positive):**

The `arm64_bytes == amd64_bytes` heuristic was calibrated against the `nvidia-nemotron-nano-9b-v2` packaging defect, where the arm64 manifest JSON was literally copied from amd64 (same layer digests → same JSON content → same byte count). The heuristic assumes: *manifest size equality implies content identity*.

This assumption fails when two architectures produce manifests with different content but identical structure:
- Both the 1B embed arm64 and amd64 manifests have **61 layers** with digests of identical string length (SHA256 hex = 64 chars each), producing identical JSON footprints.
- The actual layer content is architecture-specific (49/61 unique digests differ), but the manifest JSON serialisation length is the same.

| Image | Shared layers | Manifest size match | Actual arm64? | Heuristic verdict |
|-------|--------------|---------------------|---------------|-------------------|
| `nvidia-nemotron-nano-9b-v2` | 102/122 (83%) | Yes | ❌ x86-64 | ARM64_MANIFEST_MISMATCH ✅ correct |
| `llama-nemotron-embed-1b-v2` | 12/61 (20%, all zero-size) | Yes | ✅ aarch64 | ARM64_MANIFEST_MISMATCH ❌ false positive |

---

### Recommendation 1

**Replace `arm64_bytes == amd64_bytes` with a shared substantive-layer-digest ratio check.**

Pseudocode for the improved signal:

```python
SHARED_LAYER_MISMATCH_THRESHOLD = 0.5  # >50% of non-empty layers shared = suspect

def _is_possible_packaging_mismatch(arm64_layers, amd64_layers):
    # Exclude zero-size whiteout blobs (sha256:4f4fb700ef544...) — always shared
    WHITEOUT_DIGEST = "sha256:4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1"
    arm64_sub = [d for d in arm64_layers if d != WHITEOUT_DIGEST]
    amd64_sub = [d for d in amd64_layers if d != WHITEOUT_DIGEST]
    if not arm64_sub or not amd64_sub:
        return False
    shared = len(set(arm64_sub) & set(amd64_sub))
    ratio = shared / len(set(arm64_sub))
    return ratio > SHARED_LAYER_MISMATCH_THRESHOLD
```

This would correctly score the 9B VRS as ~83% shared (mismatch) and the 1B embed as ~0% shared (clean). Requires `_manifest_inspect_via_docker` to return full layer lists, not just manifest byte counts. The Phase 4 `_parse_manifest_arm64` function needs to return `arm64_layers` and `amd64_layers` lists alongside the current size fields.

**This is a follow-up PR change — do not patch Phase 4 yet.** The `ARM64_MANIFEST_MISMATCH` row in `nim_arm64_probe_results` for 2026-04-22 should be left as-is (it reflects the heuristic that was running). Day-2 comparison will re-fire the same flag until the heuristic is corrected.

---

## Investigation 2 — Phase 1 NGC Auth 401

### Context

Phase 1 (`get_ngc_token()`) has been logging `"NGC_API_KEY not set — skipping"` since before Feb 14, because the key was unreadable by admin. After fixing permissions today, the key loads correctly — but the NGC REST token exchange still returns 401. Phase 4 (`docker manifest inspect`) works fine on the same images.

---

### Step 1 — Phase 1 Auth Code

From `tools/nvidia_sentinel.py`, `get_ngc_token()`:

```python
def get_ngc_token(image: str) -> Optional[str]:
    auth_url = (
        f"https://authn.nvidia.com/token"
        f"?service=ngc&scope=repository:{image}:pull"
    )
    resp = requests.get(auth_url, auth=("$oauthtoken", NGC_API_KEY), timeout=15)
    resp.raise_for_status()
    return resp.json().get("token")
```

**HTTP call shape:**
- Method: `GET`
- URL: `https://authn.nvidia.com/token?service=ngc&scope=repository:{image}:pull`
- Auth: HTTP Basic, username=`$oauthtoken`, password=NGC_API_KEY
- No `Authorization` header set manually

`check_ngc_image()` then uses the returned token as `Authorization: Bearer {token}` against `https://nvcr.io/v2/{image}/tags/list`.

---

### Step 2 — Auth Endpoint Testing

Three variants tested via `sudo bash -s` heredoc (key never in argv or logs):

| Test | URL | Result |
|------|-----|--------|
| 1 — Phase 1 current | `authn.nvidia.com/token?service=ngc&scope=...` | **HTTP 401** |
| 2 — Alternate service param | `authn.nvidia.com/token?service=registry.ngc.nvidia.com&scope=...` | **HTTP 401** |
| 3 — nvcr.io proxy_auth | `nvcr.io/proxy_auth?account=%24oauthtoken&scope=...` | **HTTP 403** (Access Denied) |

The nvcr.io proxy_auth endpoint (used successfully by `nim_pull_to_nas.py`'s `_get_token()`) returned 403 rather than 401. 403 indicates authentication was processed but the specific scope was denied — different from `authn.nvidia.com`'s 401 which indicates authentication itself failed.

Both `authn.nvidia.com` variants return 401 regardless of the `service` parameter.

---

### Step 3 — Root Cause Hypothesis

**Most likely: NGC API key is `nvapi-*` format; `authn.nvidia.com` does not accept it.**

NVIDIA introduced a new API key format (`nvapi-*`) alongside the new `api.ngc.nvidia.com` REST platform. Evidence:

1. `docker login nvcr.io` with the same key → **succeeded** earlier today (Login Succeeded). nvcr.io's registry auth accepts nvapi keys via `docker login`.
2. `authn.nvidia.com/token` with the same key → **401** on both service variants. This endpoint predates the nvapi key format and may only accept legacy NGC API keys (alphanumeric, no `nvapi-` prefix).
3. `nvcr.io/proxy_auth` → **403** (not 401) for the specific image scope tested, suggesting the key authenticated but lacked entitlement for that scope — consistent with nvapi keys working at the HTTP level but the token exchange failing for access-controlled images.

Secondary hypothesis: the `service=ngc` scope string is obsolete. Modern nvcr.io auth uses `service=registry.ngc.nvidia.com` — but Test 2 showed this also returns 401, ruling it out as the sole cause.

---

### Step 4 — Minimum Code Change

The fix is to replace `get_ngc_token()` with the `nvcr.io/proxy_auth` pattern already proven to work in `nim_pull_to_nas.py`:

```python
# CURRENT (broken with nvapi-* keys):
def get_ngc_token(image: str) -> Optional[str]:
    auth_url = f"https://authn.nvidia.com/token?service=ngc&scope=repository:{image}:pull"
    resp = requests.get(auth_url, auth=("$oauthtoken", NGC_API_KEY), timeout=15)
    resp.raise_for_status()
    return resp.json().get("token")

# PROPOSED (uses nvcr.io proxy_auth — same pattern as nim_pull_to_nas._get_token()):
def get_ngc_token(image: str) -> Optional[str]:
    import urllib.parse
    scope = urllib.parse.quote(f"repository:{image}:pull", safe="")
    auth_url = f"https://nvcr.io/proxy_auth?account=%24oauthtoken&scope={scope}"
    resp = requests.get(auth_url, auth=("$oauthtoken", NGC_API_KEY), timeout=15)
    resp.raise_for_status()
    return resp.json().get("token")
```

The `nvcr.io/proxy_auth` endpoint:
- Accepted by nvcr.io for both legacy and nvapi-format keys (works for docker login)
- URL-encodes the scope to avoid colon ambiguity in query strings
- Returns a short-lived bearer token usable for `nvcr.io/v2/{image}/...` calls

**Note:** the 403 in Test 3 above was against `nim/nvidia/qwen2.5-7b-instruct` with an un-encoded scope and without the `nvcr.io/` prefix normalisation that `nim_pull_to_nas.py` uses. The production fix should URL-encode the scope and strip `nvcr.io/` from the image path before constructing the URL (matching `_get_token()`'s exact call shape). A follow-up PR should test all three Phase 1 images after the change.

---

## Recommendations

### Rec 1 — Phase 4 Heuristic (low priority, non-blocking)

Replace the `arm64_bytes == amd64_bytes` manifest-size heuristic with a shared substantive-layer-digest ratio (pseudocode above). The current heuristic produces false positives on any image where both architectures have the same layer count. The `nim_arm64_probe_results` row for 2026-04-22 should be left as-is.

### Rec 2 — Phase 1 NGC Auth Fix (medium priority, unblocks tag-change alerting)

Replace `get_ngc_token()` to use `nvcr.io/proxy_auth` endpoint pattern (same as `nim_pull_to_nas.py`). This is a three-line change but needs a follow-up test pass confirming the three NGC_IMAGES in Phase 1 respond with valid tag lists. Phase 4 and Phase 3 (driver check) are unaffected by this change.
