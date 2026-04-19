"""
Tests for Phase 4 retarget: Qwen2.5-7B target, STOP_NIM_FOR_TRAINING flag,
adapter path naming, and base model locator integration.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Adapter path naming
# ---------------------------------------------------------------------------

class TestAdapterPathNaming:
    def test_adapter_dir_uses_qwen_slug(self):
        """main() should set adapter_out to qwen2.5-7b-crog-vrs-<date>."""
        import nightly_finetune as ft
        from datetime import date

        today = date.today().isoformat()
        expected_name = f"qwen2.5-7b-crog-vrs-{today}"

        with (
            patch.object(ft, "BASE_MODEL_DIR", Path("/fake/qwen")),
            patch.object(ft, "run_export"),
            patch.object(ft, "load_training_data", return_value=[]),
            patch("nightly_finetune.subprocess.run"),
        ):
            ft.main(dry_run=True, skip_export=True)

        adapter_out = ft.ADAPTER_DIR / expected_name
        assert adapter_out.name == expected_name

    def test_adapter_slug_does_not_contain_llama(self):
        """Regression: old llama-3.3-70b-crog slug must not appear."""
        import nightly_finetune as ft
        from datetime import date
        today = date.today().isoformat()
        slug = f"qwen2.5-7b-crog-vrs-{today}"
        assert "llama" not in slug.lower()
        assert "qwen2.5-7b-crog-vrs" in slug


# ---------------------------------------------------------------------------
# STOP_NIM_FOR_TRAINING = false (default for 7B)
# ---------------------------------------------------------------------------

class TestNimStopSkipped:
    def test_stop_vllm_not_called_when_stop_nim_false(self, monkeypatch):
        import nightly_finetune as ft
        monkeypatch.setattr(ft, "STOP_NIM_FOR_TRAINING", False)
        monkeypatch.setattr(ft, "BASE_MODEL_DIR", Path("/fake/qwen"))

        stop_calls = []

        def fake_stop():
            stop_calls.append(True)
            return True

        with (
            patch.object(ft, "_stop_vllm", side_effect=fake_stop),
            patch.object(ft, "run_export"),
            patch.object(ft, "load_training_data", return_value=[]),
        ):
            ft.main(dry_run=True, skip_export=True)

        assert stop_calls == [], "_stop_vllm must not be called when STOP_NIM_FOR_TRAINING=false"

    def test_stop_vllm_called_when_stop_nim_true(self):
        """STOP_NIM_FOR_TRAINING=true must invoke _stop_vllm before training."""
        import nightly_finetune as ft

        original_stop = ft.STOP_NIM_FOR_TRAINING
        original_base = ft.BASE_MODEL_DIR
        ft.STOP_NIM_FOR_TRAINING = True
        ft.BASE_MODEL_DIR = Path("/fake/qwen")

        # Provide enough records to pass both hard floor (5) and MIN_EXAMPLES (20)
        fake_records = [{"messages": [{"role": "user", "content": "x"}]} for _ in range(25)]
        stop_calls = []

        try:
            with (
                patch.object(ft, "_stop_vllm", side_effect=lambda: stop_calls.append(True) or False),
                patch.object(ft, "_ensure_training_deps"),
                patch.object(ft, "run_qlora_training"),
                patch.object(ft, "_run_eval_pipeline"),
                patch.object(ft, "run_export"),
                patch.object(ft, "load_training_data", return_value=fake_records),
            ):
                ft.main(dry_run=False, skip_export=True)
        finally:
            ft.STOP_NIM_FOR_TRAINING = original_stop
            ft.BASE_MODEL_DIR = original_base

        assert stop_calls == [True], "_stop_vllm must be called when STOP_NIM_FOR_TRAINING=true"

    def test_stop_nim_default_is_false(self):
        """Default env must produce STOP_NIM_FOR_TRAINING=False."""
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NIGHTLY_FINETUNE_STOP_NIM", None)
            if "nightly_finetune" in sys.modules:
                del sys.modules["nightly_finetune"]
            import nightly_finetune as ft2
            assert ft2.STOP_NIM_FOR_TRAINING is False


# ---------------------------------------------------------------------------
# Base model locator
# ---------------------------------------------------------------------------

class TestBaseModelLocator:
    def test_env_override_bypasses_locator(self, monkeypatch):
        """FINETUNE_BASE_MODEL_DIR env var must be used directly."""
        import os
        override = "/tmp/test-qwen-model"
        with patch.dict(os.environ, {"FINETUNE_BASE_MODEL_DIR": override}):
            if "nightly_finetune" in sys.modules:
                del sys.modules["nightly_finetune"]
            with patch("judge.base_model_locator.find_base_model") as mock_locator:
                import nightly_finetune as ft
                mock_locator.assert_not_called()
                assert str(ft.BASE_MODEL_DIR) == override

    def test_none_base_model_causes_main_to_return_1(self):
        """main() must return exit code 1 if BASE_MODEL_DIR is None."""
        import nightly_finetune as ft
        original = ft.BASE_MODEL_DIR
        ft.BASE_MODEL_DIR = None

        try:
            with (
                patch.object(ft, "run_export"),
                patch.object(ft, "load_training_data", return_value=[{"messages": []}] * 20),
            ):
                result = ft.main(dry_run=False, skip_export=True)
            assert result == 1, "Expected exit code 1 when base model is None"
        finally:
            ft.BASE_MODEL_DIR = original

    def test_locator_called_when_no_env_override(self):
        """When env var absent, find_base_model('qwen2.5:7b') must be called."""
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FINETUNE_BASE_MODEL_DIR", None)
            if "nightly_finetune" in sys.modules:
                del sys.modules["nightly_finetune"]
            fake_path = Path("/mnt/fortress_nas/models/Qwen2.5-7B-Instruct")
            with patch("judge.base_model_locator.find_base_model", return_value=fake_path) as mock_loc:
                import nightly_finetune as ft
                mock_loc.assert_called_once_with("qwen2.5:7b")
                assert ft.BASE_MODEL_DIR == fake_path
