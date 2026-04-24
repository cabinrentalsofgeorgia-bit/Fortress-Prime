"""
Tests for the QLoRA quantization + device_map plumbing in
src/nightly_finetune.py. The 2026-04-24 nightly failed on bnb 4-bit's
"Some modules are dispatched on the CPU or the disk" ValueError; the fix
is to set `llm_int8_enable_fp32_cpu_offload=True` on the bnb config and
pass an explicit `max_memory` dict to `from_pretrained` so the loader has
a valid CPU-overflow plan even when GPU RAM is tight.

These tests exercise the pure Python helpers the trainer now calls; no
GPU is required. An optional GPU smoke test is gated on
LOCAL_GPU_AVAILABLE=1 and instantiates the config + memory map but does
NOT load weights.
"""
from __future__ import annotations

import importlib
import logging
import os
import types

import pytest

nf = importlib.import_module("nightly_finetune")


# ── 1. BnB config always carries the CPU-offload flag ──────────────────

def test_bnb_config_has_cpu_offload_flag() -> None:
    """llm_int8_enable_fp32_cpu_offload must be True to survive tight GPU
    plans; bnb 4-bit refuses implicit CPU dispatch without it."""
    sentinel_dtype = object()  # stand-in for torch.bfloat16
    kwargs = nf.build_quantization_kwargs(sentinel_dtype)

    assert kwargs["llm_int8_enable_fp32_cpu_offload"] is True
    assert kwargs["load_in_4bit"] is True
    assert kwargs["bnb_4bit_quant_type"] == "nf4"
    assert kwargs["bnb_4bit_use_double_quant"] is True
    assert kwargs["bnb_4bit_compute_dtype"] is sentinel_dtype


# ── 2. max_memory is built correctly for each GPU state ────────────────

def test_device_map_respects_max_memory_gpu_present() -> None:
    """With a real free_gpu_bytes value, GPU slot reflects (free - headroom)
    in GiB and CPU overflow bucket is present."""
    ten_gib = 10 * (1024 ** 3)
    m = nf.build_max_memory_map(free_gpu_bytes=ten_gib, cpu_ram_gb=64, gpu_headroom_gb=2)
    assert m == {"0": "8GiB", "cpu": "64GiB"}


def test_device_map_respects_max_memory_no_gpu() -> None:
    """When no GPU is available, map is CPU-only so the loader can still
    materialize the model rather than raising."""
    assert nf.build_max_memory_map(free_gpu_bytes=None, cpu_ram_gb=48) == {"cpu": "48GiB"}
    assert nf.build_max_memory_map(free_gpu_bytes=0, cpu_ram_gb=48) == {"cpu": "48GiB"}
    assert nf.build_max_memory_map(free_gpu_bytes=-1, cpu_ram_gb=48) == {"cpu": "48GiB"}


def test_device_map_headroom_applied() -> None:
    """Headroom must be deducted from the advertised GPU budget."""
    twenty_gib = 20 * (1024 ** 3)
    m_strict = nf.build_max_memory_map(free_gpu_bytes=twenty_gib, cpu_ram_gb=64, gpu_headroom_gb=4)
    m_loose = nf.build_max_memory_map(free_gpu_bytes=twenty_gib, cpu_ram_gb=64, gpu_headroom_gb=2)
    assert m_strict["0"] == "16GiB"
    assert m_loose["0"] == "18GiB"


def test_device_map_headroom_never_negative() -> None:
    """Tiny free GPU (smaller than headroom) → 0 GPU budget, CPU overflow
    still set. Prevents a negative int from leaking into max_memory."""
    one_gib = 1 * (1024 ** 3)
    m = nf.build_max_memory_map(free_gpu_bytes=one_gib, cpu_ram_gb=64, gpu_headroom_gb=2)
    assert m == {"0": "0GiB", "cpu": "64GiB"}


# ── 3. Preflight reads torch.cuda.mem_get_info and logs ────────────────

