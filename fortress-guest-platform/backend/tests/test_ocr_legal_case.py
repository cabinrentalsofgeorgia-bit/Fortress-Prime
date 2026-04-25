"""
Tests for backend.scripts.ocr_legal_case — OCR sweep orchestrator.

ocrmypdf invocations are mocked (real OCR is slow). pdftotext probes
run for real against synthetic Pillow- and reportlab-generated PDFs.
DB lookup (`fetch_case_layout`) is mocked out.
"""
from __future__ import annotations

import io
import json
import multiprocessing
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.scripts import ocr_legal_case as ocr


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic-PDF fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _text_pdf(path: Path, body: str = None) -> Path:
    """Reportlab text PDF — pdftotext returns the body string back."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    if body is None:
        body = "This is a real text PDF " * 30  # ~600 chars, well above threshold
    c = canvas.Canvas(str(path), pagesize=letter)
    text = c.beginText(50, 750)
    for line in body.splitlines() or [body]:
        # Wrap to ~80 cols so it fits
        for i in range(0, len(line), 80):
            text.textLine(line[i:i + 80])
    c.drawText(text)
    c.showPage()
    c.save()
    return path


def _image_only_pdf(path: Path) -> Path:
    """Pillow image-only PDF — pdftotext returns near-empty output."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1200, 1600), "white")
    d = ImageDraw.Draw(img)
    # Render some text into the image — but it's pixels, not selectable
    # text. pdftotext will return ~0 chars on this PDF.
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36,
        )
    except Exception:
        font = ImageFont.load_default()
    d.text((100, 100), "AFFIDAVIT OF SERVICE", fill="black", font=font)
    d.text((100, 200), "Civil Action No. 2:21-CV-226-RWS",
           fill="black", font=font)
    img.save(str(path), "PDF", resolution=100.0)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / shared fakes
# ─────────────────────────────────────────────────────────────────────────────

def _layout_for(tmp_path: Path) -> dict:
    """Build a normalized layout dict pointing at tmp_path."""
    return {
        "root":      tmp_path,
        "subdirs":   {"evidence": "."},
        "recursive": True,
    }


