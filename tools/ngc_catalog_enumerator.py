#!/usr/bin/env python3
"""
NGC Catalog Enumerator — Discovery-only pass over NVIDIA NIM / NeMo containers.
================================================================================
Enumerates every relevant container under:
  nvcr.io/nim/nvidia/*
  nvcr.io/nim/meta/*
  nvcr.io/nim/mistralai/*
  nvcr.io/nim/deepseek-ai/*
  nvcr.io/nemo/*

For each image:
  - Calls NGC REST catalog API for name / description / tag metadata
  - Calls `docker manifest inspect` to gather platform list and arm64 presence
  - Writes results to `nim_catalog` Postgres table (upsert on probe_date+image_path)
  - Writes a JSONL snapshot to /mnt/fortress_nas/fortress_data/nim_catalog/

Auth: reads NGC_API_KEY from /etc/fortress/nim.env (root-owned, 600 perms).
      Uses `sudo -n` to source the env file without exposing credentials in argv.

Rate limiting: 500 ms sleep between manifest inspects; exponential back-off on
429 responses.

CONSTRAINTS:
  - No image pulls.
  - No enterprise assignments.
  - No credentials written to logs, snapshot, or DB.
  - Idempotent: upsert on (probe_date, image_path).

Usage:
    python3 tools/ngc_catalog_enumerator.py
    python3 tools/ngc_catalog_enumerator.py --dry-run       # log only, no DB/NAS writes
    python3 tools/ngc_catalog_enumerator.py --no-manifest   # skip docker manifest inspects
    python3 tools/ngc_catalog_enumerator.py --namespace nim/nvidia  # single namespace

Governing brief: docs/ngc-catalog-enumeration-brief.md
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Path / import bootstrap
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Phase-1 ELF helper (manifest string check only — no ELF binary pull)
try:
    from scripts.nim_pull_to_nas import _parse_elf_is_aarch64  # noqa: F401 — available for callers
except ImportError:
    def _parse_elf_is_aarch64(file_output: str) -> bool:  # type: ignore[misc]
        lower = file_output.lower()
        return "arm aarch64" in lower or "aarch64" in lower

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ngc_enumerator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_FILE = Path("/etc/fortress/nim.env")
NAS_SNAPSHOT_DIR = Path("/mnt/fortress_nas/fortress_data/nim_catalog")
NGC_CATALOG_API = "https://api.ngc.nvidia.com/v2/search/catalog/resources/CONTAINER"
NGC_REGISTRY_API = "https://api.ngc.nvidia.com/v2"
NVCR_REGISTRY = "nvcr.io"
MANIFEST_TIMEOUT = 10          # seconds per docker manifest inspect
INTER_MANIFEST_SLEEP = 0.5     # seconds between manifest calls
API_BACKOFF_BASE = 2.0         # seconds base for exponential back-off on 429
API_MAX_RETRIES = 4
PAGE_SIZE = 100

# Namespaces to enumerate (org/team prefix under nvcr.io)
DEFAULT_NAMESPACES = [
    "nim/nvidia",
    "nim/meta",
    "nim/mistralai",
    "nim/deepseek-ai",
    "nemo",
]

# Tags that are noise — filter them out
JUNK_TAG_PATTERNS = re.compile(
    r"(nightly|\.dev\.|tmp|test|rc\d+[a-z]|pr[-_]\d+|sha-[0-9a-f]{7,}|\d{8}-\d{6})",
    re.IGNORECASE,
)

# Tags worth keeping
KEEP_TAG_PATTERNS = re.compile(
    r"^(latest|stable|ga|"                     # well-known symbolic tags
    r"v?\d+\.\d+(\.\d+)?([._-][a-z0-9]+)*|"   # semver-ish
    r"\d+\.\d+[._-][a-z].*"                    # milestone like 1.6.0-grace-hopper
    r")$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Credential loading (root-owned env file, no credentials in argv)
# ---------------------------------------------------------------------------

def _load_nim_env() -> dict[str, str]:
    """
    Source /etc/fortress/nim.env via `sudo cat` and parse KEY=VALUE pairs.
    Returns a dict.  Raises RuntimeError if the file is inaccessible.
    """
    try:
        result = subprocess.run(
            ["sudo", "-n", "cat", str(ENV_FILE)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Cannot read {ENV_FILE} via sudo: {result.stderr.strip()}"
            )
        env: dict[str, str] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
        return env
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout sourcing {ENV_FILE}")


def _get_db_creds() -> dict[str, Any]:
    """
    Load DB credentials using the same pattern as nvidia_sentinel.py —
    try project config first, fall back to .env / environment.
    """
    try:
        from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT  # type: ignore
        return {
            "host": DB_HOST, "dbname": DB_NAME,
            "user": DB_USER, "password": DB_PASS, "port": int(DB_PORT),
        }
    except ImportError:
        pass

    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
    return {
        "host": os.getenv("DB_HOST", "192.168.0.100"),
        "dbname": os.getenv("DB_NAME", "fortress_db"),
        "user": os.getenv("DB_USER", "miner_bot"),
        "password": os.getenv("DB_PASS", ""),
        "port": int(os.getenv("DB_PORT", "5432")),
    }


# ---------------------------------------------------------------------------
# NGC REST API helpers
# ---------------------------------------------------------------------------

def _ngc_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """GET from NGC API with exponential back-off on 429."""
    delay = API_BACKOFF_BASE
    for attempt in range(API_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 429:
                log.warning("NGC rate-limited (429). Back-off %.1fs (attempt %d/%d)",
                            delay, attempt + 1, API_MAX_RETRIES)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 401:
                raise RuntimeError("NGC authentication failed (401). Check NGC_API_KEY.")
            if resp.status_code == 403:
                log.warning("NGC 403 Forbidden for %s — skipping.", url)
                return {}
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            log.warning("NGC request error (attempt %d/%d): %s", attempt + 1, API_MAX_RETRIES, exc)
            if attempt < API_MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2
    return {}


def enumerate_namespace(
    namespace: str,
    ngc_api_key: str,
) -> list[dict[str, Any]]:
    """
    Page through NGC catalog REST API for a given org/team namespace.
    Returns a list of raw catalog entry dicts.
    """
    headers = {"Authorization": f"Bearer {ngc_api_key}"}
    # NGC catalog search: query by org path
    org_team = namespace.split("/")
    query_str = " ".join(org_team)

    all_entries: list[dict[str, Any]] = []
    offset = 0

    while True:
        params: dict[str, Any] = {
            "q": query_str,
            "fields": "name,latestTag,description,architecture,orgName,teamName,displayName,publisher",
            "offset": offset,
            "limit": PAGE_SIZE,
        }
        data = _ngc_get(NGC_CATALOG_API, params, headers)
        if not data:
            break

        results = data.get("results", [])
        if not results:
            # Try top-level result key variants
            results = data.get("containerVersions", data.get("resources", []))

        if not results:
            break

        all_entries.extend(results)
        log.info("  namespace=%s  offset=%d  page_count=%d  total_so_far=%d",
                 namespace, offset, len(results), len(all_entries))

        total = data.get("totalRecords", data.get("total", len(all_entries)))
        offset += PAGE_SIZE
        if offset >= total or len(results) < PAGE_SIZE:
            break

    return all_entries


# ---------------------------------------------------------------------------
# Tag filtering
# ---------------------------------------------------------------------------

def _is_keep_tag(tag: str) -> bool:
    """Return True if the tag looks like a stable/release tag worth recording."""
    if JUNK_TAG_PATTERNS.search(tag):
        return False
    return bool(KEEP_TAG_PATTERNS.match(tag))


def fetch_tags_for_image(image_path: str, ngc_api_key: str) -> list[str]:
    """
    Fetch available tags for an image via the NGC registry v2 API (catalog).
    image_path is like  nim/nvidia/llama-3.1-8b-instruct
    """
    parts = image_path.replace("nvcr.io/", "").split("/")
    if len(parts) < 2:
        return []

    # Try the registry tags endpoint
    org = parts[0]
    team_image = "/".join(parts[1:])
    # NGC tags API: GET /v2/{org}/{team}/{image}/tags/list
    url = f"https://nvcr.io/v2/{'/'.join(parts)}/tags/list"
    headers = {"Authorization": f"Bearer {ngc_api_key}"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            tags_data = resp.json()
            raw_tags: list[str] = tags_data.get("tags", [])
            return [t for t in raw_tags if _is_keep_tag(t)]
        elif resp.status_code == 401:
            # Try token auth
            token = _get_registry_token(org, ngc_api_key, "/".join(parts))
            if token:
                headers["Authorization"] = f"Bearer {token}"
                resp2 = requests.get(url, headers=headers, timeout=15)
                if resp2.status_code == 200:
                    raw_tags = resp2.json().get("tags", [])
                    return [t for t in raw_tags if _is_keep_tag(t)]
    except requests.RequestException as exc:
        log.debug("Tags fetch failed for %s: %s", image_path, exc)
    return []


def _get_registry_token(org: str, ngc_api_key: str, scope_path: str) -> str:
    """Fetch a registry bearer token for nvcr.io scope."""
    try:
        resp = requests.get(
            "https://authn.nvidia.com/token",
            params={
                "service": "registry.ngc.nvidia.com",
                "scope": f"repository:{scope_path}:pull",
            },
            auth=("$oauthtoken", ngc_api_key),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("token", "")
    except requests.RequestException:
        pass
    return ""


# ---------------------------------------------------------------------------
# Docker manifest inspect
# ---------------------------------------------------------------------------

def manifest_inspect(image_ref: str) -> dict[str, Any]:
    """
    Run `docker manifest inspect <image_ref>` and return parsed JSON.
    Returns empty dict on error/timeout (logs warning).

    The returned dict has synthetic keys injected:
      _entitlement_status: 'accessible' | 'nvaie_gated' | 'not_found' | 'auth_error' | 'timeout' | 'error'
      _platforms: list[str]
      _arm64_present: bool
      _size_bytes: int | None
      _publication_date: str | None
    """
    result: dict[str, Any] = {
        "_entitlement_status": "error",
        "_platforms": [],
        "_arm64_present": False,
        "_size_bytes": None,
        "_publication_date": None,
    }
    try:
        proc = subprocess.run(
            ["docker", "manifest", "inspect", image_ref],
            capture_output=True, text=True, timeout=MANIFEST_TIMEOUT,
        )
        stderr_low = proc.stderr.lower()

        if proc.returncode != 0:
            if "unauthorized" in stderr_low or "denied" in stderr_low:
                # Could be 401 or 403 — check if it's a known 402-equivalent
                if "402" in proc.stderr or "nvaie" in stderr_low or "entitlement" in stderr_low:
                    result["_entitlement_status"] = "nvaie_gated"
                else:
                    result["_entitlement_status"] = "auth_error"
            elif "not found" in stderr_low or "manifest unknown" in stderr_low or "404" in proc.stderr:
                result["_entitlement_status"] = "not_found"
            else:
                result["_entitlement_status"] = "error"
            result["_raw_error"] = proc.stderr.strip()[:300]
            return result

        try:
            index = json.loads(proc.stdout)
        except json.JSONDecodeError:
            result["_entitlement_status"] = "error"
            result["_raw_error"] = "JSON parse failed"
            return result

        result.update(index)
        result["_entitlement_status"] = "accessible"

        # Parse platforms
        platforms: list[str] = []
        arm64_present = False
        total_size: int | None = None

        if "manifests" in index:
            for m in index["manifests"]:
                plat = m.get("platform", {})
                arch = plat.get("architecture", "unknown")
                os_name = plat.get("os", "unknown")
                variant = plat.get("variant", "")
                plat_str = f"{os_name}/{arch}"
                if variant:
                    plat_str += f"/{variant}"
                if os_name not in ("unknown", ""):
                    platforms.append(plat_str)
                if arch == "arm64" and os_name == "linux":
                    arm64_present = True
                # Size from config/layers if available
                for layer_key in ("config", "schemaV2Manifest"):
                    sz = m.get(layer_key, {})
                    if isinstance(sz, dict) and sz.get("size"):
                        if total_size is None:
                            total_size = sz["size"]
        elif index.get("architecture") == "arm64":
            # Single-arch manifest
            platforms.append(f"{index.get('os', 'linux')}/arm64")
            arm64_present = True
        elif "architecture" in index:
            platforms.append(f"{index.get('os', 'linux')}/{index['architecture']}")

        # Try to get total size from config layer
        config = index.get("config", {})
        if isinstance(config, dict) and config.get("size") and total_size is None:
            total_size = config["size"]
        layers = index.get("layers", [])
        if layers and total_size is None:
            total_size = sum(layer.get("size", 0) for layer in layers if isinstance(layer, dict))
            if total_size == 0:
                total_size = None

        # Publication date from history or annotations
        pub_date: str | None = None
        annotations = index.get("annotations", {})
        if isinstance(annotations, dict):
            pub_date = annotations.get("org.opencontainers.image.created")
        if not pub_date and isinstance(config, dict):
            pub_date = config.get("created")

        result["_platforms"] = list(dict.fromkeys(platforms))  # dedupe, preserve order
        result["_arm64_present"] = arm64_present
        result["_size_bytes"] = total_size
        result["_publication_date"] = pub_date

    except subprocess.TimeoutExpired:
        result["_entitlement_status"] = "timeout"
        log.warning("Manifest inspect timeout for %s", image_ref)

    return result


# ---------------------------------------------------------------------------
# Metadata parsing helpers
# ---------------------------------------------------------------------------

_FAMILY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"nemotron", re.I), "nemotron"),
    (re.compile(r"llama", re.I), "llama"),
    (re.compile(r"mistral|mixtral", re.I), "mistral"),
    (re.compile(r"deepseek", re.I), "deepseek"),
    (re.compile(r"qwen", re.I), "qwen"),
    (re.compile(r"phi[-_]?\d", re.I), "phi"),
    (re.compile(r"gemma", re.I), "gemma"),
    (re.compile(r"embed|embedding", re.I), "embed"),
    (re.compile(r"rerank", re.I), "rerank"),
    (re.compile(r"clip|vision|vl|visual", re.I), "vision"),
    (re.compile(r"whisper|asr|speech", re.I), "speech"),
    (re.compile(r"nemo", re.I), "nemo"),
    (re.compile(r"triton", re.I), "triton"),
    (re.compile(r"trt[-_]?llm|tensorrt", re.I), "tensorrt-llm"),
]

_TASK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"concierge|hotel|hospitality|property[-_ ]?mgmt", re.I), "concierge"),
    (re.compile(r"retriev|rag|qa|question[-_ ]?answer", re.I), "retrieval"),
    (re.compile(r"embed|encoding", re.I), "embedding"),
    (re.compile(r"rerank", re.I), "reranking"),
    (re.compile(r"reason|r1|cot|chain[-_ ]?of[-_ ]?thought", re.I), "reasoning"),
    (re.compile(r"vision|vl|multimodal|vlm", re.I), "vision-language"),
    (re.compile(r"code|coder|codegen", re.I), "code-generation"),
    (re.compile(r"speech|asr|whisper|transcri", re.I), "speech"),
    (re.compile(r"instruct", re.I), "instruction-following"),
    (re.compile(r"chat", re.I), "chat"),
    (re.compile(r"guard|safety|shield", re.I), "safety"),
]

_LICENSE_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"nvaie|enterprise[-_ ]?only", re.I), "nvaie-only"),
    (re.compile(r"commercial|community", re.I), "commercial"),
    (re.compile(r"research[-_ ]?only|non[-_ ]?commercial", re.I), "research-only"),
    (re.compile(r"apache|mit\b|bsd", re.I), "open-source"),
    (re.compile(r"llama\s*(community|license)", re.I), "llama-community"),
]


def _infer_model_family(name: str, description: str = "") -> str:
    text = f"{name} {description}"
    for pattern, family in _FAMILY_PATTERNS:
        if pattern.search(text):
            return family
    return "other"


def _infer_task_type(name: str, description: str = "") -> str:
    text = f"{name} {description}"
    for pattern, task in _TASK_PATTERNS:
        if pattern.search(text):
            return task
    return "inference"


def _infer_license(description: str, license_field: str = "") -> str:
    text = f"{description} {license_field}"
    for pattern, hint in _LICENSE_HINTS:
        if pattern.search(text):
            return hint
    return "unknown"


# ---------------------------------------------------------------------------
# Core catalog entry assembly
# ---------------------------------------------------------------------------

def build_catalog_entry(
    namespace: str,
    raw: dict[str, Any],
    ngc_api_key: str,
    probe_date: date,
    do_manifest: bool = True,
) -> dict[str, Any]:
    """
    Given a raw NGC catalog result entry, build a nim_catalog row dict.
    """
    # Extract name from various NGC response shapes
    name: str = (
        raw.get("name")
        or raw.get("containerName")
        or raw.get("displayName")
        or ""
    )
    org_name: str = raw.get("orgName", namespace.split("/")[0])
    team_name: str = raw.get("teamName", "/".join(namespace.split("/")[1:]) if "/" in namespace else "")

    # Build canonical image_path
    if name.startswith("nvcr.io/"):
        image_path = name
    elif "/" in name and name.count("/") >= 2:
        image_path = f"nvcr.io/{name}"
    else:
        if team_name:
            image_path = f"nvcr.io/{org_name}/{team_name}/{name}"
        else:
            image_path = f"nvcr.io/{org_name}/{name}"

    latest_tag: str | None = raw.get("latestTag") or raw.get("latestVersion")
    description: str = raw.get("description", "") or ""
    description_snippet = description[:200].strip() if description else None

    # Fetch filtered tags
    tags_available: list[str] = fetch_tags_for_image(image_path, ngc_api_key)
    if latest_tag and _is_keep_tag(latest_tag) and latest_tag not in tags_available:
        tags_available.insert(0, latest_tag)

    # If no latest_tag was in catalog response but we have tags, pick best
    if not latest_tag and tags_available:
        for preferred in ("latest", "stable", "ga"):
            if preferred in tags_available:
                latest_tag = preferred
                break
        if not latest_tag:
            latest_tag = tags_available[0]

    model_family = _infer_model_family(name, description)
    task_type = _infer_task_type(name, description)
    license_hint = _infer_license(description, raw.get("license", ""))

    # Docker manifest inspect
    entitlement_status = "unknown"
    platforms: list[str] = []
    arm64_present: bool | None = None
    size_bytes: int | None = None
    publication_date: str | None = None
    probe_notes: list[str] = []

    if do_manifest:
        inspect_tag = latest_tag or "latest"
        inspect_ref = f"{image_path}:{inspect_tag}"
        time.sleep(INTER_MANIFEST_SLEEP)
        manifest_data = manifest_inspect(inspect_ref)
        entitlement_status = manifest_data.get("_entitlement_status", "error")
        platforms = manifest_data.get("_platforms", [])
        arm64_present = manifest_data.get("_arm64_present", False)
        size_bytes = manifest_data.get("_size_bytes")
        publication_date = manifest_data.get("_publication_date")

        if entitlement_status == "error":
            raw_err = manifest_data.get("_raw_error", "")
            if raw_err:
                probe_notes.append(f"manifest-error: {raw_err[:120]}")

        if entitlement_status == "nvaie_gated":
            license_hint = "nvaie-only"
    else:
        entitlement_status = "not-inspected"

    return {
        "probe_date": probe_date.isoformat(),
        "image_path": image_path,
        "latest_tag": latest_tag,
        "tags_available": tags_available,
        "platforms": platforms,
        "arm64_manifest_present": arm64_present,
        "size_bytes": size_bytes,
        "model_family": model_family,
        "task_type": task_type,
        "license_hint": license_hint,
        "publication_date": publication_date,
        "entitlement_status": entitlement_status,
        "description_snippet": description_snippet,
        "probe_notes": "; ".join(probe_notes) if probe_notes else None,
    }


# ---------------------------------------------------------------------------
# Postgres upsert
# ---------------------------------------------------------------------------

def upsert_catalog_rows(rows: list[dict[str, Any]], db_creds: dict[str, Any]) -> None:
    """Upsert nim_catalog rows using psycopg2."""
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore

    conn = psycopg2.connect(**db_creds)
    try:
        with conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO nim_catalog
                        (probe_date, image_path, latest_tag, tags_available, platforms,
                         arm64_manifest_present, size_bytes, model_family, task_type,
                         license_hint, publication_date, entitlement_status,
                         description_snippet, probe_notes)
                    VALUES
                        (%(probe_date)s, %(image_path)s, %(latest_tag)s,
                         %(tags_available)s::jsonb, %(platforms)s::jsonb,
                         %(arm64_manifest_present)s, %(size_bytes)s,
                         %(model_family)s, %(task_type)s, %(license_hint)s,
                         %(publication_date)s, %(entitlement_status)s,
                         %(description_snippet)s, %(probe_notes)s)
                    ON CONFLICT (probe_date, image_path)
                    DO UPDATE SET
                        latest_tag             = EXCLUDED.latest_tag,
                        tags_available         = EXCLUDED.tags_available,
                        platforms              = EXCLUDED.platforms,
                        arm64_manifest_present = EXCLUDED.arm64_manifest_present,
                        size_bytes             = EXCLUDED.size_bytes,
                        model_family           = EXCLUDED.model_family,
                        task_type              = EXCLUDED.task_type,
                        license_hint           = EXCLUDED.license_hint,
                        publication_date       = EXCLUDED.publication_date,
                        entitlement_status     = EXCLUDED.entitlement_status,
                        description_snippet    = EXCLUDED.description_snippet,
                        probe_notes            = EXCLUDED.probe_notes
                    """,
                    [
                        {
                            **row,
                            "tags_available": json.dumps(row["tags_available"]),
                            "platforms": json.dumps(row["platforms"]),
                        }
                        for row in rows
                    ],
                    page_size=50,
                )
        log.info("DB upsert complete: %d rows.", len(rows))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# JSONL snapshot writer
