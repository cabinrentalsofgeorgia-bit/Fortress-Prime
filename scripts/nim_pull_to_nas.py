#!/usr/bin/env python3
"""
nim_pull_to_nas.py — Pull NIM Docker container images to NAS, bypassing
Docker daemon TLS issues with nvcr.io on DGX Spark ARM64.

Creates a Docker-compatible tar archive at:
  /mnt/fortress_nas/nim-cache/nim/<model>/<tag>/image.tar

Which can be loaded on any node via:
  docker load < /mnt/fortress_nas/nim-cache/nim/<model>/<tag>/image.tar

Two-stage ARM64 verification gate (both must pass before NAS commit):
  Stage 1 — Manifest gate:  arm64 platform entry present in manifest index.
  Stage 2 — ELF gate:       layer-0 binary is aarch64 (catches mislabeled images).

Usage:
  python3 scripts/nim_pull_to_nas.py <model-name> [--tag TAG]
  python3 scripts/nim_pull_to_nas.py <model-name> --force-skip-verification  # emergency only
  python3 scripts/nim_pull_to_nas.py --verify-only <path/to/image.tar>       # audit existing NAS tar

Examples:
  python3 scripts/nim_pull_to_nas.py llama-nemotron-embed-1b-v2
  python3 scripts/nim_pull_to_nas.py nemotron-nano-12b-v2-vl --tag 1.6.0
  python3 scripts/nim_pull_to_nas.py --verify-only /mnt/fortress_nas/nim-cache/nim/nemotron-nano-12b-v2-vl/latest/image.tar

NGC_API_KEY is read from /etc/fortress/nim.env (root-owned, 600 perms).
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import requests

NAS_BASE = Path("/mnt/fortress_nas/nim-cache/nim")
NIM_ORG = "nim/nvidia"
REGISTRY = "https://nvcr.io"
ENV_FILE = Path("/etc/fortress/nim.env")

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Verification types
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    stage1_manifest_arm64: bool = False
    stage2_elf_aarch64: bool = False
    probe_binary_elf: str = ""
    verdict: Literal["PASS", "MANIFEST_FAIL", "ELF_FAIL", "ERROR"] = "ERROR"
    evidence: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ELF helpers (pure Python, no docker required)
# ---------------------------------------------------------------------------

def _parse_elf_is_aarch64(file_output: str) -> bool:
    """Return True iff `file` output describes an ARM aarch64 ELF binary."""
    lower = file_output.lower()
    return "arm aarch64" in lower or "aarch64" in lower


def _extract_binary_from_layer_bytes(
    layer_bytes: bytes,
    candidates: tuple[str, ...] = (
        "./bin/ls", "./usr/bin/ls", "bin/ls", "usr/bin/ls",
    ),
) -> bytes:
    """
    Extract the first available candidate binary from a gzip-compressed OCI
    layer blob.  Returns empty bytes if extraction fails or layer is malformed.
    """
    for candidate in candidates:
        try:
            buf = io.BytesIO(layer_bytes)
            with gzip.GzipFile(fileobj=buf) as gz:
                with tarfile.open(fileobj=gz) as tf:
                    try:
                        member = tf.getmember(candidate)
                        fobj = tf.extractfile(member)
                        if fobj:
                            return fobj.read()
                    except KeyError:
                        continue
        except Exception:
            continue
    return b""


def _check_layer_elf(layer_bytes: bytes) -> tuple[bool, str]:
    """
    Extract a probe binary from an OCI layer blob and run ``file`` on it.

    Returns ``(is_aarch64, file_output_string)``.  Temp file is always
    cleaned up regardless of outcome.
    """
    binary_data = _extract_binary_from_layer_bytes(layer_bytes)
    if not binary_data:
        return False, "UNKNOWN — could not extract probe binary from layer"

    suffix = uuid.uuid4().hex[:8]
    tmp_path = Path(tempfile.gettempdir()) / f"nim-elf-probe-{suffix}"
    try:
        tmp_path.write_bytes(binary_data)
        result = subprocess.run(
            ["file", str(tmp_path)],
            capture_output=True, text=True, timeout=10,
        )
        elf_output = result.stdout.strip()
        if ": " in elf_output:
            elf_output = elf_output.split(": ", 1)[1]
        return _parse_elf_is_aarch64(elf_output), elf_output
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# verify_arm64_with_docker — standalone docker-based probe (for probe tool)
# ---------------------------------------------------------------------------

def verify_arm64_with_docker(
    image_ref: str,
    *,
    _run: Callable = subprocess.run,
) -> VerificationResult:
    """
    Two-stage ARM64 verification using the docker CLI.

    Stage 1: ``docker manifest inspect`` — arm64 platform entry present.
    Stage 2: ``docker pull`` → ``docker create`` → ``docker cp /bin/ls`` →
             ``file`` — ELF architecture is aarch64.

    All scratch containers/tags/temp files are cleaned up in a finally block
    regardless of outcome.  Suitable for use in standalone probe tooling;
    the pull script uses inline verification instead to avoid a double download.
    """
    result = VerificationResult()
    scratch_tag = f"fortress-verify-{uuid.uuid4().hex[:8]}"
    container_id: str | None = None
    tmp_path: Path | None = None

    try:
        # --- Stage 1: manifest inspect ---
        r1 = _run(
            ["docker", "manifest", "inspect", image_ref],
            capture_output=True, text=True, timeout=30,
        )
        if r1.returncode != 0:
            result.verdict = "ERROR"
            result.evidence = {"stage1_error": r1.stderr.strip()}
            return result

        try:
            index = json.loads(r1.stdout)
        except json.JSONDecodeError as exc:
            result.verdict = "ERROR"
            result.evidence = {"stage1_error": f"JSON parse failed: {exc}"}
            return result

        arm64_digest: str | None = None
        platforms: list[str] = []
        if "manifests" in index:
            for m in index["manifests"]:
                plat = m.get("platform", {})
                arch = plat.get("architecture", "")
                os_name = plat.get("os", "")
                if os_name not in ("unknown", None, ""):
                    platforms.append(f"{os_name}/{arch}")
                if arch == "arm64" and os_name == "linux":
                    arm64_digest = m.get("digest")
        elif index.get("architecture") == "arm64":
            arm64_digest = image_ref

        result.stage1_manifest_arm64 = arm64_digest is not None
        result.evidence["stage1_arm64_digest"] = arm64_digest
        result.evidence["stage1_platforms"] = platforms

        if not result.stage1_manifest_arm64:
            result.verdict = "MANIFEST_FAIL"
            return result

        # --- Stage 2: docker pull → create → cp → file ---
        pull_ref = arm64_digest if (arm64_digest and arm64_digest != image_ref) else image_ref
        r_pull = _run(
            ["docker", "pull", "--platform", "linux/arm64", pull_ref],
            capture_output=True, text=True, timeout=300,
        )
        if r_pull.returncode != 0:
            result.verdict = "ERROR"
            result.evidence["stage2_pull_error"] = r_pull.stderr.strip()
            return result

        r_tag = _run(
            ["docker", "tag", pull_ref, scratch_tag],
            capture_output=True, text=True, timeout=30,
        )
        if r_tag.returncode != 0:
            result.verdict = "ERROR"
            result.evidence["stage2_tag_error"] = r_tag.stderr.strip()
            return result

        r_create = _run(
            ["docker", "create", scratch_tag],
            capture_output=True, text=True, timeout=60,
        )
        if r_create.returncode != 0:
            result.verdict = "ERROR"
            result.evidence["stage2_create_error"] = r_create.stderr.strip()
            return result
        container_id = r_create.stdout.strip()

        suffix = uuid.uuid4().hex[:8]
        tmp_path = Path(tempfile.gettempdir()) / f"nim-elf-docker-probe-{suffix}"
        cp_ok = False
        for probe_src in ("/bin/ls", "/usr/bin/ls"):
            r_cp = _run(
                ["docker", "cp", f"{container_id}:{probe_src}", str(tmp_path)],
                capture_output=True, text=True, timeout=30,
            )
            if r_cp.returncode == 0:
                cp_ok = True
                break

        if not cp_ok:
            result.verdict = "ERROR"
            result.evidence["stage2_cp_error"] = "could not copy /bin/ls or /usr/bin/ls"
            return result

        r_file = _run(
            ["file", str(tmp_path)],
            capture_output=True, text=True, timeout=10,
        )
        elf_output = r_file.stdout.strip()
        if ": " in elf_output:
            elf_output = elf_output.split(": ", 1)[1]

        result.probe_binary_elf = elf_output
        result.evidence["stage2_elf"] = elf_output
        result.stage2_elf_aarch64 = _parse_elf_is_aarch64(elf_output)
        result.verdict = "PASS" if result.stage2_elf_aarch64 else "ELF_FAIL"
        return result

    finally:
        if container_id:
            _run(["docker", "rm", container_id],
                 capture_output=True, text=True, timeout=30)
        if scratch_tag:
            _run(["docker", "rmi", scratch_tag],
                 capture_output=True, text=True, timeout=30)
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# verify_nas_tar — audit an already-cached NAS tar (--verify-only mode)
# ---------------------------------------------------------------------------

def verify_nas_tar(tar_path: Path) -> VerificationResult:
    """
    Verify an existing NAS image.tar without pulling from the registry.

    Stage 1: read manifest.json + config JSON inside the tar for arch claim.
    Stage 2: extract layer-0 blob, run ELF check on probe binary.
    """
    result = VerificationResult()

    try:
        with tarfile.open(tar_path, "r") as outer:
            # Read manifest.json
            try:
                mf = outer.extractfile("manifest.json")
                if not mf:
                    raise KeyError
                manifests = json.load(mf)
            except (KeyError, json.JSONDecodeError) as exc:
                result.verdict = "ERROR"
                result.evidence = {"error": f"Cannot read manifest.json: {exc}"}
                return result

            if not manifests:
                result.verdict = "ERROR"
                result.evidence = {"error": "Empty manifest.json"}
                return result

            entry = manifests[0]
            config_name = entry.get("Config", "")
            layers = entry.get("Layers", [])

            # Stage 1: read image config for arch claim
            try:
                cf = outer.extractfile(config_name)
                if not cf:
                    raise KeyError
                config = json.load(cf)
                arch = config.get("architecture", "unknown")
                result.stage1_manifest_arm64 = arch == "arm64"
                result.evidence["stage1_config_arch"] = arch
                result.evidence["stage1_config_os"] = config.get("os", "unknown")
            except (KeyError, json.JSONDecodeError) as exc:
                result.verdict = "ERROR"
                result.evidence = {"error": f"Cannot read image config: {exc}"}
                return result

            if not result.stage1_manifest_arm64:
                result.verdict = "MANIFEST_FAIL"
                return result

            # Stage 2: extract layer-0 bytes, check ELF
            if not layers:
                result.verdict = "ERROR"
                result.evidence["error"] = "No layers in manifest"
                return result

            layer0_name = layers[0]
            try:
                lf = outer.extractfile(layer0_name)
                if not lf:
                    raise KeyError
                layer_bytes = lf.read()
            except KeyError as exc:
                result.verdict = "ERROR"
                result.evidence["error"] = f"Cannot read layer-0 {layer0_name}: {exc}"
                return result

        is_aarch64, elf_output = _check_layer_elf(layer_bytes)
        result.stage2_elf_aarch64 = is_aarch64
        result.probe_binary_elf = elf_output
        result.evidence["stage2_elf"] = elf_output
        result.evidence["stage2_layer"] = layer0_name
        result.verdict = "PASS" if is_aarch64 else "ELF_FAIL"
        return result

    except Exception as exc:
        result.verdict = "ERROR"
        result.evidence = {"error": str(exc)}
        return result


# ---------------------------------------------------------------------------
# Registry helpers (unchanged from original)
# ---------------------------------------------------------------------------

def _read_key() -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("NGC_API_KEY="):
                return line.split("=", 1)[1].strip()
    key = os.getenv("NGC_API_KEY", "")
    if not key:
        sys.exit("NGC_API_KEY not found in /etc/fortress/nim.env or environment")
    return key


def _get_token(sess: requests.Session, image: str, key: str) -> str:
    r = sess.get(
        f"{REGISTRY}/proxy_auth?account=%24oauthtoken"
        f"&scope=repository%3A{image}%3Apull",
        auth=("$oauthtoken", key), timeout=20,
    )
    r.raise_for_status()
    return r.json()["token"]


def _get_arm64_manifest(
    sess: requests.Session, image: str, tag: str
) -> tuple[str, dict]:
    """
    Returns (arm64_digest, manifest_dict).

    Fixes the original single-arch shortcut that silently accepted any
    architecture — now checks the config blob when the registry returns a
    bare manifest instead of an index.
    """
    r = sess.get(
        f"{REGISTRY}/v2/{image}/manifests/{tag}",
        headers={
            "Accept": (
                "application/vnd.oci.image.index.v1+json,"
                "application/vnd.docker.distribution.manifest.list.v2+json"
            )
        },
        timeout=20,
    )
    r.raise_for_status()
    idx = r.json()

    if "layers" in idx:
        # Single-arch manifest returned directly — verify architecture via config blob
        config_digest = idx.get("config", {}).get("digest", "")
        if config_digest:
            try:
                r_cfg = sess.get(
                    f"{REGISTRY}/v2/{image}/blobs/{config_digest}",
                    headers={"Accept": "application/vnd.oci.image.config.v1+json"},
                    timeout=20,
                )
                if r_cfg.status_code == 200:
                    cfg = r_cfg.json()
                    actual_arch = cfg.get("architecture", "unknown")
                    if actual_arch != "arm64":
                        sys.exit(
                            f"No arm64 manifest found. "
                            f"Registry returned single-arch manifest: {actual_arch}"
                        )
            except Exception as exc:
                log.warning("Could not verify single-arch manifest architecture: %s", exc)
        return tag, idx

    # Multi-arch index — find the arm64 entry
    arm64_digest = None
    for m in idx.get("manifests", []):
        if m.get("platform", {}).get("architecture") == "arm64":
            arm64_digest = m["digest"]
            break

    if not arm64_digest:
        archs = [
            m.get("platform", {}).get("architecture")
            for m in idx.get("manifests", [])
        ]
        sys.exit(f"No arm64 manifest found. Available: {archs}")

    r2 = sess.get(
        f"{REGISTRY}/v2/{image}/manifests/{arm64_digest}",
        headers={
            "Accept": (
                "application/vnd.oci.image.manifest.v1+json,"
                "application/vnd.docker.distribution.manifest.v2+json"
            )
        },
        timeout=20,
    )
    r2.raise_for_status()
    return arm64_digest, r2.json()


def _download_blob(
    sess: requests.Session,
    image: str,
    digest: str,
    expected_size: int,
    label: str,
) -> bytes:
    """Download a single blob with progress reporting."""
    url = f"{REGISTRY}/v2/{image}/blobs/{digest}"
    r = sess.get(url, timeout=300, stream=True)
    r.raise_for_status()

    buf = io.BytesIO()
    downloaded = 0
    chunk_size = 1024 * 1024
    t0 = time.time()

    for chunk in r.iter_content(chunk_size=chunk_size):
        buf.write(chunk)
        downloaded += len(chunk)
        if expected_size > 0:
            pct = downloaded / expected_size * 100
            mb = downloaded / 1e6
            speed = downloaded / (time.time() - t0 + 0.001) / 1e6
            print(
                f"\r  {label}: {mb:.0f}MB / {expected_size/1e6:.0f}MB "
                f"({pct:.0f}%) {speed:.1f}MB/s     ",
                end="", flush=True,
            )

    print()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main pull function
# ---------------------------------------------------------------------------

def pull_to_nas(
    model_name: str,
    tag: str = "latest",
    arch: str = "arm64",  # reserved; only arm64 is supported
    skip_verification: bool = False,
) -> Path:
    out_dir = NAS_BASE / model_name / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tar = out_dir / "image.tar"

    if out_tar.exists():
        size = out_tar.stat().st_size
        print(f"Already cached: {out_tar} ({size/1e9:.2f}GB)")
        return out_tar

    if skip_verification:
        warnings.warn(
            "ARM64 VERIFICATION BYPASSED via --force-skip-verification. "
            "This is an emergency escape hatch only. The cached image is NOT "
            "guaranteed to be genuine aarch64.",
            stacklevel=2,
        )
        log.warning(
            "!!! ARM64 verification skipped for %s:%s — FORCE flag active !!!",
            model_name, tag,
        )

    key = _read_key()
    image = f"{NIM_ORG}/{model_name}"

    sess = requests.Session()
    sess.headers.update({"User-Agent": "fortress-nim-pull/1.0"})

    print(f"Authenticating for {image}:{tag}...")
    token = _get_token(sess, image, key)
    sess.headers["Authorization"] = f"Bearer {token}"

    print("Fetching manifest...")
    digest, manifest = _get_arm64_manifest(sess, image, tag)
    layers = manifest.get("layers", [])
    config_descriptor = manifest.get("config", {})
    total_compressed = sum(layer.get("size", 0) for layer in layers)
    print(f"  {len(layers)} layers, {total_compressed/1e9:.2f}GB compressed")

    # Download config blob
    print(f"Downloading config ({config_descriptor.get('size', 0)} bytes)...")
    config_bytes = _download_blob(
        sess, image, config_descriptor["digest"],
        config_descriptor.get("size", 0), "config",
    )
    config_hash = config_descriptor["digest"].replace("sha256:", "")

    # Download layer 0 first for ELF gate
    if not layers:
        sys.exit("Manifest has no layers — cannot proceed.")

    layer0 = layers[0]
    layer0_digest = layer0["digest"].replace("sha256:", "")
    print(f"Downloading layer 1/{len(layers)} for ELF verification...")
    layer0_data = _download_blob(
        sess, image, layer0["digest"], layer0.get("size", 0), "layer 1",
    )

    # --- Stage 2 ELF gate (inline, avoids re-download) ---
    elf_output = "SKIPPED"
    if not skip_verification:
        print("Running Stage 2 ELF verification on layer 0...")
        is_aarch64, elf_output = _check_layer_elf(layer0_data)
        if not is_aarch64:
            raise RuntimeError(
                f"\nARM64 ELF verification FAILED for {model_name}:{tag}\n"
                f"Layer-0 ELF: {elf_output}\n"
                f"This image has {elf_output.split(',')[0] if ',' in elf_output else elf_output} "
                f"binaries despite claiming arm64 in its manifest.\n"
                f"NGC packaging defect — refusing to cache. "
                f"Use --force-skip-verification only in emergencies."
            )
        print(f"  ELF PASS: {elf_output}")

    # Download remaining layers
    layer_digests = [layer0_digest]
    layer_data_list = [layer0_data]

    for i, layer in enumerate(layers[1:], start=2):
        ldig = layer["digest"].replace("sha256:", "")
        layer_digests.append(ldig)
        print(f"Downloading layer {i}/{len(layers)} ({layer['size']/1e9:.2f}GB)...")
        data = _download_blob(
            sess, image, layer["digest"], layer["size"],
            f"layer {i}/{len(layers)}",
        )
        layer_data_list.append(data)

    # Build Docker-compatible tar archive
    print(f"Building image.tar ({out_tar})...")
    manifest_json = [
        {
            "Config": f"{config_hash}.json",
            "RepoTags": [f"nvcr.io/{image}:{tag}"],
            "Layers": [f"{d}/layer.tar" for d in layer_digests],
        }
    ]

    with tarfile.open(out_tar, "w") as tf:
        config_info = tarfile.TarInfo(name=f"{config_hash}.json")
        config_info.size = len(config_bytes)
        tf.addfile(config_info, io.BytesIO(config_bytes))

        for ldig, data in zip(layer_digests, layer_data_list):
            dir_info = tarfile.TarInfo(name=f"{ldig}/")
            dir_info.type = tarfile.DIRTYPE
            tf.addfile(dir_info)
            layer_info = tarfile.TarInfo(name=f"{ldig}/layer.tar")
            layer_info.size = len(data)
            tf.addfile(layer_info, io.BytesIO(data))

        mj_bytes = json.dumps(manifest_json).encode()
        mj_info = tarfile.TarInfo(name="manifest.json")
        mj_info.size = len(mj_bytes)
        tf.addfile(mj_info, io.BytesIO(mj_bytes))

    size = out_tar.stat().st_size
    print(f"\nSaved: {out_tar} ({size/1e9:.2f}GB)")

    # Digest file
    (out_dir / "image.sha256").write_text(digest)
    print(f"Digest: {out_dir / 'image.sha256'}")

    # Verification audit trail
    verification_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "tag": tag,
        "manifest_digest": digest,
        "stage1_manifest_arm64": True,  # reached here implies stage 1 passed
        "stage2_probe_elf": elf_output,
        "stage2_elf_aarch64": skip_verification or _parse_elf_is_aarch64(elf_output),
        "verdict": "SKIPPED" if skip_verification else "PASS",
        "skip_verification": skip_verification,
    }
    (out_dir / "verification.json").write_text(
        json.dumps(verification_record, indent=2)
    )
    print(f"Verification record: {out_dir / 'verification.json'}")

    return out_tar


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Pull NIM container images to NAS with ARM64 ELF verification."
    )
    ap.add_argument(
        "model",
        nargs="?",
        help="Model name (e.g. llama-nemotron-embed-1b-v2).  "
             "Not required when --verify-only is used.",
    )
    ap.add_argument("--tag", default="latest", help="Image tag (default: latest)")
    ap.add_argument("--arch", default="arm64", help="Target architecture (default: arm64)")
    ap.add_argument(
        "--force-skip-verification",
        action="store_true",
        help=(
            "EMERGENCY ONLY — bypass ARM64 ELF gate and cache the image "
            "without verification.  Logs a loud warning."
        ),
    )
    ap.add_argument(
        "--verify-only",
        metavar="TAR_PATH",
        help=(
            "Verify an already-cached NAS image.tar without pulling from the "
            "registry.  Exits 0 on PASS, 1 on FAIL/ERROR."
        ),
    )
    args = ap.parse_args()

    if args.verify_only:
        tar_path = Path(args.verify_only)
        if not tar_path.exists():
            print(f"ERROR: {tar_path} not found", file=sys.stderr)
            sys.exit(1)
        print(f"Verifying {tar_path} ...")
        result = verify_nas_tar(tar_path)
        print(f"\nVerdict:        {result.verdict}")
        print(f"Stage 1 (arch): {'PASS' if result.stage1_manifest_arm64 else 'FAIL'}")
        print(f"Stage 2 (ELF):  {'PASS' if result.stage2_elf_aarch64 else 'FAIL'}")
        if result.probe_binary_elf:
            print(f"Probe ELF:      {result.probe_binary_elf}")
        if result.evidence:
            print(f"Evidence:       {json.dumps(result.evidence, indent=2)}")
        sys.exit(0 if result.verdict == "PASS" else 1)

    if not args.model:
        ap.error("model name is required unless --verify-only is used")

    pull_to_nas(
        args.model,
        tag=args.tag,
        arch=args.arch,
        skip_verification=args.force_skip_verification,
    )


if __name__ == "__main__":
    main()
