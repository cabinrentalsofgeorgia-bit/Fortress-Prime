"""
Unit tests for the ARM64 verification gate in scripts/nim_pull_to_nas.py.

All docker/subprocess calls are mocked — no real docker daemon needed in CI.

Coverage targets per brief:
  - Stage 1 PASS (arm64 + x86-64 in manifest index)
  - Stage 1 FAIL (x86-64 only)
  - Stage 1 PASS + Stage 2 ELF FAIL (tonight's incident class)
  - Stage 1 PASS + Stage 2 ELF PASS (overall PASS)
  - docker pull failure → ERROR
  - Cleanup invariant: scratch tags/containers/temp files gone even on exception
  - --force-skip-verification flag logs warning and skips gate
  - verify_nas_tar: PASS on genuine arm64 tar, FAIL on mislabeled x86-64 tar
"""
from __future__ import annotations

import gzip
import io
import json
import tarfile
import tempfile
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.nim_pull_to_nas import (
    _check_layer_elf,
    _extract_binary_from_layer_bytes,
    _parse_elf_is_aarch64,
    verify_arm64_with_docker,
    verify_nas_tar,
)


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

ELF_OUTPUT_AARCH64 = (
    "ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV), "
    "dynamically linked, interpreter /lib/ld-linux-aarch64.so.1"
)
ELF_OUTPUT_X86_64 = (
    "ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), "
    "dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2"
)

MANIFEST_ARM64_AND_AMD64 = json.dumps({
    "manifests": [
        {
            "platform": {"architecture": "amd64", "os": "linux"},
            "digest": "sha256:amd64abc000",
        },
        {
            "platform": {"architecture": "arm64", "os": "linux"},
            "digest": "sha256:arm64abc000",
        },
    ]
})

MANIFEST_X86_ONLY = json.dumps({
    "manifests": [
        {
            "platform": {"architecture": "amd64", "os": "linux"},
            "digest": "sha256:amd64abc000",
        },
    ]
})


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    """Build a fake subprocess.CompletedProcess-like mock."""
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _make_gzip_tar_layer(path: str, content: bytes) -> bytes:
    """Build a minimal gzip-compressed OCI layer blob containing `content` at `path`."""
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w") as tf:
        info = tarfile.TarInfo(name=path)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))

    gz_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
        gz.write(inner.getvalue())
    return gz_buf.getvalue()


def _make_nas_image_tar(
    arch: str = "arm64",
    layer_path: str = "./bin/ls",
    layer_content: bytes = b"fake-binary",
) -> Path:
    """
    Build a minimal NAS image.tar (outer tar wrapping config.json, manifest.json,
    and one gzip-compressed layer) for use with verify_nas_tar().
    """
    config = {
        "architecture": arch,
        "os": "linux",
    }
    config_bytes = json.dumps(config).encode()
    config_hash = "a" * 64

    layer_bytes = _make_gzip_tar_layer(layer_path, layer_content)
    layer_digest = "b" * 64

    manifest_json_content = json.dumps([
        {
            "Config": f"{config_hash}.json",
            "RepoTags": [f"nvcr.io/nim/nvidia/test-model:latest"],
            "Layers": [f"{layer_digest}/layer.tar"],
        }
    ]).encode()

    tmp = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    tmp.close()
    tar_path = Path(tmp.name)

    with tarfile.open(tar_path, "w") as tf:
        for name, data in [
            (f"{config_hash}.json", config_bytes),
            ("manifest.json", manifest_json_content),
        ]:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        # Layer directory + blob
        dir_info = tarfile.TarInfo(name=f"{layer_digest}/")
        dir_info.type = tarfile.DIRTYPE
        tf.addfile(dir_info)

        layer_info = tarfile.TarInfo(name=f"{layer_digest}/layer.tar")
        layer_info.size = len(layer_bytes)
        tf.addfile(layer_info, io.BytesIO(layer_bytes))

    return tar_path


# ---------------------------------------------------------------------------
# _parse_elf_is_aarch64
# ---------------------------------------------------------------------------

def test_parse_elf_aarch64_returns_true():
    assert _parse_elf_is_aarch64(ELF_OUTPUT_AARCH64) is True


def test_parse_elf_x86_64_returns_false():
    assert _parse_elf_is_aarch64(ELF_OUTPUT_X86_64) is False


def test_parse_elf_unknown_string_returns_false():
    assert _parse_elf_is_aarch64("data") is False