# ---------------------------------------------------------------------------

def write_jsonl_snapshot(rows: list[dict[str, Any]], probe_date: date) -> Path:
    """Write rows to a dated JSONL snapshot file on NAS."""
    NAS_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = NAS_SNAPSHOT_DIR / f"snapshot_{probe_date.isoformat()}.jsonl"
    with snapshot_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")
    log.info("JSONL snapshot written: %s  (%d records)", snapshot_path, len(rows))
    return snapshot_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NGC NIM/NeMo catalog enumerator — discovery only, no pulls.",
    )
    parser.add_argument(
        "--namespace",
        metavar="ORG[/TEAM]",
        help="Enumerate a single namespace only (e.g. nim/nvidia).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log results only. Do not write to DB or NAS.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Skip docker manifest inspect calls (faster; loses arm64/platform data).",
    )
    args = parser.parse_args()

    probe_date = date.today()
    started_at = datetime.now(tz=timezone.utc).isoformat()

    log.info("NGC catalog enumeration started at %s  probe_date=%s", started_at, probe_date)
    if args.dry_run:
        log.info("DRY RUN mode — no DB or NAS writes.")

    # --- Load credentials ---
    try:
        nim_env = _load_nim_env()
    except RuntimeError as exc:
        log.critical("STOP: %s", exc)
        sys.exit(1)

    ngc_api_key = nim_env.get("NGC_API_KEY", "")
    if not ngc_api_key:
        log.critical("STOP: NGC_API_KEY not found in %s", ENV_FILE)
        sys.exit(1)

    # Strip key from any logging — no credentials in logs
    log.info("NGC_API_KEY loaded (length=%d). Beginning enumeration.", len(ngc_api_key))

    # --- Load DB creds (not needed in dry-run, but load early to fail fast) ---
    db_creds: dict[str, Any] = {}
    if not args.dry_run:
        try:
            db_creds = _get_db_creds()
        except Exception as exc:
            log.critical("STOP: DB credential load failed: %s", exc)
            sys.exit(1)

    # --- Enumerate namespaces ---
    namespaces = [args.namespace] if args.namespace else DEFAULT_NAMESPACES
    all_rows: list[dict[str, Any]] = []

    for ns in namespaces:
        log.info("Enumerating namespace: %s", ns)
        catalog_entries = enumerate_namespace(ns, ngc_api_key)
        log.info("  Found %d raw catalog entries for %s", len(catalog_entries), ns)

        for raw in catalog_entries:
            try:
                row = build_catalog_entry(
                    namespace=ns,
                    raw=raw,
                    ngc_api_key=ngc_api_key,
                    probe_date=probe_date,
                    do_manifest=not args.no_manifest,
                )
                all_rows.append(row)
                status_sym = {
                    "accessible": "OK",
                    "nvaie_gated": "402",
                    "not_found": "404",
                    "auth_error": "AUTH",
                    "timeout": "TMO",
                    "error": "ERR",
                    "not-inspected": "---",
                    "unknown": "???",
                }.get(row["entitlement_status"], "???")
                arm_sym = "arm64" if row["arm64_manifest_present"] else "x86-only"
                if row["arm64_manifest_present"] is None:
                    arm_sym = "unknown"
                log.info(
                    "  [%s] %-55s  %s  family=%-12s task=%s",
                    status_sym, row["image_path"], arm_sym,
                    row["model_family"], row["task_type"],
                )
            except Exception as exc:
                log.warning("  Failed to build entry for raw=%s: %s", raw.get("name", "?"), exc)

    # Deduplicate by image_path (keep last, which is the most-recently-processed namespace)
    seen: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        seen[row["image_path"]] = row
    deduped = list(seen.values())

    # --- Summary ---
    total = len(deduped)
    arm64_count = sum(1 for r in deduped if r["arm64_manifest_present"] is True)
    gated_count = sum(1 for r in deduped if r["entitlement_status"] == "nvaie_gated")
    commercial_count = sum(
        1 for r in deduped
        if r["license_hint"] in ("commercial", "llama-community", "open-source")
    )

    log.info(
        "Enumeration complete: total=%d  arm64=%d  nvaie_gated=%d  commercial_ok=%d",
        total, arm64_count, gated_count, commercial_count,
    )

    if not deduped:
        log.warning("No entries found. Check NGC_API_KEY permissions and namespace paths.")
        return

    # --- DB upsert ---
    if not args.dry_run:
        try:
            upsert_catalog_rows(deduped, db_creds)
        except Exception as exc:
            log.error("DB upsert failed: %s. Continuing to write JSONL snapshot.", exc)

        # --- JSONL snapshot ---
        try:
            snapshot_path = write_jsonl_snapshot(deduped, probe_date)
        except Exception as exc:
            log.error("JSONL snapshot write failed: %s", exc)
    else:
        log.info("DRY RUN: skipped DB upsert and JSONL write.")
        log.info("DRY RUN: first 3 rows:")
        for row in deduped[:3]:
            log.info("  %s", json.dumps(row, default=str, indent=2))


if __name__ == "__main__":
    main()
