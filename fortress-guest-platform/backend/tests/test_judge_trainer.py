"""Tests for Phase 4e.3 judge trainer and base model locator."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# base_model_locator
# ---------------------------------------------------------------------------

class TestBaseModelLocator:
    def _loc(self):
        import sys
        repo_root = str(Path(__file__).parents[3])  # fortress-guest-platform/../.. = Fortress-Prime
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from src.judge.base_model_locator import find_base_model
        return find_base_model

    def test_returns_none_when_not_found_anywhere(self):
        find = self._loc()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            # Patch Path.exists to always False
            with patch("pathlib.Path.exists", return_value=False):
                result = find("nonexistent_model:99b")
        assert result is None

    def test_logs_ollama_hint_when_model_in_ollama(self):
        find = self._loc()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="FROM qwen2.5-7b-Q4_K_M.gguf\n")
            with patch("pathlib.Path.exists", return_value=False):
                result = find("qwen2.5:7b")
        # Returns None (Ollama GGUF ≠ HF format), but doesn't crash
        assert result is None

    def test_finds_model_in_nas_models_dir(self, tmp_path):
        find = self._loc()
        model_dir = tmp_path / "qwen2.5-7b"
        model_dir.mkdir()
        (model_dir / "config.json").write_text('{"model_type": "qwen2"}')

        with patch("src.judge.base_model_locator._NAS_MODELS", tmp_path):
            with patch("subprocess.run", return_value=MagicMock(returncode=1)):
                result = find("qwen2.5:7b")
        assert result is not None
        assert result == model_dir

    def test_finds_model_in_hf_cache(self, tmp_path):
        find = self._loc()
        # Create mock HF cache structure
        cache = tmp_path / "hub"
        model_dir = cache / "models--Qwen--Qwen2.5-7B-Instruct"
        snap = model_dir / "snapshots" / "abc123"
        snap.mkdir(parents=True)
        (snap / "config.json").write_text('{"model_type": "qwen2"}')

        with patch("src.judge.base_model_locator._HF_CACHE_AI_BULK", cache), \
             patch("src.judge.base_model_locator._NAS_MODELS", tmp_path / "nonexistent"), \
             patch("subprocess.run", return_value=MagicMock(returncode=1)):
            result = find("qwen2.5:7b")
        assert result == snap


# ---------------------------------------------------------------------------
# train_judge — insufficient data path
# ---------------------------------------------------------------------------

class TestTrainJudge:
    def _train(self):
        import sys
        repo_root = str(Path(__file__).parents[3])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from src.judge.train_judge import train_judge
        return train_judge

    def test_insufficient_data_exits_cleanly(self, tmp_path):
        train = self._train()
        # Write 5 examples (below MIN_EXAMPLES=50)
        data_file = tmp_path / "data.jsonl"
        for i in range(5):
            data_file.write_text(
                "\n".join(json.dumps({"messages": [
                    {"role": "system", "content": "judge"},
                    {"role": "user", "content": f"prompt {i}"},
                    {"role": "assistant", "content": '{"decision":"confident","reasoning":"ok"}'},
                ]}) for i in range(5))
            )
        output = tmp_path / "output"
        rc = train("test_judge", "qwen2.5:7b", data_file, output, dry_run=False)
        assert rc == 1
        assert (output / "training.error").exists()
        error_text = (output / "training.error").read_text()
        assert "Insufficient" in error_text
        assert "5 examples" in error_text

    def test_missing_base_model_writes_error(self, tmp_path):
        train = self._train()
        # Write enough data
        data_file = tmp_path / "data.jsonl"
        lines = [json.dumps({"messages": [
            {"role": "system", "content": "judge"},
            {"role": "user", "content": f"prompt {i}"},
            {"role": "assistant", "content": '{"decision":"confident","reasoning":"ok"}'},
        ]}) for i in range(60)]
        data_file.write_text("\n".join(lines))
        output = tmp_path / "output"

        with patch("src.judge.base_model_locator.find_base_model", return_value=None):
            rc = train("test_judge", "qwen2.5:7b", data_file, output, dry_run=False)
        assert rc == 1
        assert (output / "training.error").exists()
        assert "not found" in (output / "training.error").read_text().lower()

    def test_dry_run_succeeds_with_enough_data_and_model(self, tmp_path):
        train = self._train()
        data_file = tmp_path / "data.jsonl"
        lines = [json.dumps({"messages": [
            {"role": "system", "content": "judge"},
            {"role": "user", "content": f"p{i}"},
            {"role": "assistant", "content": '{"decision":"confident","reasoning":"ok"}'},
        ]}) for i in range(60)]
        data_file.write_text("\n".join(lines))
        output = tmp_path / "output"

        with patch("src.judge.base_model_locator.find_base_model",
                   return_value=tmp_path / "fake_model"):
            rc = train("test_judge", "qwen2.5:7b", data_file, output, dry_run=True)
        assert rc == 0
        # Dry-run should not create output dir or .error
        assert not (output / "training.error").exists()

    def test_mock_training_loop(self, tmp_path):
        """Verify training pipeline structure without GPU."""
        train = self._train()
        data_file = tmp_path / "data.jsonl"
        lines = [json.dumps({"messages": [
            {"role": "system", "content": "judge"},
            {"role": "user", "content": f"p{i}"},
            {"role": "assistant", "content": '{"decision":"escalate","reasoning":"bad"}'},
        ]}) for i in range(60)]
        data_file.write_text("\n".join(lines))
        output = tmp_path / "output"

        mock_model = MagicMock()
        mock_model.print_trainable_parameters = MagicMock()
        mock_trainer = MagicMock()
        mock_trainer.train.return_value = MagicMock(metrics={})
        mock_trainer.state.log_history = [{"step": 1, "loss": 0.5}]
        mock_trainer.save_model = MagicMock()

        with patch("src.judge.base_model_locator.find_base_model",
                   return_value=tmp_path / "fake_model"), \
             patch("torch.cuda.is_available", return_value=False), \
             patch("transformers.AutoTokenizer.from_pretrained", return_value=MagicMock(
                 pad_token=None, eos_token="<eos>",
                 apply_chat_template=lambda m, **k: " ".join(str(x) for x in m))), \
             patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model), \
             patch("transformers.BitsAndBytesConfig", return_value=MagicMock()), \
             patch("peft.prepare_model_for_kbit_training", return_value=mock_model), \
             patch("peft.get_peft_model", return_value=mock_model), \
             patch("peft.LoraConfig", return_value=MagicMock()), \
             patch("trl.SFTTrainer", return_value=mock_trainer), \
             patch("trl.SFTConfig", return_value=MagicMock()):
            rc = train("test_judge", "qwen2.5:7b", data_file, output, dry_run=False)

        assert rc == 0
        assert (output / "training_manifest.json").exists()
        manifest = json.loads((output / "training_manifest.json").read_text())
        assert manifest["judge_name"] == "test_judge"
        assert manifest["dataset_size"] == 60
        assert manifest["lora_config"]["r"] == 16
        assert manifest["lora_config"]["lora_alpha"] == 32
        assert manifest["serving_format"] == "ollama-lora"
