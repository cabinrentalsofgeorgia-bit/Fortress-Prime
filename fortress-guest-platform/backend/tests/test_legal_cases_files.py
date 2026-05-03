"""
Tests for the legal-cases /files + /download endpoints with the
nullable per-case nas_layout column.

LegacySession is fully stubbed; filesystem fixtures use tmp_path.
No real DB or NAS access.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

import backend.api.legal_cases as lc
from backend.api.legal_cases import (
    _DEFAULT_SUBDIR_MAP,
    _is_under,
    _resolve_case_layout,
    _walk_case_subdir,
    download_case_file,
    list_case_files,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────

def _row(nas_layout=None, id_=1):
    """Build a SQLAlchemy-Row-shaped namespace for case lookup."""
    return SimpleNamespace(id=id_, nas_layout=nas_layout)


def _patch_legacy_session(monkeypatch, row_to_return):
    """Replace LegacySession() with a context-managed mock returning one row."""
    session = AsyncMock()
    result = AsyncMock()
    result.fetchone = lambda: row_to_return  # synchronous on Result, mirrors live API
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(lc, "LegacySession", fake_session)
    return session


def _seed_canonical_case(root: Path, slug: str) -> dict[str, list[str]]:
    """Create the 6-subdir tree under root/slug, return {subdir: [filenames]}."""
    placed: dict[str, list[str]] = {}
    layout = {
        "filings/incoming":  ["Complaint.pdf"],
        "filings/outgoing":  ["Answer.docx", "Motion.docx"],
        "correspondence":    ["letter1.txt", "letter2.txt"],
        "evidence":          ["exhibit_a.jpg"],
        "certified_mail":    [],            # subdir absent on purpose
        "receipts":          ["receipt1.pdf"],
    }
    case_root = root / slug
    for sub, files in layout.items():
        if not files and sub == "certified_mail":
            continue   # skip — proves the "missing subdir silently skipped" path
        d = case_root / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_bytes(b"x")
        placed[sub] = files
    return placed


# ─────────────────────────────────────────────────────────────────────────────
# 1. test_list_files_default_layout — Generali-style canonical case
# ─────────────────────────────────────────────────────────────────────────────

class TestListFilesDefaultLayout:
    @pytest.mark.asyncio
    async def test_list_files_default_layout_walks_canonical_subdirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Point NAS_LEGAL_ROOT at our tmp dir
        monkeypatch.setattr(lc, "NAS_LEGAL_ROOT", str(tmp_path))
        slug = "fish-trap-suv2026000013"
        _seed_canonical_case(tmp_path, slug)
        _patch_legacy_session(monkeypatch, _row(nas_layout=None, id_=2))

        result = await list_case_files(slug)
        assert result["case_slug"] == slug
        # filings/incoming(1) + filings/outgoing(2) + correspondence(2)
        # + evidence(1) + receipts(1) = 7. certified_mail subdir was skipped
        # by the seed helper so the "missing subdir silent skip" branch fires.
        assert result["total"] == 7
        names = {f["filename"] for f in result["files"]}
        assert names == {
            "Complaint.pdf", "Answer.docx", "Motion.docx",
            "letter1.txt", "letter2.txt", "exhibit_a.jpg", "receipt1.pdf",
        }
        # Logical subdir names returned to UI:
        subdirs = {f["subdir"] for f in result["files"]}
        assert subdirs <= set(_DEFAULT_SUBDIR_MAP.keys())
        # Each entry has a download_url referencing the slug
        for f in result["files"]:
            parsed = urlsplit(f["download_url"])
            params = parse_qs(parsed.query)
            assert parsed.path == f"/api/internal/legal/cases/{slug}/download/{f['filename']}"
            assert params == {
                "subdir": [f["subdir"]],
                "relative_path": [f["relative_path"]],
            }


# ─────────────────────────────────────────────────────────────────────────────
# 2. test_list_files_custom_layout — synthetic 7IL-shaped case
# ─────────────────────────────────────────────────────────────────────────────

class TestListFilesCustomLayout:
    @pytest.mark.asyncio
    async def test_list_files_custom_layout_resolves_per_case_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Build a real-world-shaped tree:
        #   tmp/Business_Legal/# Pleadings - GAND/Complaint.pdf
        #   tmp/Business_Legal/Discovery/RFP_Resp.pdf
        #   tmp/Business_Legal/Correspondence/oc_email.eml
        bl = tmp_path / "Business_Legal"
        (bl / "# Pleadings - GAND").mkdir(parents=True)
        (bl / "# Pleadings - GAND" / "Complaint.pdf").write_bytes(b"complaint")
        (bl / "Discovery").mkdir()
        (bl / "Discovery" / "RFP_Resp.pdf").write_bytes(b"rfp-response")
        (bl / "Correspondence").mkdir()
        (bl / "Correspondence" / "oc_email.eml").write_bytes(b"email")

        layout = {
            "root": str(bl),
            "subdirs": {
                "filings_incoming": "# Pleadings - GAND",
                "evidence":         "Discovery",
                "correspondence":   "Correspondence",
                # filings_outgoing / certified_mail / receipts not provided
            },
        }
        slug = "7il-v-knight"
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        result = await list_case_files(slug)
        assert result["total"] == 3
        names = {(f["subdir"], f["filename"]) for f in result["files"]}
        assert names == {
            ("filings_incoming", "Complaint.pdf"),
            ("evidence",         "RFP_Resp.pdf"),
            ("correspondence",   "oc_email.eml"),
        }


class TestListFilesWave7Layout:
    @pytest.mark.asyncio
    async def test_list_files_wave7_layout_walks_curated_paths_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = tmp_path / "Business_Legal" / "7il-v-knight-ndga-ii"
        (root / "curated" / "pleadings").mkdir(parents=True)
        (root / "curated" / "pleadings" / "Complaint.pdf").write_bytes(b"x")
        (root / "curated" / "emails").mkdir()
        (root / "curated" / "emails" / "Argo.eml").write_bytes(b"x")
        (root / "curated" / "private").mkdir()
        (root / "curated" / "private" / "DoNotServe.pdf").write_bytes(b"x")
        (root / "legacy_dump").mkdir()
        (root / "legacy_dump" / "Poison.pdf").write_bytes(b"x")

        layout = {
            "primary_root": str(root),
            "include_subdirs": ["curated"],
            "exclude_subdirs": ["curated/private"],
        }
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        result = await list_case_files("7il-v-knight-ndga-ii")

        assert result["total"] == 2
        names = {(f["subdir"], f["relative_path"], f["filename"]) for f in result["files"]}
        assert names == {
            ("curated", "emails/Argo.eml", "Argo.eml"),
            ("curated", "pleadings/Complaint.pdf", "Complaint.pdf"),
        }
        argo = next(f for f in result["files"] if f["filename"] == "Argo.eml")
        parsed = urlsplit(argo["download_url"])
        assert parsed.path == "/api/internal/legal/cases/7il-v-knight-ndga-ii/download/Argo.eml"
        assert parse_qs(parsed.query) == {
            "subdir": ["curated"],
            "relative_path": ["emails/Argo.eml"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. test_list_files_recursive_flag — nested folder structure
# ─────────────────────────────────────────────────────────────────────────────

class TestListFilesRecursiveFlag:
    @pytest.mark.asyncio
    async def test_recursive_walks_nested_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        bl = tmp_path / "Business_Legal"
        d = bl / "Discovery"
        (d / "Production").mkdir(parents=True)
        (d / "Production" / "Set1.pdf").write_bytes(b"x")
        (d / "Production" / "Set2.pdf").write_bytes(b"x")
        (d / "Depo Exhibits" / "Wilson").mkdir(parents=True)
        (d / "Depo Exhibits" / "Wilson" / "Exhibit_M.pdf").write_bytes(b"x")
        (d / "@eaDir" / "thumbs").mkdir(parents=True)         # synology garbage
        (d / "@eaDir" / "thumbs" / "thumb.jpg").write_bytes(b"junk")
        (d / ".DS_Store").write_bytes(b"junk")                # mac metadata

        layout = {"root": str(bl), "subdirs": {"evidence": "Discovery"},
                  "recursive": True}
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        result = await list_case_files("nested-case")
        names = sorted(f["filename"] for f in result["files"])
        assert names == ["Exhibit_M.pdf", "Set1.pdf", "Set2.pdf"]
        # @eaDir AND .DS_Store filtered out:
        joined = " ".join(names)
        assert "@eaDir" not in joined and "DS_Store" not in joined
        # Each entry carries a relative_path so the UI can render the tree:
        rel = {f["relative_path"] for f in result["files"]}
        assert "Production/Set1.pdf" in rel
        assert "Depo Exhibits/Wilson/Exhibit_M.pdf" in rel

    @pytest.mark.asyncio
    async def test_non_recursive_default_does_not_descend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        bl = tmp_path / "Business_Legal"
        (bl / "Discovery" / "Nested").mkdir(parents=True)
        (bl / "Discovery" / "top.pdf").write_bytes(b"x")
        (bl / "Discovery" / "Nested" / "deep.pdf").write_bytes(b"x")

        layout = {"root": str(bl), "subdirs": {"evidence": "Discovery"}}
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        result = await list_case_files("flat-case")
        names = {f["filename"] for f in result["files"]}
        assert names == {"top.pdf"}, "non-recursive must skip nested dirs"


# ─────────────────────────────────────────────────────────────────────────────
# 4. test_list_files_missing_subdir_silent_skip
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingSubdirSilentSkip:
    @pytest.mark.asyncio
    async def test_missing_canonical_subdir_returns_empty_total(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Only create one of the six canonical subdirs.
        slug = "sparse-case"
        (tmp_path / slug / "evidence").mkdir(parents=True)
        (tmp_path / slug / "evidence" / "only.pdf").write_bytes(b"x")
        monkeypatch.setattr(lc, "NAS_LEGAL_ROOT", str(tmp_path))
        _patch_legacy_session(monkeypatch, _row(nas_layout=None))

        result = await list_case_files(slug)
        assert result["total"] == 1
        assert result["files"][0]["subdir"] == "evidence"


# ─────────────────────────────────────────────────────────────────────────────
# 5. test_list_files_nonexistent_case_404
# ─────────────────────────────────────────────────────────────────────────────

class TestNonexistentCase404:
    @pytest.mark.asyncio
    async def test_unknown_slug_raises_404(self, monkeypatch: pytest.MonkeyPatch):
        from fastapi import HTTPException
        _patch_legacy_session(monkeypatch, None)        # no row returned
        try:
            await list_case_files("ghost-case")
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("expected 404 for unknown case_slug")


# ─────────────────────────────────────────────────────────────────────────────
# 6. test_download_respects_custom_layout
# ─────────────────────────────────────────────────────────────────────────────

class TestDownloadCustomLayout:
    @pytest.mark.asyncio
    async def test_download_finds_file_under_custom_layout_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        bl = tmp_path / "Business_Legal"
        (bl / "# Pleadings - GAND").mkdir(parents=True)
        target = bl / "# Pleadings - GAND" / "#1 Complaint.pdf"
        target.write_bytes(b"<<pdf>>")
        layout = {"root": str(bl),
                  "subdirs": {"filings_incoming": "# Pleadings - GAND"}}
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        # The download handler returns a FileResponse — easiest verification
        # is to assert it doesn't raise + the path resolves to our file.
        from fastapi.responses import FileResponse
        resp = await download_case_file("7il", "#1 Complaint.pdf")
        assert isinstance(resp, FileResponse)
        assert Path(resp.path).resolve() == target.resolve()


class TestDownloadStableAddressing:
    @pytest.mark.asyncio
    async def test_relative_path_selects_nested_duplicate_filename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        case_root = tmp_path / "case"
        email_target = case_root / "curated" / "emails" / "Report.pdf"
        pleading_target = case_root / "curated" / "pleadings" / "Report.pdf"
        email_target.parent.mkdir(parents=True)
        pleading_target.parent.mkdir(parents=True)
        email_target.write_bytes(b"email")
        pleading_target.write_bytes(b"pleading")

        layout = {
            "primary_root": str(case_root),
            "include_subdirs": ["curated"],
        }
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        from fastapi.responses import FileResponse
        resp = await download_case_file(
            "case",
            "Report.pdf",
            subdir="curated",
            relative_path="emails/Report.pdf",
        )
        assert isinstance(resp, FileResponse)
        assert Path(resp.path).resolve() == email_target.resolve()

    @pytest.mark.asyncio
    async def test_filename_only_duplicate_download_returns_conflict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        case_root = tmp_path / "case"
        for folder in ("emails", "pleadings"):
            target = case_root / "curated" / folder / "Report.pdf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(folder.encode())

        layout = {
            "primary_root": str(case_root),
            "include_subdirs": ["curated"],
        }
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await download_case_file("case", "Report.pdf")
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_relative_path_traversal_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        case_root = tmp_path / "case"
        (case_root / "curated").mkdir(parents=True)
        layout = {
            "primary_root": str(case_root),
            "include_subdirs": ["curated"],
        }
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await download_case_file(
                "case",
                "secret.pdf",
                subdir="curated",
                relative_path="../secret.pdf",
            )
        assert exc_info.value.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 7. test_download_path_traversal_rejected
# ─────────────────────────────────────────────────────────────────────────────

class TestPathTraversalRejected:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("evil", [
        "../etc/passwd", "..\\..\\Windows\\System32\\config\\sam",
        "subdir/file.pdf", "/absolute/path",
    ])
    async def test_evil_filename_rejected_400(
        self, monkeypatch: pytest.MonkeyPatch, evil: str,
    ):
        from fastapi import HTTPException
        # Note: handler rejects before touching DB/filesystem.
        try:
            await download_case_file("any-case", evil)
        except HTTPException as exc:
            assert exc.status_code == 400, f"expected 400 for {evil!r}"
        else:
            raise AssertionError(f"expected 400 for {evil!r}")

    @pytest.mark.asyncio
    async def test_resolved_path_must_stay_under_case_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Build: case_root/evidence/safe.pdf, plus a symlink in evidence/
        # that escapes case_root pointing at outside_secret.txt.
        from fastapi import HTTPException
        case_root = tmp_path / "case_dir"
        outside = tmp_path / "outside_secret.txt"
        outside.write_bytes(b"top secret")

        ev = case_root / "evidence"
        ev.mkdir(parents=True)
        (ev / "safe.pdf").write_bytes(b"x")
        (ev / "escape.lnk").symlink_to(outside)

        layout = {"root": str(case_root),
                  "subdirs": {"evidence": "evidence"}}
        _patch_legacy_session(monkeypatch, _row(nas_layout=layout))

        # safe.pdf works
        from fastapi.responses import FileResponse
        ok = await download_case_file("c", "safe.pdf")
        assert isinstance(ok, FileResponse)

        # escape.lnk resolves outside case_root → 404 (skipped, not served)
        try:
            await download_case_file("c", "escape.lnk")
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("symlink escape should not have been served")


# ─────────────────────────────────────────────────────────────────────────────
# Helper-function unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_resolve_layout_null_returns_canonical(self, monkeypatch):
        monkeypatch.setattr(lc, "NAS_LEGAL_ROOT", "/mnt/x/legal")
        root, m, rec = _resolve_case_layout("fish-trap", None)
        assert root == Path("/mnt/x/legal/fish-trap")
        assert m == _DEFAULT_SUBDIR_MAP
        assert rec is False

    def test_resolve_layout_populated_returns_custom(self):
        layout = {"root": "/mnt/y", "subdirs": {"evidence": "ev"}, "recursive": True}
        root, m, rec = _resolve_case_layout("any", layout)
        assert root == Path("/mnt/y")
        assert m == {"evidence": "ev"}
        assert rec is True

    def test_resolve_layout_wave7_shape_defaults_recursive_true(self):
        layout = {
            "primary_root": "/mnt/business/7il-v-knight-ndga-i",
            "include_subdirs": ["curated", "case-i-context"],
        }
        root, m, rec = _resolve_case_layout("any", layout)
        assert root == Path("/mnt/business/7il-v-knight-ndga-i")
        assert m == {"curated": "curated", "case-i-context": "case-i-context"}
        assert rec is True

    def test_resolve_layout_skips_empty_subdir_values(self):
        layout = {"root": "/mnt/y", "subdirs": {"a": "x", "b": "", "c": None}}
        _, m, _ = _resolve_case_layout("any", layout)
        assert m == {"a": "x"}

    def test_walk_skips_eadir_and_dotfiles(self, tmp_path: Path):
        (tmp_path / "@eaDir").mkdir()
        (tmp_path / "@eaDir" / "thumb.jpg").write_bytes(b"x")
        (tmp_path / ".DS_Store").write_bytes(b"x")
        (tmp_path / "real.pdf").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.pdf").write_bytes(b"x")
        (tmp_path / "sub" / "@eaDir").mkdir()
        (tmp_path / "sub" / "@eaDir" / "junk.txt").write_bytes(b"x")

        flat = _walk_case_subdir(tmp_path, recursive=False)
        assert [p.name for p in flat] == ["real.pdf"]

        rec = _walk_case_subdir(tmp_path, recursive=True)
        assert sorted(p.name for p in rec) == ["nested.pdf", "real.pdf"]

    def test_walk_honors_layout_excludes(self, tmp_path: Path):
        (tmp_path / "curated" / "public").mkdir(parents=True)
        (tmp_path / "curated" / "public" / "ok.pdf").write_bytes(b"x")
        (tmp_path / "curated" / "private").mkdir()
        (tmp_path / "curated" / "private" / "skip.pdf").write_bytes(b"x")

        rec = _walk_case_subdir(
            tmp_path / "curated",
            recursive=True,
            case_root=tmp_path,
            exclude_subdirs={"curated/private"},
        )

        assert [p.name for p in rec] == ["ok.pdf"]

    def test_is_under_rejects_paths_outside_parent(self, tmp_path: Path):
        parent = tmp_path / "case"
        parent.mkdir()
        (parent / "ok.txt").write_bytes(b"x")
        (tmp_path / "outside.txt").write_bytes(b"x")
        assert _is_under(parent / "ok.txt", parent) is True
        assert _is_under(tmp_path / "outside.txt", parent) is False
