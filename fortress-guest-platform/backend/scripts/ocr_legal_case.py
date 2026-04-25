"""
ocr_legal_case.py — in-place OCR sweep over a legal case file tree.

Reads `legal.cases.nas_layout` for the supplied --case-slug, walks every
PDF under the configured root (recursive when the layout opts in),
probes pdftotext on each file, and runs `ocrmypdf --skip-text` over
image-only PDFs.

Idempotent end-to-end:
  - pdftotext probe skips PDFs that already have text.
  - ocrmypdf's --skip-text flag is itself idempotent — even if the probe
    misclassifies, ocrmypdf refuses to re-OCR a page that already has a
    text layer.
  - Concurrent runs are gated by /tmp/ocr-sweep-{slug}.lock; --force
    overrides locks older than 6h.

ocrmypdf writes to a temp file and only swaps the target on success,
so a corrupt input PDF cannot destroy the original file via this
script.

Usage after merge:
    python -m backend.scripts.ocr_legal_case \\
        --case-slug 7il-v-knight-ndga \\
        --quality standard --jobs 6
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("ocr_legal_case")

# ─── config ────────────────────────────────────────────────────────────────

NAS_LEGAL_ROOT = "/mnt/fortress_nas/sectors/legal"
ENV_PATH = Path("/home/admin/Fortress-Prime/fortress-guest-platform/.env")

AUDIT_DIR = Path("/mnt/fortress_nas/audits")

# pdftotext output below this many chars → treated as image-only.
# 100 catches the most common image-only PDFs (which produce 0–10 chars
# of OCR-leftover whitespace from the wrapper). Real text PDFs return
# hundreds-to-thousands of chars on page 1 alone.
DEFAULT_TEXT_THRESHOLD = 100

# Map operator-friendly --quality flag to ocrmypdf --optimize integer.
# 0 = no optimisation (largest output, fastest), 3 = aggressive.
QUALITY_TO_OPTIMIZE: dict[str, int] = {
    "fast":     3,
    "standard": 1,
    "high":     0,
}

# pdftotext probe timeout — handles wedged or crashing PDFs.
PDFTOTEXT_TIMEOUT_S = 8
# Per-file ocrmypdf timeout.
OCRMYPDF_TIMEOUT_S = 600

# Lock-file safety.
LOCK_STALE_AFTER_S = 6 * 3600  # 6 hours


# ─── DB lookup ─────────────────────────────────────────────────────────────

def _read_env_pgs() -> dict[str, str]:
    """Parse .env for the admin URI (used to fetch nas_layout)."""
    out: dict[str, str] = {}
    if not ENV_PATH.exists():
        return out
    for raw in ENV_PATH.read_text().splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _admin_dsn() -> tuple[str, str, str, str, str]:
    """Return (host, port, user, password, db) for fortress_db (read-only SELECT)."""
    env = _read_env_pgs()
    uri = env.get("POSTGRES_ADMIN_URI", "")
    # postgresql+asyncpg://user:pw@host:port/dbname
    import re
    m = re.match(
        r"postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/([^?]+)",
        uri,
    )
    if not m:
        raise SystemExit(f"could not parse POSTGRES_ADMIN_URI from {ENV_PATH}")
    user, pw, host, port, _ = m.groups()
    # Layout actually lives in fortress_db (per CLAUDE.md / legal_email_intake).
    return host, port or "5432", user, pw, "fortress_db"


def fetch_case_layout(case_slug: str) -> dict[str, Any]:
    """
    Read legal.cases.nas_layout for the given slug. Returns a normalized
    dict: {"root": Path, "subdirs": {logical: relpath}, "recursive": bool}.
    Raises SystemExit if the slug is unknown.
    """
    host, port, user, pw, dbname = _admin_dsn()
    env = os.environ.copy()
    env["PGPASSWORD"] = pw
    sql = (
        "SELECT COALESCE(nas_layout::text, '{}') FROM legal.cases "
        "WHERE case_slug = $$" + case_slug.replace("$", "") + "$$"
    )
    proc = subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname,
         "-tAc", sql],
        env=env, capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"psql lookup failed for slug={case_slug}: "
            f"{proc.stderr.strip()[:200]}"
        )
    raw = proc.stdout.strip()
    if not raw:
        raise SystemExit(f"case_slug {case_slug!r} not found in legal.cases")
    layout = json.loads(raw) if raw and raw != "{}" else {}
    return _normalize_layout(case_slug, layout)


def _normalize_layout(case_slug: str, raw: dict | None) -> dict[str, Any]:
    """
    Mirror the FastAPI handler's _resolve_case_layout semantics.
    NULL/empty → canonical sectors/legal/{slug} layout, recursive=False.
    """
    if not raw:
        return {
            "root":      Path(NAS_LEGAL_ROOT) / case_slug,
            "subdirs":   {
                "certified_mail":   "certified_mail",
                "correspondence":   "correspondence",
                "evidence":         "evidence",
                "receipts":         "receipts",
                "filings_incoming": "filings/incoming",
                "filings_outgoing": "filings/outgoing",
            },
            "recursive": False,
        }
    root = Path(str(raw.get("root") or "")).expanduser()
    subs = raw.get("subdirs") or {}
    if not isinstance(subs, dict):
        subs = {}
    subdirs = {
        str(k): str(v) for k, v in subs.items()
        if v is not None and v != ""
    }
    return {
        "root":      root,
        "subdirs":   subdirs,
        "recursive": bool(raw.get("recursive")),
    }


# ─── PDF discovery + classification ────────────────────────────────────────

def iter_case_pdfs(layout: dict[str, Any]) -> list[Path]:
    """
    Return every PDF under the case's configured subdirs (deduped),
    skipping @eaDir Synology metadata folders and dotfiles.
    """
    root: Path = layout["root"]
    recursive: bool = layout["recursive"]
    seen: set[Path] = set()
    out: list[Path] = []
    for relpath in layout["subdirs"].values():
        d = root / relpath
        if not d.is_dir():
            continue
        candidates = d.rglob("*") if recursive else d.iterdir()
        for p in candidates:
            if not p.is_file():
                continue
            if p.suffix.lower() != ".pdf":
                continue
            if any(part == "@eaDir" or part.startswith(".") for part in p.parts):
                continue
            try:
                rp = p.resolve()
            except OSError:
                continue
            if rp in seen:
                continue
            seen.add(rp)
            out.append(p)
    out.sort()
    return out


def has_text_layer(path: Path, threshold: int = DEFAULT_TEXT_THRESHOLD) -> bool:
    """Probe with pdftotext on the first 3 pages. True if extracted >= threshold."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-q", "-l", "3", str(path), "-"],
            capture_output=True, timeout=PDFTOTEXT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False
    text = proc.stdout.decode("utf-8", errors="replace")
    # Strip whitespace-only output that some image-only PDFs return.
    return len(text.strip()) >= threshold


