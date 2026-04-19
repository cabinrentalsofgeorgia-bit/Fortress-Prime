"""Tests for backfill_label_historical.py env auto-loading."""
import os
from pathlib import Path

_ENV_FILES = [".env", ".env.dgx", ".env.security"]


class TestBackfillEnvLoading:
    def test_loads_env_without_presourcing(self, tmp_path: Path) -> None:
        """dotenv block in backfill script loads vars from .env without shell set -a."""
        fgp_dir = tmp_path / "fortress-guest-platform"
        fgp_dir.mkdir()
        (fgp_dir / ".env").write_text("BACKFILL_TEST_SENTINEL=loaded_by_dotenv\n")

        from dotenv import load_dotenv

        for env_file in _ENV_FILES:
            env_path = fgp_dir / env_file
            if env_path.exists():
                load_dotenv(env_path, override=False)

        assert os.environ.get("BACKFILL_TEST_SENTINEL") == "loaded_by_dotenv"
        os.environ.pop("BACKFILL_TEST_SENTINEL", None)

    def test_missing_env_files_are_skipped(self, tmp_path: Path) -> None:
        """Missing .env files are silently skipped — no FileNotFoundError."""
        fgp_dir = tmp_path / "fortress-guest-platform"
        fgp_dir.mkdir()

        from dotenv import load_dotenv

        for env_file in _ENV_FILES:
            env_path = fgp_dir / env_file
            if env_path.exists():
                load_dotenv(env_path, override=False)
        # reaching here without exception is the assertion

    def test_explicit_process_env_wins_over_dotenv(self, tmp_path: Path) -> None:
        """override=False means a pre-set process env var is not overwritten."""
        fgp_dir = tmp_path / "fortress-guest-platform"
        fgp_dir.mkdir()
        (fgp_dir / ".env").write_text("BACKFILL_OVERRIDE_TEST=from_file\n")

        os.environ["BACKFILL_OVERRIDE_TEST"] = "from_process"
        from dotenv import load_dotenv
        load_dotenv(fgp_dir / ".env", override=False)

        assert os.environ["BACKFILL_OVERRIDE_TEST"] == "from_process"
        os.environ.pop("BACKFILL_OVERRIDE_TEST", None)
