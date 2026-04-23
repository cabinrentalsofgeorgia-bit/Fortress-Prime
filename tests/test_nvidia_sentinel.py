"""
Unit tests for tools/nvidia_sentinel.py — Phase 4 heuristic and Phase 1 auth.

All HTTP / subprocess calls are mocked.  No live NGC calls in CI.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.nvidia_sentinel import (
    _OCI_EMPTY_BLOB,
    _shared_substantive_layer_ratio,
    _parse_manifest_arm64,
    get_ngc_token,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _layer(digest: str, size: int) -> dict:
    return {"digest": digest, "size": size}


WHITEOUT = _layer(_OCI_EMPTY_BLOB, 32)

# Fake substantive layer digests
ARM_A = "sha256:" + "a" * 64
ARM_B = "sha256:" + "b" * 64
ARM_C = "sha256:" + "c" * 64
AMD_A = ARM_A          # shared with arm
AMD_D = "sha256:" + "d" * 64
AMD_E = "sha256:" + "e" * 64


# ---------------------------------------------------------------------------
# _shared_substantive_layer_ratio
# ---------------------------------------------------------------------------

def test_ratio_no_shared_layers():
    arm64 = [_layer(ARM_A, 1000), _layer(ARM_B, 2000)]
    amd64 = [_layer(AMD_D, 1000), _layer(AMD_E, 2000)]
    assert _shared_substantive_layer_ratio(arm64, amd64) == 0.0


def test_ratio_all_shared_layers():
    arm64 = [_layer(ARM_A, 1000), _layer(ARM_B, 2000)]
    amd64 = [_layer(ARM_A, 1000), _layer(ARM_B, 2000)]
    assert _shared_substantive_layer_ratio(arm64, amd64) == 1.0


def test_ratio_exactly_50_percent():
    arm64 = [_layer(ARM_A, 1000), _layer(ARM_B, 2000)]
    amd64 = [_layer(ARM_A, 1000), _layer(AMD_D, 2000)]
    ratio = _shared_substantive_layer_ratio(arm64, amd64)
    assert ratio == 0.5


def test_ratio_60_percent():
    arm64 = [_layer(ARM_A, 1000), _layer(ARM_B, 2000), _layer(ARM_C, 3000)]
    amd64 = [_layer(ARM_A, 1000), _layer(ARM_B, 2000), _layer(AMD_D, 3000)]
    ratio = _shared_substantive_layer_ratio(arm64, amd64)
    assert abs(ratio - 2 / 3) < 1e-9


def test_ratio_whiteout_layers_excluded():
    # Only shared layers are zero-size whiteout blobs — ratio must be 0.0
    arm64 = [WHITEOUT, WHITEOUT, _layer(ARM_A, 1000)]
    amd64 = [WHITEOUT, WHITEOUT, _layer(AMD_D, 1000)]
    assert _shared_substantive_layer_ratio(arm64, amd64) == 0.0


def test_ratio_empty_layer_list_returns_zero():
    assert _shared_substantive_layer_ratio([], []) == 0.0
    assert _shared_substantive_layer_ratio([_layer(ARM_A, 1000)], []) == 0.0


# ---------------------------------------------------------------------------
# _parse_manifest_arm64 — verdict mapping
# ---------------------------------------------------------------------------

def _mock_index(arm64_digest: str, amd64_digest: str) -> dict:
    return {
        "manifests": [
            {"platform": {"architecture": "arm64", "os": "linux"}, "digest": arm64_digest, "size": 10000},
            {"platform": {"architecture": "amd64", "os": "linux"}, "digest": amd64_digest, "size": 10000},
        ]
    }


def _mock_sub_manifest(layers: list[dict]) -> dict:
    return {"schemaVersion": 2, "layers": layers}


def _make_inspect_side_effect(index_json, arm64_layers, amd64_layers):
    """
    Returns a side_effect function for _manifest_inspect_via_docker that:
    - returns index_json for the base image ref
    - returns the arm64 sub-manifest for ...@sha256:arm64...
    - returns the amd64 sub-manifest for ...@sha256:amd64...
    """
    call_count = {"n": 0}
    responses = [
        index_json,
        _mock_sub_manifest(arm64_layers),
        _mock_sub_manifest(amd64_layers),
    ]

    def side_effect(_image_ref: str):
        n = call_count["n"]
        call_count["n"] += 1
        return responses[n] if n < len(responses) else None

    return side_effect


@patch("tools.nvidia_sentinel._manifest_inspect_via_docker")
def test_parse_manifest_arm64_ok_no_shared(mock_inspect):
    """Genuine arm64 image — no shared substantive layers → ARM64_OK."""
    index = _mock_index("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    mock_inspect.side_effect = _make_inspect_side_effect(
        index,
        arm64_layers=[_layer(ARM_A, 5000)],
        amd64_layers=[_layer(AMD_D, 5000)],
    )
    stage1, _, _, _, _, ratio = _parse_manifest_arm64("nvcr.io/nim/nvidia/model:latest")
    assert stage1 is True
    assert ratio == 0.0
    # Caller maps ratio <= 0.5 → ARM64_OK


@patch("tools.nvidia_sentinel._manifest_inspect_via_docker")
def test_parse_manifest_mismatch_all_shared(mock_inspect):
    """Packaging defect — all substantive layers shared → ratio 1.0 → ARM64_MANIFEST_MISMATCH."""
    shared_layer = _layer(ARM_A, 5000)
    index = _mock_index("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    mock_inspect.side_effect = _make_inspect_side_effect(
        index,
        arm64_layers=[shared_layer],
        amd64_layers=[shared_layer],
    )
    stage1, _, _, _, _, ratio = _parse_manifest_arm64("nvcr.io/nim/nvidia/model:latest")
    assert stage1 is True
    assert ratio == 1.0
    assert ratio > 0.5  # caller maps this → ARM64_MANIFEST_MISMATCH


@patch("tools.nvidia_sentinel._manifest_inspect_via_docker")
def test_parse_manifest_50_percent_is_not_mismatch(mock_inspect):
    """Exactly 50% shared — strict > 0.5 threshold means NOT a mismatch."""
    index = _mock_index("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    mock_inspect.side_effect = _make_inspect_side_effect(
        index,
        arm64_layers=[_layer(ARM_A, 5000), _layer(ARM_B, 5000)],
        amd64_layers=[_layer(ARM_A, 5000), _layer(AMD_D, 5000)],
    )
    _, _, _, _, _, ratio = _parse_manifest_arm64("nvcr.io/nim/nvidia/model:latest")
    assert ratio == 0.5
    assert not (ratio > 0.5)  # strict threshold — 50% is ARM64_OK


@patch("tools.nvidia_sentinel._manifest_inspect_via_docker")
def test_parse_manifest_60_percent_is_mismatch(mock_inspect):
    """60% shared → ARM64_MANIFEST_MISMATCH."""
    index = _mock_index("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    mock_inspect.side_effect = _make_inspect_side_effect(
        index,
        arm64_layers=[_layer(ARM_A, 5000), _layer(ARM_B, 5000), _layer(ARM_C, 5000)],
        amd64_layers=[_layer(ARM_A, 5000), _layer(ARM_B, 5000), _layer(AMD_D, 5000)],
    )
    _, _, _, _, _, ratio = _parse_manifest_arm64("nvcr.io/nim/nvidia/model:latest")
    assert ratio > 0.5


@patch("tools.nvidia_sentinel._manifest_inspect_via_docker")
def test_parse_manifest_whiteout_only_shared_is_ok(mock_inspect):
    """Only zero-size whiteout blobs shared — substantive layers all unique → ARM64_OK."""
    index = _mock_index("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    mock_inspect.side_effect = _make_inspect_side_effect(
        index,
        arm64_layers=[WHITEOUT, WHITEOUT, _layer(ARM_A, 5000)],
        amd64_layers=[WHITEOUT, WHITEOUT, _layer(AMD_D, 5000)],
    )
    _, _, _, _, _, ratio = _parse_manifest_arm64("nvcr.io/nim/nvidia/model:latest")
    assert ratio == 0.0


@patch("tools.nvidia_sentinel._manifest_inspect_via_docker")
def test_parse_manifest_no_arm64_platform(mock_inspect):
    """No arm64 entry in index → stage1=False, ratio=0.0."""
    index = {
        "manifests": [
            {"platform": {"architecture": "amd64", "os": "linux"}, "digest": "sha256:" + "b" * 64, "size": 9000},
        ]
    }
    mock_inspect.return_value = index
    stage1, _, _, _, _, ratio = _parse_manifest_arm64("nvcr.io/nim/nvidia/model:latest")
    assert stage1 is False
    assert ratio == 0.0


@patch("tools.nvidia_sentinel._manifest_inspect_via_docker")
def test_parse_manifest_access_denied(mock_inspect):
    """docker manifest inspect fails (access denied) → stage1=False."""
    mock_inspect.return_value = None
    stage1, _, _, _, _, ratio = _parse_manifest_arm64("nvcr.io/nim/nvidia/model:latest")
    assert stage1 is False
    assert ratio == 0.0


# ---------------------------------------------------------------------------
# get_ngc_token — Phase 1 auth URL (Fix 2)
# ---------------------------------------------------------------------------

@patch("tools.nvidia_sentinel.requests.get")
@patch("tools.nvidia_sentinel.NGC_API_KEY", "fake-nvapi-key")
def test_get_ngc_token_uses_proxy_auth_url(mock_get):
    """get_ngc_token() must call nvcr.io/proxy_auth, not authn.nvidia.com."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"token": "fake-bearer-token"}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    token = get_ngc_token("nim/nvidia/qwen2.5-7b-instruct")

    assert token == "fake-bearer-token"
    called_url = mock_get.call_args[0][0]
    assert "nvcr.io/proxy_auth" in called_url, f"Expected nvcr.io/proxy_auth, got: {called_url}"
    assert "authn.nvidia.com" not in called_url, "Must NOT use authn.nvidia.com"
    assert "repository%3A" in called_url or "repository:" in called_url


@patch("tools.nvidia_sentinel.requests.get")
@patch("tools.nvidia_sentinel.NGC_API_KEY", "fake-nvapi-key")
def test_get_ngc_token_extracts_token_from_proxy_auth_response(mock_get):
    """Token is extracted from proxy_auth JSON response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"token": "eyJhbGci.test.token"}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    token = get_ngc_token("nim/nvidia/model:latest")
    assert token == "eyJhbGci.test.token"


@patch("tools.nvidia_sentinel.NGC_API_KEY", "")
def test_get_ngc_token_returns_none_when_key_missing():
    """Returns None and logs warning when NGC_API_KEY is empty."""
    token = get_ngc_token("nim/nvidia/model:latest")
    assert token is None
