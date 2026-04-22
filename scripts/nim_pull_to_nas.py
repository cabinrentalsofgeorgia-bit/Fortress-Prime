#!/usr/bin/env python3
"""
nim_pull_to_nas.py — Pull NIM Docker container images to NAS, bypassing
Docker daemon TLS issues with nvcr.io on DGX Spark ARM64.

Creates a Docker-compatible tar archive at:
  /mnt/fortress_nas/nim-cache/nim/<model>/<tag>/image.tar

Which can be loaded on any node via:
  docker load < /mnt/fortress_nas/nim-cache/nim/<model>/<tag>/image.tar

Usage:
  python3 scripts/nim_pull_to_nas.py <model-name> [--tag TAG] [--arch ARCH]

Examples:
  python3 scripts/nim_pull_to_nas.py llama-nemotron-embed-1b-v2
  python3 scripts/nim_pull_to_nas.py nvidia-nemotron-nano-9b-v2
  python3 scripts/nim_pull_to_nas.py nemotron-nano-12b-v2-vl

NGC_API_KEY is read from /etc/fortress/nim.env.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

import requests

NAS_BASE = Path("/mnt/fortress_nas/nim-cache/nim")
NIM_ORG = "nim/nvidia"
REGISTRY = "https://nvcr.io"
ENV_FILE = Path("/etc/fortress/nim.env")


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
        auth=("$oauthtoken", key), timeout=20
    )
    r.raise_for_status()
    return r.json()["token"]


def _get_arm64_manifest(sess: requests.Session, image: str, tag: str) -> tuple[str, dict]:
    """Returns (arm64_digest, manifest_dict)."""
    r = sess.get(
        f"{REGISTRY}/v2/{image}/manifests/{tag}",
        headers={"Accept": "application/vnd.oci.image.index.v1+json,"
                           "application/vnd.docker.distribution.manifest.list.v2+json"},
        timeout=20
    )
    r.raise_for_status()
    idx = r.json()

    # If this is already a single-arch manifest, use it directly
    if "layers" in idx:
        return tag, idx

    # Find arm64 digest in the manifest list
    arm64_digest = None
    for m in idx.get("manifests", []):
        if m.get("platform", {}).get("architecture") == "arm64":
            arm64_digest = m["digest"]
            break

    if not arm64_digest:
        archs = [m.get("platform", {}).get("architecture") for m in idx.get("manifests", [])]
        sys.exit(f"No arm64 manifest found. Available: {archs}")

    r = sess.get(
        f"{REGISTRY}/v2/{image}/manifests/{arm64_digest}",
        headers={"Accept": "application/vnd.oci.image.manifest.v1+json,"
                           "application/vnd.docker.distribution.manifest.v2+json"},
        timeout=20
    )
    r.raise_for_status()
    return arm64_digest, r.json()


def _download_blob(sess: requests.Session, image: str, digest: str,
                   expected_size: int, label: str) -> bytes:
    """Download a single blob with progress reporting."""
    url = f"{REGISTRY}/v2/{image}/blobs/{digest}"
    r = sess.get(url, timeout=300, stream=True)
    r.raise_for_status()

    buf = io.BytesIO()
    downloaded = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    t0 = time.time()

    for chunk in r.iter_content(chunk_size=chunk_size):
        buf.write(chunk)
        downloaded += len(chunk)
        if expected_size > 0:
            pct = downloaded / expected_size * 100
            mb = downloaded / 1e6
            speed = downloaded / (time.time() - t0 + 0.001) / 1e6
            print(f"\r  {label}: {mb:.0f}MB / {expected_size/1e6:.0f}MB "
                  f"({pct:.0f}%) {speed:.1f}MB/s     ", end="", flush=True)

    print()  # newline after progress
    return buf.getvalue()


def pull_to_nas(model_name: str, tag: str = "latest", arch: str = "arm64") -> Path:
    key = _read_key()
    image = f"{NIM_ORG}/{model_name}"
    out_dir = NAS_BASE / model_name / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tar = out_dir / "image.tar"

    if out_tar.exists():
        size = out_tar.stat().st_size
        print(f"Already cached: {out_tar} ({size/1e9:.2f}GB)")
        return out_tar

    sess = requests.Session()
    sess.headers.update({"User-Agent": "fortress-nim-pull/1.0"})

    print(f"Authenticating for {image}:{tag}...")
    token = _get_token(sess, image, key)
    sess.headers["Authorization"] = f"Bearer {token}"

    print("Fetching manifest...")
    digest, manifest = _get_arm64_manifest(sess, image, tag)
    layers = manifest.get("layers", [])
    config_descriptor = manifest.get("config", {})
    total_compressed = sum(l.get("size", 0) for l in layers)
    print(f"  {len(layers)} layers, {total_compressed/1e9:.2f}GB compressed")

    # Download config blob
    print(f"Downloading config ({config_descriptor.get('size',0)} bytes)...")
    config_bytes = _download_blob(
        sess, image, config_descriptor["digest"],
        config_descriptor.get("size", 0), "config"
    )
    config_hash = config_descriptor["digest"].replace("sha256:", "")

    # Download all layers
    layer_digests = []
    layer_data = []
    for i, layer in enumerate(layers):
        layer_digest = layer["digest"].replace("sha256:", "")
        layer_digests.append(layer_digest)
        print(f"Downloading layer {i+1}/{len(layers)} ({layer['size']/1e9:.2f}GB)...")
        data = _download_blob(sess, image, layer["digest"], layer["size"],
                              f"layer {i+1}/{len(layers)}")
        layer_data.append(data)

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
        # Config
        config_info = tarfile.TarInfo(name=f"{config_hash}.json")
        config_info.size = len(config_bytes)
        tf.addfile(config_info, io.BytesIO(config_bytes))

        # Layers
        for digest, data in zip(layer_digests, layer_data):
            layer_dir = f"{digest}/"
            dir_info = tarfile.TarInfo(name=layer_dir)
            dir_info.type = tarfile.DIRTYPE
            tf.addfile(dir_info)

            layer_info = tarfile.TarInfo(name=f"{digest}/layer.tar")
            layer_info.size = len(data)
            tf.addfile(layer_info, io.BytesIO(data))

        # manifest.json
        mj_bytes = json.dumps(manifest_json).encode()
        mj_info = tarfile.TarInfo(name="manifest.json")
        mj_info.size = len(mj_bytes)
        tf.addfile(mj_info, io.BytesIO(mj_bytes))

    size = out_tar.stat().st_size
    print(f"\nSaved: {out_tar} ({size/1e9:.2f}GB)")

    # Write digest file
    (out_dir / "image.sha256").write_text(digest)
    print(f"Digest: {out_dir / 'image.sha256'}")

    return out_tar


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pull NIM to NAS cache")
    ap.add_argument("model", help="Model name (e.g. llama-nemotron-embed-1b-v2)")
    ap.add_argument("--tag", default="latest")
    ap.add_argument("--arch", default="arm64")
    args = ap.parse_args()
    pull_to_nas(args.model, args.tag, args.arch)