def test_parse_elf_case_insensitive():
    assert _parse_elf_is_aarch64("ELF 64-bit ... ARM AARCH64") is True


# ---------------------------------------------------------------------------
# _extract_binary_from_layer_bytes
# ---------------------------------------------------------------------------

def test_extract_binary_found_at_bin_ls():
    layer = _make_gzip_tar_layer("./bin/ls", b"binary-payload")
    assert _extract_binary_from_layer_bytes(layer) == b"binary-payload"


def test_extract_binary_found_at_usr_bin_ls():
    layer = _make_gzip_tar_layer("./usr/bin/ls", b"usr-bin-payload")
    assert _extract_binary_from_layer_bytes(layer) == b"usr-bin-payload"


def test_extract_binary_not_found_returns_empty():
    layer = _make_gzip_tar_layer("./etc/hosts", b"other-content")
    assert _extract_binary_from_layer_bytes(layer) == b""


def test_extract_binary_corrupt_layer_returns_empty():
    assert _extract_binary_from_layer_bytes(b"not-gzip-data") == b""


# ---------------------------------------------------------------------------
# _check_layer_elf
# ---------------------------------------------------------------------------

@patch("scripts.nim_pull_to_nas.subprocess.run")
def test_check_layer_elf_aarch64(mock_run):
    layer = _make_gzip_tar_layer("./bin/ls", b"fake-aarch64")
    mock_run.return_value = _proc(stdout=f"/tmp/x: {ELF_OUTPUT_AARCH64}\n")
    is_aarch64, elf_out = _check_layer_elf(layer)
    assert is_aarch64 is True
    assert "ARM aarch64" in elf_out


@patch("scripts.nim_pull_to_nas.subprocess.run")
def test_check_layer_elf_x86_64_is_tonight_incident(mock_run):
    """Manifest claims arm64, layer binary is x86-64 — the incident that triggered this work."""
    layer = _make_gzip_tar_layer("./bin/ls", b"fake-x86")
    mock_run.return_value = _proc(stdout=f"/tmp/x: {ELF_OUTPUT_X86_64}\n")
    is_aarch64, elf_out = _check_layer_elf(layer)
    assert is_aarch64 is False
    assert "x86-64" in elf_out


@patch("scripts.nim_pull_to_nas.subprocess.run")
def test_check_layer_elf_temp_file_cleaned_up(mock_run):
    layer = _make_gzip_tar_layer("./bin/ls", b"fake")
    mock_run.return_value = _proc(stdout=f"/tmp/x: {ELF_OUTPUT_AARCH64}\n")

    _check_layer_elf(layer)

    # Retrieve the temp path that was passed to `file` and confirm it is gone
    file_cmd = mock_run.call_args[0][0]
    tmp_path = Path(file_cmd[1])
    assert not tmp_path.exists(), f"Temp file not cleaned up: {tmp_path}"


# ---------------------------------------------------------------------------
# verify_arm64_with_docker — stage 1 tests
# ---------------------------------------------------------------------------

def test_stage1_manifest_fail_x86_only():
    """Only x86-64 platform in manifest → MANIFEST_FAIL, no docker pull."""
    # container_id is None on MANIFEST_FAIL so docker rm is skipped; docker rmi always runs
    calls = [
        _proc(stdout=MANIFEST_X86_ONLY),  # manifest inspect
        _proc(),                            # docker rmi (cleanup — scratch_tag always set)
    ]
    mock = MagicMock(side_effect=calls)
    result = verify_arm64_with_docker("nvcr.io/nim/nvidia/model:latest", _run=mock)
    assert result.verdict == "MANIFEST_FAIL"
    assert result.stage1_manifest_arm64 is False
    # docker pull must NOT have been called
    pull_calls = [c for c in mock.call_args_list if c.args[0][1] == "pull"]
    assert len(pull_calls) == 0


def test_stage1_pass_with_arm64_and_amd64_platforms():
    """arm64 present alongside amd64 → stage 1 PASS."""
    calls = [
        _proc(stdout=MANIFEST_ARM64_AND_AMD64),   # manifest inspect
        _proc(),                                    # docker pull
        _proc(),                                    # docker tag
        _proc(stdout="container123"),               # docker create
        _proc(),                                    # docker cp /bin/ls
        _proc(stdout=f"/tmp/p: {ELF_OUTPUT_AARCH64}"),  # file
        _proc(),                                    # docker rm
        _proc(),                                    # docker rmi
    ]
    mock = MagicMock(side_effect=calls)
    result = verify_arm64_with_docker("nvcr.io/nim/nvidia/model:latest", _run=mock)
    assert result.stage1_manifest_arm64 is True