class _FakeOcrmypdf:
    """
    Stand-in for ocrmypdf: copies INPUT to OUTPUT, optionally simulating
    the addition of a text layer. Tracks invocations.

    Captures the real subprocess.run at construction time so the fake
    can delegate pdftotext (and any other non-ocrmypdf call) to the
    real implementation even after `patch.object(ocr.subprocess, "run", ...)`
    has globally rebound subprocess.run to this instance.
    """
    def __init__(self, outcome: str = "success", returncode: int = 0):
        self.outcome = outcome
        self.returncode = returncode
        self.calls: list[list[str]] = []
        # IMPORTANT: capture BEFORE the patch is installed.
        self._real_run = subprocess.run

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        if cmd[0] == "ocrmypdf":
            _, out = Path(cmd[-2]), Path(cmd[-1])
            if self.outcome == "success":
                _text_pdf(out, body="OCR'D TEXT LAYER " * 30)
                return subprocess.CompletedProcess(cmd, 0, b"", b"")
            if self.outcome == "fail":
                return subprocess.CompletedProcess(
                    cmd, 1, b"", b"PriorOcrFoundError: page already has text",
                )
            if self.outcome == "timeout":
                raise subprocess.TimeoutExpired(cmd, 10)
        # Anything else (pdftotext, sha256sum, ...): real subprocess.run
        return self._real_run(cmd, *args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSkipAlreadyTextPdf:
    def test_text_pdf_classified_already_text(self, tmp_path: Path):
        p = _text_pdf(tmp_path / "has-text.pdf")
        # Use the high-level worker function directly
        result = ocr.process_one_pdf(
            str(p), optimize_level=1, ocr_jobs_per_file=1,
            text_threshold=ocr.DEFAULT_TEXT_THRESHOLD, dry_run=False,
        )
        assert result["status"] == "already_text"
        assert result["pre_chars"] >= ocr.DEFAULT_TEXT_THRESHOLD


class TestOcrImageOnlyPdf:
    def test_image_only_pdf_invokes_ocrmypdf_and_swaps(self, tmp_path: Path):
        p = _image_only_pdf(tmp_path / "image-only.pdf")
        # Sanity: pre-OCR pdftotext returns sub-threshold
        pre = ocr._probe_chars(p)
        assert pre < ocr.DEFAULT_TEXT_THRESHOLD

        fake = _FakeOcrmypdf(outcome="success")
        with patch.object(ocr.subprocess, "run", side_effect=fake):
            result = ocr.process_one_pdf(
                str(p), optimize_level=1, ocr_jobs_per_file=1,
                text_threshold=ocr.DEFAULT_TEXT_THRESHOLD, dry_run=False,
            )
        assert result["status"] == "ocr_applied"
        # Confirm the original file got swapped with the OCR'd output —
        # the new pdftotext probe should now see the simulated text layer.
        post = ocr._probe_chars(p)
        assert post >= ocr.DEFAULT_TEXT_THRESHOLD
        # And ocrmypdf was actually called once with --skip-text
        ocr_calls = [c for c in fake.calls if c[0] == "ocrmypdf"]
        assert len(ocr_calls) == 1
        assert "--skip-text" in ocr_calls[0]


class TestIdempotency:
    def test_second_run_is_zero_ocr_applied(self, tmp_path: Path):
        # Two image-only PDFs.
        a = _image_only_pdf(tmp_path / "a.pdf")
        b = _image_only_pdf(tmp_path / "b.pdf")
        fake = _FakeOcrmypdf(outcome="success")

        # First sweep — process both. Use jobs=1 for determinism.
        layout = _layout_for(tmp_path)
        with patch.object(ocr.subprocess, "run", side_effect=fake):
            r1 = [
                ocr.process_one_pdf(str(p), 1, 1,
                                    ocr.DEFAULT_TEXT_THRESHOLD, False)
                for p in (a, b)
            ]
        assert sum(1 for r in r1 if r["status"] == "ocr_applied") == 2

        # Second sweep — _FakeOcrmypdf would still simulate success if called,
        # but the probe should classify the now-text-layer PDFs as
        # already_text and skip the ocrmypdf call entirely.
        fake2 = _FakeOcrmypdf(outcome="success")
        with patch.object(ocr.subprocess, "run", side_effect=fake2):
            r2 = [
                ocr.process_one_pdf(str(p), 1, 1,
                                    ocr.DEFAULT_TEXT_THRESHOLD, False)
                for p in (a, b)
            ]
        assert sum(1 for r in r2 if r["status"] == "ocr_applied") == 0
        assert sum(1 for r in r2 if r["status"] == "already_text") == 2
        assert all(c[0] != "ocrmypdf" for c in fake2.calls)


class TestManifestWritten:
    def test_manifest_carries_expected_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        a = _text_pdf(tmp_path / "text.pdf")
        b = _image_only_pdf(tmp_path / "image-only.pdf")

        # Redirect AUDIT_DIR + lock to tmp_path so the test is hermetic.
        monkeypatch.setattr(ocr, "AUDIT_DIR", tmp_path / "audits")
        monkeypatch.setattr(ocr, "_lock_path",
                            lambda slug: tmp_path / f"ocr-{slug}.lock")
        monkeypatch.setattr(
            ocr, "fetch_case_layout",
            lambda slug: _layout_for(tmp_path),
        )

        fake = _FakeOcrmypdf(outcome="success")
        with patch.object(ocr.subprocess, "run", side_effect=fake):
            rc = ocr.main(["--case-slug", "test-case", "--jobs", "1"])
        assert rc == 0

        # Locate the manifest
        mfs = list((tmp_path / "audits").glob("ocr-sweep-test-case-*.json"))
        assert len(mfs) == 1
        m = json.loads(mfs[0].read_text())
        assert m["case_slug"] == "test-case"
        assert m["total_pdfs"] == 2
        assert m["already_text"] == 1
        assert m["ocr_applied"] == 1
        assert m["errors_count"] == 0
        assert m["dry_run"] is False
        assert m["jobs"] == 1
        assert m["layout_recursive"] is True


class TestLockFile:
    def test_concurrent_run_refused(self, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(ocr, "_lock_path",
                            lambda slug: tmp_path / f"ocr-{slug}.lock")
        # Pre-create the lock with a fresh mtime
        lock = tmp_path / "ocr-c.lock"
        lock.write_text("99999\n")
        try:
            ocr.acquire_lock("c", force=False)
        except SystemExit as exc:
            assert "another sweep" in str(exc) or "lock" in str(exc).lower()
        else:
            raise AssertionError("expected SystemExit when lock is fresh")

    def test_force_overrides_stale_lock(self, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch):
        import time
        monkeypatch.setattr(ocr, "_lock_path",
                            lambda slug: tmp_path / f"ocr-{slug}.lock")
        lock = tmp_path / "ocr-c.lock"
        lock.write_text("99999\n")
        # Make it 7 hours old
        old = time.time() - (7 * 3600)
        os.utime(lock, (old, old))
        # --force should remove and re-create
        new_lock = ocr.acquire_lock("c", force=True)
        try:
            assert new_lock.exists()
            assert str(os.getpid()) in new_lock.read_text()
        finally:
            ocr.release_lock(new_lock)


class TestDryRunSafety:
    def test_dry_run_does_not_invoke_ocrmypdf(self, tmp_path: Path):
        p = _image_only_pdf(tmp_path / "image-only.pdf")
        original_bytes = p.read_bytes()

        fake = _FakeOcrmypdf(outcome="success")
        with patch.object(ocr.subprocess, "run", side_effect=fake):
            result = ocr.process_one_pdf(
                str(p), optimize_level=1, ocr_jobs_per_file=1,
                text_threshold=ocr.DEFAULT_TEXT_THRESHOLD, dry_run=True,
            )
        assert result["status"] == "skipped"
        assert result["detail"] == "dry_run"
        # File untouched — byte-for-byte identical
        assert p.read_bytes() == original_bytes
        # ocrmypdf NOT called
        assert all(c[0] != "ocrmypdf" for c in fake.calls)


class TestCorruptPdfPreservesOriginal:
    def test_ocrmypdf_failure_leaves_original_intact(self, tmp_path: Path):
        p = _image_only_pdf(tmp_path / "corrupt.pdf")
        original_sha = subprocess.run(
            ["sha256sum", str(p)], capture_output=True,
        ).stdout

        fake = _FakeOcrmypdf(outcome="fail")
        with patch.object(ocr.subprocess, "run", side_effect=fake):
            result = ocr.process_one_pdf(
                str(p), 1, 1, ocr.DEFAULT_TEXT_THRESHOLD, False,
            )
        assert result["status"] == "error"
        assert "rc=1" in result["detail"]
        # The original file is untouched (no swap happened)
        post_sha = subprocess.run(
            ["sha256sum", str(p)], capture_output=True,
        ).stdout
        assert original_sha == post_sha
        # And no .ocr.tmp left behind
        assert not (tmp_path / "corrupt.pdf.ocr.tmp").exists()

    def test_ocrmypdf_timeout_leaves_original_intact(self, tmp_path: Path):
        p = _image_only_pdf(tmp_path / "wedge.pdf")
        before = p.read_bytes()
        fake = _FakeOcrmypdf(outcome="timeout")
        with patch.object(ocr.subprocess, "run", side_effect=fake):
            result = ocr.process_one_pdf(
                str(p), 1, 1, ocr.DEFAULT_TEXT_THRESHOLD, False,
            )
        assert result["status"] == "error"
        assert result["detail"] == "timeout"
        assert p.read_bytes() == before


class TestPdfDiscovery:
    def test_iter_skips_eadir_and_dotfiles(self, tmp_path: Path):
        # Build: tmp/Discovery/{real.pdf, @eaDir/junk.pdf, .hidden.pdf, sub/deep.pdf}
        (tmp_path / "Discovery").mkdir()
        _text_pdf(tmp_path / "Discovery" / "real.pdf")
        (tmp_path / "Discovery" / "@eaDir").mkdir()
        _text_pdf(tmp_path / "Discovery" / "@eaDir" / "junk.pdf")
        _text_pdf(tmp_path / "Discovery" / ".hidden.pdf")
        (tmp_path / "Discovery" / "sub").mkdir()
        _text_pdf(tmp_path / "Discovery" / "sub" / "deep.pdf")

        layout = {
            "root":      tmp_path,
            "subdirs":   {"evidence": "Discovery"},
            "recursive": True,
        }
        names = sorted(p.name for p in ocr.iter_case_pdfs(layout))
        assert names == ["deep.pdf", "real.pdf"]