class _FakeCuda:
    def __init__(self, available: bool = True, free: int = 42 * (1024 ** 3), total: int = 120 * (1024 ** 3)):
        self._available = available
        self._free = free
        self._total = total

    def is_available(self) -> bool:
        return self._available

    def mem_get_info(self) -> tuple[int, int]:
        return (self._free, self._total)


def _fake_torch(cuda: _FakeCuda) -> types.SimpleNamespace:
    return types.SimpleNamespace(cuda=cuda)


def test_preflight_logs_gpu_state(caplog: pytest.LogCaptureFixture) -> None:
    """Happy path: GPU present; returns populated state dict, emits a log
    line with free + total GiB."""
    fake = _fake_torch(_FakeCuda(available=True, free=40 * (1024 ** 3), total=120 * (1024 ** 3)))
    with caplog.at_level(logging.INFO, logger="finetune"):
        state = nf.log_gpu_preflight(fake)

    assert state["has_gpu"] is True
    assert state["free_bytes"] == 40 * (1024 ** 3)
    assert state["total_bytes"] == 120 * (1024 ** 3)
    assert any("gpu_preflight" in r.getMessage() for r in caplog.records)


def test_preflight_no_gpu_falls_back_cleanly(caplog: pytest.LogCaptureFixture) -> None:
    """No CUDA → state.has_gpu False, free/total None, warning logged. Caller
    will build a CPU-only max_memory from this."""
    fake = _fake_torch(_FakeCuda(available=False))
    with caplog.at_level(logging.WARNING, logger="finetune"):
        state = nf.log_gpu_preflight(fake)

    assert state == {"has_gpu": False, "free_bytes": None, "total_bytes": None}
    assert any("no_cuda_device" in r.getMessage() for r in caplog.records)


def test_preflight_swallows_torch_errors() -> None:
    """If mem_get_info or is_available raises, preflight returns the no-GPU
    state rather than propagating — the trainer must never die in preflight."""
    class _Exploder:
        def is_available(self) -> bool:
            raise RuntimeError("cuda not initialized")

        def mem_get_info(self) -> tuple[int, int]:  # pragma: no cover — not reached
            raise AssertionError("should not be called")

    fake = _fake_torch(_Exploder())  # type: ignore[arg-type]
    state = nf.log_gpu_preflight(fake)
    assert state == {"has_gpu": False, "free_bytes": None, "total_bytes": None}


# ── 4. Explicit kwargs override the module-level defaults ──────────────

def test_helper_kwargs_override_module_defaults() -> None:
    """Callers can override cpu_ram_gb / gpu_headroom_gb without touching
    env vars; module defaults are used only when kwargs are omitted. This
    guards against future refactors that drop the parameters in favor of
    reading env vars mid-function (which would defeat testability)."""
    twenty_gib = 20 * (1024 ** 3)
    m = nf.build_max_memory_map(free_gpu_bytes=twenty_gib, cpu_ram_gb=128, gpu_headroom_gb=8)
    assert m == {"0": "12GiB", "cpu": "128GiB"}


# ── 5. Optional GPU smoke (off in CI) ──────────────────────────────────

@pytest.mark.skipif(
    os.getenv("LOCAL_GPU_AVAILABLE") != "1",
    reason="GPU smoke test — set LOCAL_GPU_AVAILABLE=1 to run on a host with CUDA",
)
def test_local_gpu_smoke_builds_config_without_loading_weights() -> None:
    """With a real GPU, the config + max_memory map should be constructible
    without touching the model. This catches torch/bnb/transformers import
    breakage early, in under a second, without burning the 6h nightly."""
    import torch
    from transformers import BitsAndBytesConfig

    state = nf.log_gpu_preflight(torch)
    assert state["has_gpu"] is True
    assert state["free_bytes"] is not None and state["free_bytes"] > 0

    kwargs = nf.build_quantization_kwargs(torch.bfloat16)
    bnb = BitsAndBytesConfig(**kwargs)
    assert bnb.load_in_4bit is True
    assert getattr(bnb, "llm_int8_enable_fp32_cpu_offload", None) is True

    mem = nf.build_max_memory_map(free_gpu_bytes=state["free_bytes"])
    assert "0" in mem and "cpu" in mem