# ---------------------------------------------------------------------------
# verify_arm64_with_docker — stage 2 ELF tests
# ---------------------------------------------------------------------------

def test_stage2_elf_fail_is_tonights_incident_class():
    """Stage 1 PASS (arm64 in manifest), Stage 2 FAIL (binary is x86-64) → ELF_FAIL."""
    calls = [
        _proc(stdout=MANIFEST_ARM64_AND_AMD64),
        _proc(),
        _proc(),
        _proc(stdout="ctr123"),
        _proc(),
        _proc(stdout=f"/tmp/p: {ELF_OUTPUT_X86_64}"),
        _proc(),
        _proc(),
    ]
    mock = MagicMock(side_effect=calls)
    result = verify_arm64_with_docker("nvcr.io/nim/nvidia/model:latest", _run=mock)
    assert result.verdict == "ELF_FAIL"
    assert result.stage1_manifest_arm64 is True
    assert result.stage2_elf_aarch64 is False


def test_full_pass_arm64_manifest_and_aarch64_elf():
    calls = [
        _proc(stdout=MANIFEST_ARM64_AND_AMD64),
        _proc(),
        _proc(),
        _proc(stdout="ctr123"),
        _proc(),
        _proc(stdout=f"/tmp/p: {ELF_OUTPUT_AARCH64}"),
        _proc(),
        _proc(),
    ]
    mock = MagicMock(side_effect=calls)
    result = verify_arm64_with_docker("nvcr.io/nim/nvidia/model:latest", _run=mock)
    assert result.verdict == "PASS"
    assert result.stage1_manifest_arm64 is True
    assert result.stage2_elf_aarch64 is True


# ---------------------------------------------------------------------------
# verify_arm64_with_docker — error paths
# ---------------------------------------------------------------------------

def test_docker_pull_failure_returns_error():
    calls = [
        _proc(stdout=MANIFEST_ARM64_AND_AMD64),
        _proc(returncode=1, stderr="pull access denied"),  # docker pull fails
        _proc(),   # docker rm (cleanup)
        _proc(),   # docker rmi (cleanup)
    ]
    mock = MagicMock(side_effect=calls)
    result = verify_arm64_with_docker("nvcr.io/nim/nvidia/model:latest", _run=mock)
    assert result.verdict == "ERROR"
    assert "pull access denied" in result.evidence.get("stage2_pull_error", "")


def test_manifest_inspect_failure_returns_error():
    mock = MagicMock(return_value=_proc(returncode=1, stderr="connection refused"))
    result = verify_arm64_with_docker("nvcr.io/nim/nvidia/model:latest", _run=mock)
    assert result.verdict == "ERROR"


def test_manifest_inspect_invalid_json_returns_error():
    mock = MagicMock(return_value=_proc(stdout="not-json", returncode=0))
    result = verify_arm64_with_docker("nvcr.io/nim/nvidia/model:latest", _run=mock)
    assert result.verdict == "ERROR"


# ---------------------------------------------------------------------------
# Cleanup invariant
# ---------------------------------------------------------------------------

def test_cleanup_runs_even_on_mid_stage_exception():
    """docker rm and docker rmi must be called even when an exception is raised."""
    rm_calls: list[list[str]] = []

    def tracking_run(cmd, **_kwargs):
        rm_calls.append(list(cmd[:2]))
        if cmd[0] == "docker" and cmd[1] == "cp":
            raise RuntimeError("simulated cp failure")
        if cmd[0] == "docker" and cmd[1] == "create":
            return _proc(stdout="container-abc")
        return _proc(stdout=MANIFEST_ARM64_AND_AMD64 if cmd[1] == "manifest" else "")

    with pytest.raises(RuntimeError, match="simulated cp failure"):
        verify_arm64_with_docker(
            "nvcr.io/nim/nvidia/model:latest", _run=tracking_run
        )

    assert ["docker", "rm"] in rm_calls, "docker rm not called in cleanup"
    assert ["docker", "rmi"] in rm_calls, "docker rmi not called in cleanup"


