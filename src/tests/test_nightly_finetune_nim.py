"""Integration tests for NIM GPU lifecycle management in nightly_finetune.

Mocks kubectl and nvidia-smi; verifies that _wait_for_gpu_released blocks
correctly for each GPU type and raises on timeout.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nightly_finetune as ft


# ---------------------------------------------------------------------------
# _nim_any_pod_exists
# ---------------------------------------------------------------------------
class TestNimAnyPodExists:
    def _run(self, stdout: str) -> bool:
        with patch("nightly_finetune.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=stdout)
            return ft._nim_any_pod_exists()

    def test_running_pod(self):
        assert self._run("nim-sovereign-abc   1/1   Running   0   5h\n") is True

    def test_terminating_pod(self):
        # Terminating state must still block Phase 1
        assert self._run("nim-sovereign-abc   0/1   Terminating   0   5h\n") is True

    def test_no_pods(self):
        assert self._run("") is False

    def test_whitespace_only(self):
        assert self._run("   \n  ") is False


# ---------------------------------------------------------------------------
# _gpu_free_mib
# ---------------------------------------------------------------------------
class TestGpuFreeMib:
    def test_reports_numeric_value(self):
        with patch("nightly_finetune.subprocess.check_output", return_value="45000\n"):
            assert ft._gpu_free_mib() == 45000

    def test_unified_memory_na(self):
        with patch("nightly_finetune.subprocess.check_output", return_value="[N/A]\n"):
            assert ft._gpu_free_mib() is None

    def test_empty_output(self):
        with patch("nightly_finetune.subprocess.check_output", return_value=""):
            assert ft._gpu_free_mib() is None

    def test_subprocess_error_returns_none(self):
        with patch("nightly_finetune.subprocess.check_output", side_effect=Exception("no gpu")):
            assert ft._gpu_free_mib() is None

    def test_multiline_takes_first(self):
        with patch("nightly_finetune.subprocess.check_output", return_value="30000\n20000\n"):
            assert ft._gpu_free_mib() == 30000


# ---------------------------------------------------------------------------
# _wait_for_gpu_released
# ---------------------------------------------------------------------------
class TestWaitForGpuReleased:
    def test_unified_memory_sleeps_dwell(self, monkeypatch):
        """GB10 path: pod gone + nvidia-smi N/A → sleep exactly dwell seconds."""
        monkeypatch.setattr(ft, "NIM_TERMINATION_DWELL_SECONDS", 7)
        sleep_calls: list[float] = []

        with (
            patch("nightly_finetune._nim_any_pod_exists", return_value=False),
            patch("nightly_finetune._gpu_free_mib", return_value=None),
            patch("nightly_finetune.time.sleep", side_effect=lambda s: sleep_calls.append(s)),
        ):
            ft._wait_for_gpu_released()

        assert 7 in sleep_calls, f"expected dwell sleep of 7s, got {sleep_calls}"

    def test_discrete_gpu_returns_on_memory_jump(self, monkeypatch):
        """Discrete GPU: poll free memory → large jump → return without error."""
        monkeypatch.setattr(ft, "NIM_TERMINATION_DWELL_SECONDS", 30)
        free_values = iter([5000, 5100, 66000])  # 61 GiB jump on third poll

        with (
            patch("nightly_finetune._nim_any_pod_exists", return_value=False),
            patch("nightly_finetune._gpu_free_mib", side_effect=lambda: next(free_values)),
            patch("nightly_finetune.time.sleep"),
        ):
            ft._wait_for_gpu_released()  # must not raise

    def test_discrete_gpu_na_mid_poll_treated_as_released(self, monkeypatch):
        """If nvidia-smi switches to N/A mid-poll, treat as context released."""
        monkeypatch.setattr(ft, "NIM_TERMINATION_DWELL_SECONDS", 30)
        free_values = iter([5000, None])  # second call returns N/A

        with (
            patch("nightly_finetune._nim_any_pod_exists", return_value=False),
            patch("nightly_finetune._gpu_free_mib", side_effect=lambda: next(free_values)),
            patch("nightly_finetune.time.sleep"),
        ):
            ft._wait_for_gpu_released()  # must not raise

    def test_pod_never_gone_raises_runtime_error(self, monkeypatch):
        """If pod never disappears within 120s ceiling, raise RuntimeError."""
        monkeypatch.setattr(ft, "_NIM_GPU_RELEASE_TIMEOUT", 0.05)

        with (
            patch("nightly_finetune._nim_any_pod_exists", return_value=True),
            patch("nightly_finetune.time.sleep"),  # no-op sleep so loop spins fast
        ):
            with pytest.raises(RuntimeError, match="still present"):
                ft._wait_for_gpu_released()

    def test_terminating_pod_blocks_phase1_then_proceeds(self, monkeypatch):
        """Pod in Terminating state should extend Phase 1 until fully gone."""
        monkeypatch.setattr(ft, "NIM_TERMINATION_DWELL_SECONDS", 1)
        # Two calls return True (pod Terminating), third returns False (gone)
        exists_seq = iter([True, True, False])
        sleep_calls: list[float] = []

        with (
            patch("nightly_finetune._nim_any_pod_exists", side_effect=lambda: next(exists_seq)),
            patch("nightly_finetune._gpu_free_mib", return_value=None),
            patch("nightly_finetune.time.sleep", side_effect=lambda s: sleep_calls.append(s)),
        ):
            ft._wait_for_gpu_released()

        phase1_sleeps = [s for s in sleep_calls if s == 3]
        assert len(phase1_sleeps) >= 2, "expected at least 2 phase-1 poll sleeps"

    def test_stop_vllm_calls_wait_for_gpu_released(self, monkeypatch):
        """_stop_vllm must call _wait_for_gpu_released after pod leaves Running."""
        wait_called = []

        def fake_wait():
            wait_called.append(True)

        with (
            patch("nightly_finetune._nim_pod_running", side_effect=[True, False]),
            patch("nightly_finetune._wait_for_gpu_released", side_effect=fake_wait),
            patch("nightly_finetune.subprocess.run"),
            patch("nightly_finetune.time.sleep"),
        ):
            result = ft._stop_vllm()

        assert result is True
        assert wait_called, "_wait_for_gpu_released was not called by _stop_vllm"
