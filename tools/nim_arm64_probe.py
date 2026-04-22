#!/usr/bin/env python3
"""
nim_arm64_probe.py — Standalone CLI for NIM ARM64 verification.

Wraps verify_arm64_with_docker() and verify_nas_tar() from scripts/nim_pull_to_nas.

Usage:
    python3 tools/nim_arm64_probe.py --models nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:latest
    python3 tools/nim_arm64_probe.py --from-file models.txt   # one image_ref per line
    python3 tools/nim_arm64_probe.py --json                   # machine-readable output
    python3 tools/nim_arm64_probe.py --verify-nas /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar

Output (human-readable):
    MODEL                                                    MANIFEST  ELF     VERDICT
    nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:latest       PASS      PASS    PASS

Auth:
    Before any docker calls, /etc/fortress/nim.env is sourced via sudo to perform
    docker login nvcr.io. This is done once per run, not per image.

Exit codes:
    0  — all probes PASS
    1  — one or more probes FAIL or ERROR
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Import verification functions from scripts/nim_pull_to_nas
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.nim_pull_to_nas import verify_arm64_with_docker, verify_nas_tar, VerificationResult

log = logging.getLogger("nim_arm64_probe")

ENV_FILE = Path("/etc/fortress/nim.env")

# Rate-limit between docker-based probes (ms → seconds)
PROBE_SLEEP_S = 0.5


# ---------------------------------------------------------------------------
# Result wrapper for tabular output
# ---------------------------------------------------------------------------

@dataclass
class ProbeRow:
    image_ref: str
    manifest: str  # "PASS" | "FAIL" | "N/A" | "ERROR"
    elf: str        # "PASS" | "FAIL" | "N/A" | "ERROR" | "SKIP"
    verdict: str    # "PASS" | "MANIFEST_FAIL" | "ELF_FAIL" | "ERROR"
    evidence: dict


def _result_to_row(image_ref: str, res: VerificationResult) -> ProbeRow:
    manifest_str = "PASS" if res.stage1_manifest_arm64 else "FAIL"
    if res.verdict == "ERROR" and not res.stage1_manifest_arm64:
        manifest_str = "ERROR"

    if res.verdict == "MANIFEST_FAIL":
        elf_str = "N/A"
    elif res.verdict == "ERROR" and not res.stage2_elf_aarch64:
        elf_str = "ERROR"
    else:
        elf_str = "PASS" if res.stage2_elf_aarch64 else "FAIL"

    return ProbeRow(
        image_ref=image_ref,
        manifest=manifest_str,
        elf=elf_str,
        verdict=res.verdict,
        evidence=res.evidence,
    )


# ---------------------------------------------------------------------------
# docker login — once per run, via sudo heredoc (no credentials in argv/logs)
# ---------------------------------------------------------------------------

def docker_login_once() -> bool:
    """
    Source /etc/fortress/nim.env as root via sudo and run docker login nvcr.io.
    Credentials are passed via stdin to avoid appearing in argv or logs.
    Returns True on success, False if login fails or env file missing.
    """
    if not ENV_FILE.exists():
        log.warning("nim.env not found at %s — skipping docker login", ENV_FILE)
        return False

    # Heredoc script: source the env file as root, then pipe the API key to docker login
    # NGC uses $oauthtoken as username and the API key as password
    script = (
        "set -e\n"
        f"source {ENV_FILE}\n"
        'echo "${NGC_API_KEY}" | docker login nvcr.io --username "$oauthtoken" --password-stdin\n'
    )

    try:
        result = subprocess.run(
            ["sudo", "bash", "-s"],
            input=script,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            log.info("docker login nvcr.io: OK")
            return True
        else:
            log.warning("docker login nvcr.io failed: %s", result.stderr.strip())
            return False
    except Exception as exc:
        log.warning("docker login attempt failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Core probe dispatcher
# ---------------------------------------------------------------------------

def probe_image(image_ref: str) -> ProbeRow:
    """Run two-stage ARM64 verification via docker for a single image_ref."""
    log.info("Probing %s ...", image_ref)
    try:
        res = verify_arm64_with_docker(image_ref)
    except Exception as exc:
        res = VerificationResult(verdict="ERROR", evidence={"exception": str(exc)})
    return _result_to_row(image_ref, res)


def probe_nas_tar(tar_path: Path) -> ProbeRow:
    """Run verification against a locally-cached NAS tar (no docker required)."""
    log.info("Verifying NAS tar %s ...", tar_path)
    try:
        res = verify_nas_tar(tar_path)
    except Exception as exc:
        res = VerificationResult(verdict="ERROR", evidence={"exception": str(exc)})
    # Use the tar path as the display key
    return _result_to_row(str(tar_path), res)


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _pass_fail(val: str) -> str:
    return val  # keep raw strings; colour could be added later


def print_table(rows: list[ProbeRow]) -> None:
    col_model = max(len(r.image_ref) for r in rows)
    col_model = max(col_model, len("MODEL"))
    header = (
        f"{'MODEL':<{col_model}}  {'MANIFEST':<8}  {'ELF':<6}  VERDICT"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row.image_ref:<{col_model}}  "
            f"{_pass_fail(row.manifest):<8}  "
            f"{_pass_fail(row.elf):<6}  "
            f"{row.verdict}"
        )


def print_json(rows: list[ProbeRow]) -> None:
    output = []
    for row in rows:
        output.append({
            "image_ref": row.image_ref,
            "manifest": row.manifest,
            "elf": row.elf,
            "verdict": row.verdict,
            "evidence": row.evidence,
        })
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "nim_arm64_probe — Standalone NIM ARM64 verification CLI.\n"
            "Wraps verify_arm64_with_docker() from scripts/nim_pull_to_nas."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    source = ap.add_mutually_exclusive_group()
    source.add_argument(
        "--models",
        nargs="+",
        metavar="IMAGE_REF",
        help="One or more fully-qualified image refs (e.g. nvcr.io/nim/nvidia/foo:latest)",
    )
    source.add_argument(
        "--from-file",
        metavar="FILE",
        help="Path to a text file with one image_ref per line (# comments ignored)",
    )
    source.add_argument(
        "--verify-nas",
        metavar="TAR_PATH",
        help=(
            "Verify an already-cached NAS image.tar using verify_nas_tar() "
            "(no docker pull, suitable for smoke tests)"
        ),
    )

    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as a JSON array instead of a human-readable table",
    )
    ap.add_argument(
        "--no-login",
        action="store_true",
        help="Skip docker login (use if already authenticated)",
    )
    ap.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --verify-nas is a special path — no docker login needed
    if args.verify_nas:
        tar_path = Path(args.verify_nas)
        if not tar_path.exists():
            print(f"ERROR: {tar_path} not found", file=sys.stderr)
            sys.exit(1)
        row = probe_nas_tar(tar_path)
        rows = [row]
        if args.json_output:
            print_json(rows)
        else:
            print_table(rows)
        sys.exit(0 if row.verdict == "PASS" else 1)

    # Collect image refs
    image_refs: list[str] = []

    if args.models:
        image_refs = args.models
    elif args.from_file:
        fpath = Path(args.from_file)
        if not fpath.exists():
            print(f"ERROR: --from-file path not found: {fpath}", file=sys.stderr)
            sys.exit(1)
        for line in fpath.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                image_refs.append(line)
    else:
        ap.error("One of --models, --from-file, or --verify-nas is required.")

    if not image_refs:
        print("ERROR: no image refs to probe", file=sys.stderr)
        sys.exit(1)

    # docker login — once per run
    if not args.no_login:
        docker_login_once()

    # Probe each image
    rows: list[ProbeRow] = []
    for i, ref in enumerate(image_refs):
        if i > 0:
            time.sleep(PROBE_SLEEP_S)
        row = probe_image(ref)
        rows.append(row)

    # Output
    if args.json_output:
        print_json(rows)
    else:
        print_table(rows)

    # Exit code
    any_fail = any(r.verdict != "PASS" for r in rows)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