def test_cleanup_temp_file_removed_on_exception():
    """Temp file written before the file check must be gone after exception."""
    created_paths: list[str] = []

    def tracking_run(cmd, **_kwargs):
        if cmd[0] == "docker" and cmd[1] == "manifest":
            return _proc(stdout=MANIFEST_ARM64_AND_AMD64)
        if cmd[0] == "docker" and cmd[1] == "create":
            return _proc(stdout="ctr99")
        if cmd[0] == "docker" and cmd[1] == "cp":
            Path(cmd[3]).write_bytes(b"fake")
            created_paths.append(cmd[3])
            return _proc()
        if cmd[0] == "file":
            raise RuntimeError("file command exploded")
        return _proc()

    with pytest.raises(RuntimeError):
        verify_arm64_with_docker(
            "nvcr.io/nim/nvidia/model:latest", _run=tracking_run
        )

    for p in created_paths:
        assert not Path(p).exists(), f"Temp file not cleaned up: {p}"


# ---------------------------------------------------------------------------
# --force-skip-verification
# ---------------------------------------------------------------------------

def test_force_skip_verification_emits_warning(tmp_path, monkeypatch):
    """pull_to_nas with skip_verification=True must emit a warnings.warn."""
    from scripts.nim_pull_to_nas import pull_to_nas

    out_dir = tmp_path / "nim-cache" / "nim" / "test-model" / "latest"
    out_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "scripts.nim_pull_to_nas.NAS_BASE", tmp_path / "nim-cache" / "nim"
    )

    with (
        patch("scripts.nim_pull_to_nas._read_key", return_value="fake-key"),
        patch("scripts.nim_pull_to_nas._get_token", return_value="fake-token"),
        patch("scripts.nim_pull_to_nas._get_arm64_manifest") as mock_manifest,
        patch("scripts.nim_pull_to_nas._download_blob", return_value=b""),
    ):
        mock_manifest.return_value = ("sha256:abc", {
            "config": {"digest": "sha256:cfg", "size": 10},
            "layers": [{"digest": "sha256:lyr", "size": 100}],
        })

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                pull_to_nas("test-model", tag="latest", skip_verification=True)
            except Exception:
                pass  # tar-building with empty layer bytes may fail; warning fires first

    skip_warnings = [w for w in caught if "VERIFICATION BYPASSED" in str(w.message)]
    assert len(skip_warnings) >= 1, "Expected 'VERIFICATION BYPASSED' warning not raised"


# ---------------------------------------------------------------------------
# verify_nas_tar
# ---------------------------------------------------------------------------

@patch("scripts.nim_pull_to_nas.subprocess.run")
def test_verify_nas_tar_pass_genuine_arm64(mock_run):
    mock_run.return_value = _proc(stdout=f"/tmp/x: {ELF_OUTPUT_AARCH64}\n")
    tar_path = _make_nas_image_tar(arch="arm64", layer_path="./bin/ls")
    try:
        result = verify_nas_tar(tar_path)
        assert result.verdict == "PASS"
        assert result.stage1_manifest_arm64 is True
        assert result.stage2_elf_aarch64 is True
    finally:
        tar_path.unlink(missing_ok=True)


@patch("scripts.nim_pull_to_nas.subprocess.run")
def test_verify_nas_tar_fail_mislabeled_x86(mock_run):
    """NAS tar config says arm64 but layer binary is x86-64 — catches mislabeled images."""
    mock_run.return_value = _proc(stdout=f"/tmp/x: {ELF_OUTPUT_X86_64}\n")
    tar_path = _make_nas_image_tar(arch="arm64", layer_path="./bin/ls")
    try:
        result = verify_nas_tar(tar_path)
        assert result.verdict == "ELF_FAIL"
        assert result.stage1_manifest_arm64 is True
        assert result.stage2_elf_aarch64 is False
    finally:
        tar_path.unlink(missing_ok=True)


@patch("scripts.nim_pull_to_nas.subprocess.run")
def test_verify_nas_tar_manifest_fail_x86_config(mock_run):
    """Config arch is x86-64 → MANIFEST_FAIL, no ELF check needed."""
    tar_path = _make_nas_image_tar(arch="amd64")
    try:
        result = verify_nas_tar(tar_path)
        assert result.verdict == "MANIFEST_FAIL"
        assert result.stage1_manifest_arm64 is False
        mock_run.assert_not_called()
    finally:
        tar_path.unlink(missing_ok=True)


def test_verify_nas_tar_missing_file():
    result = verify_nas_tar(Path("/nonexistent/image.tar"))
    assert result.verdict == "ERROR"