# ─── ocrmypdf invocation (worker) ──────────────────────────────────────────

@dataclass
class FileResult:
    path: str
    status: str                              # "already_text" | "ocr_applied" | "skipped" | "error"
    detail: str = ""
    pre_chars: int = 0
    post_chars: int = 0
    seconds: float = 0.0


def _probe_chars(path: Path) -> int:
    """Return character count from pdftotext on first 3 pages (best-effort)."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-q", "-l", "3", str(path), "-"],
            capture_output=True, timeout=PDFTOTEXT_TIMEOUT_S,
        )
        return len(proc.stdout)
    except Exception:
        return 0


def process_one_pdf(
    path_str: str, optimize_level: int, ocr_jobs_per_file: int,
    text_threshold: int, dry_run: bool,
) -> dict[str, Any]:
    """Worker entry point — must be picklable for ProcessPoolExecutor."""
    t0 = time.monotonic()
    p = Path(path_str)
    pre_chars = _probe_chars(p)
    if pre_chars >= text_threshold:
        return asdict(FileResult(
            path=path_str, status="already_text",
            pre_chars=pre_chars, post_chars=pre_chars,
            seconds=round(time.monotonic() - t0, 2),
        ))

    if dry_run:
        return asdict(FileResult(
            path=path_str, status="skipped", detail="dry_run",
            pre_chars=pre_chars, seconds=round(time.monotonic() - t0, 2),
        ))

    tmp_out = p.with_suffix(p.suffix + ".ocr.tmp")
    cmd = [
        "ocrmypdf",
        "--skip-text",                  # idempotent: leave OCR'd pages alone
        "--output-type", "pdf",
        "--optimize", str(optimize_level),
        "--rotate-pages",
        "--deskew",
        "--quiet",
        "--jobs", str(ocr_jobs_per_file),
        str(p), str(tmp_out),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=OCRMYPDF_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        try:
            tmp_out.unlink(missing_ok=True)
        except Exception:
            pass
        return asdict(FileResult(
            path=path_str, status="error", detail="timeout",
            pre_chars=pre_chars,
            seconds=round(time.monotonic() - t0, 2),
        ))
    except Exception as exc:
        try:
            tmp_out.unlink(missing_ok=True)
        except Exception:
            pass
        return asdict(FileResult(
            path=path_str, status="error",
            detail=f"{type(exc).__name__}:{str(exc)[:120]}",
            pre_chars=pre_chars,
            seconds=round(time.monotonic() - t0, 2),
        ))

    if proc.returncode != 0:
        try:
            tmp_out.unlink(missing_ok=True)
        except Exception:
            pass
        return asdict(FileResult(
            path=path_str, status="error",
            detail=f"rc={proc.returncode}:{proc.stderr.decode('utf-8', errors='replace')[:160]}",
            pre_chars=pre_chars,
            seconds=round(time.monotonic() - t0, 2),
        ))

    # Atomic swap: only replace the original after ocrmypdf wrote a clean
    # output. shutil.move is atomic on the same filesystem.
    try:
        shutil.move(str(tmp_out), str(p))
    except Exception as exc:
        return asdict(FileResult(
            path=path_str, status="error",
            detail=f"swap_failed:{type(exc).__name__}:{str(exc)[:120]}",
            pre_chars=pre_chars,
            seconds=round(time.monotonic() - t0, 2),
        ))

    post_chars = _probe_chars(p)
    return asdict(FileResult(
        path=path_str, status="ocr_applied",
        pre_chars=pre_chars, post_chars=post_chars,
        seconds=round(time.monotonic() - t0, 2),
    ))


# ─── lock file ─────────────────────────────────────────────────────────────

def _lock_path(case_slug: str) -> Path:
    return Path(f"/tmp/ocr-sweep-{case_slug}.lock")


def acquire_lock(case_slug: str, force: bool) -> Path:
    lp = _lock_path(case_slug)
    if lp.exists():
        age = time.time() - lp.stat().st_mtime
        if force and age > LOCK_STALE_AFTER_S:
            lp.unlink()
        elif force:
            raise SystemExit(
                f"--force given but lock at {lp} is only {int(age)}s old "
                f"(needs > {LOCK_STALE_AFTER_S}s); refusing"
            )
        else:
            raise SystemExit(
                f"another sweep appears to be running (lock at {lp}); "
                f"pass --force after confirming no concurrent run"
            )
    lp.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}\n")
    return lp


def release_lock(lp: Path) -> None:
    try:
        lp.unlink()
    except Exception:
        pass


# ─── manifest ──────────────────────────────────────────────────────────────

@dataclass
class SweepManifest:
    case_slug: str
    started_at: str
    finished_at: str
    runtime_seconds: float
    layout_root: str
    layout_recursive: bool
    layout_subdirs: dict[str, str]
    quality: str
    optimize_level: int
    jobs: int
    dry_run: bool
    text_threshold: int
    total_pdfs: int = 0
    already_text: int = 0
    ocr_applied: int = 0
    skipped: int = 0
    errors_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    samples_already_text: list[str] = field(default_factory=list)
    samples_ocr_applied: list[str] = field(default_factory=list)


def write_manifest(case_slug: str, manifest: SweepManifest) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = AUDIT_DIR / f"ocr-sweep-{case_slug}-{ts}.json"
    out.write_text(json.dumps(asdict(manifest), indent=2, default=str))
    return out


# ─── orchestrator ──────────────────────────────────────────────────────────

def run_sweep(args: argparse.Namespace) -> int:
    layout = fetch_case_layout(args.case_slug)
    pdfs = iter_case_pdfs(layout)
    if args.max_files is not None:
        pdfs = pdfs[: args.max_files]

    optimize_level = QUALITY_TO_OPTIMIZE[args.quality]
    started = datetime.now(timezone.utc)
    t_started = time.monotonic()

    manifest = SweepManifest(
        case_slug=args.case_slug,
        started_at=started.isoformat(),
        finished_at="",
        runtime_seconds=0.0,
        layout_root=str(layout["root"]),
        layout_recursive=layout["recursive"],
        layout_subdirs=dict(layout["subdirs"]),
        quality=args.quality,
        optimize_level=optimize_level,
        jobs=args.jobs,
        dry_run=args.dry_run,
        text_threshold=args.text_threshold,
        total_pdfs=len(pdfs),
    )

    print(f"# OCR sweep: {args.case_slug}", flush=True)
    print(f"# layout: root={layout['root']}, recursive={layout['recursive']}, "
          f"subdirs={len(layout['subdirs'])}", flush=True)
    print(f"# PDFs queued: {len(pdfs)} "
          f"(max_files={args.max_files}, dry_run={args.dry_run})", flush=True)

    # Single-process when --jobs=1 (also makes tests deterministic).
    if args.jobs == 1:
        results = [process_one_pdf(
            str(p), optimize_level, args.ocr_jobs_per_file,
            args.text_threshold, args.dry_run,
        ) for p in pdfs]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            futs = [
                ex.submit(
                    process_one_pdf, str(p), optimize_level,
                    args.ocr_jobs_per_file, args.text_threshold, args.dry_run,
                )
                for p in pdfs
            ]
            for n, fut in enumerate(as_completed(futs), 1):
                r = fut.result()
                results.append(r)
                if n % 25 == 0 or r["status"] == "error":
                    print(
                        f"  [{n}/{len(futs)}] {r['status']:<14s} "
                        f"({r.get('seconds', 0):>5.1f}s)  {Path(r['path']).name[:60]}",
                        flush=True,
                    )

    for r in results:
        s = r["status"]
        if s == "already_text":
            manifest.already_text += 1
            if len(manifest.samples_already_text) < 10:
                manifest.samples_already_text.append(Path(r["path"]).name)
        elif s == "ocr_applied":
            manifest.ocr_applied += 1
            if len(manifest.samples_ocr_applied) < 10:
                manifest.samples_ocr_applied.append(Path(r["path"]).name)
        elif s == "skipped":
            manifest.skipped += 1
        elif s == "error":
            manifest.errors_count += 1
            manifest.errors.append({
                "path":   r["path"],
                "detail": r.get("detail", ""),
            })

    manifest.runtime_seconds = round(time.monotonic() - t_started, 2)
    manifest.finished_at = datetime.now(timezone.utc).isoformat()

    out = write_manifest(args.case_slug, manifest)
    print(
        f"# done: total={manifest.total_pdfs}  "
        f"already_text={manifest.already_text}  "
        f"ocr_applied={manifest.ocr_applied}  "
        f"skipped={manifest.skipped}  errors={manifest.errors_count}  "
        f"runtime={manifest.runtime_seconds:.1f}s  "
        f"manifest={out}",
        flush=True,
    )
    return 0 if manifest.errors_count == 0 else 1


# ─── CLI ───────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="OCR sweep over a legal case file tree (in-place, idempotent)",
    )
    p.add_argument("--case-slug", required=True,
                   help="legal.cases.case_slug to sweep")
    p.add_argument("--dry-run", action="store_true",
                   help="classify only — do NOT run ocrmypdf")
    p.add_argument("--max-files", type=int, default=None,
                   help="cap on PDFs processed (testing)")
    p.add_argument("--quality", choices=tuple(QUALITY_TO_OPTIMIZE),
                   default="standard")
    p.add_argument("--jobs", type=int, default=4,
                   help="parallel files (default 4)")
    p.add_argument("--ocr-jobs-per-file", type=int, default=2,
                   help="ocrmypdf --jobs per file (default 2)")
    p.add_argument("--text-threshold", type=int,
                   default=DEFAULT_TEXT_THRESHOLD,
                   help=f"pdftotext char count below which a PDF is image-only "
                        f"(default {DEFAULT_TEXT_THRESHOLD})")
    p.add_argument("--skip-already-text", action="store_true", default=True,
                   help="(default) skip PDFs whose pdftotext probe returns >= threshold")
    p.add_argument("--force", action="store_true",
                   help="override stale lock files (>6h old)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    lp = acquire_lock(args.case_slug, args.force)
    try:
        return run_sweep(args)
    finally:
        release_lock(lp)


if __name__ == "__main__":
    raise SystemExit(main())
