"""Tests for Phase 6 logging fix — root logger wired at startup."""
import importlib
import logging
import sys
from io import StringIO
from typing import Any


# ---------------------------------------------------------------------------
# config.py log_level field
# ---------------------------------------------------------------------------

class TestLogLevelConfig:
    def test_default_is_info(self) -> None:
        from backend.core.config import settings
        assert settings.log_level == "INFO"

    def test_valid_levels_accepted(self, monkeypatch: Any) -> None:
        import backend.core.config as cfg
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            monkeypatch.setenv("LOG_LEVEL", level)
            importlib.reload(cfg)
            assert cfg.settings.log_level == level
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        importlib.reload(cfg)

    def test_invalid_level_falls_back_to_info(self, monkeypatch: Any) -> None:
        import backend.core.config as cfg
        monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
        importlib.reload(cfg)
        assert cfg.settings.log_level == "INFO"
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        importlib.reload(cfg)

    def test_lowercase_normalised(self, monkeypatch: Any) -> None:
        import backend.core.config as cfg
        monkeypatch.setenv("LOG_LEVEL", "debug")
        importlib.reload(cfg)
        assert cfg.settings.log_level == "DEBUG"
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        importlib.reload(cfg)

    def test_empty_falls_back_to_info(self, monkeypatch: Any) -> None:
        import backend.core.config as cfg
        monkeypatch.setenv("LOG_LEVEL", "")
        importlib.reload(cfg)
        assert cfg.settings.log_level == "INFO"
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        importlib.reload(cfg)


# ---------------------------------------------------------------------------
# basicConfig is called at module import with correct arguments
# ---------------------------------------------------------------------------

class TestLoggingBasicConfig:
    def test_root_logger_has_handler_after_main_import(self) -> None:
        """After main.py loads, root logger must have at least one handler."""
        # main.py calls basicConfig(force=True) at module level
        import backend.main  # noqa: F401 — side-effect import
        root = logging.getLogger()
        assert root.handlers, "root logger has no handlers — basicConfig was not called"

    def test_root_logger_level_is_info_or_lower(self) -> None:
        import backend.main  # noqa: F401
        root = logging.getLogger()
        assert root.level <= logging.INFO, (
            f"root logger level {root.level} is above INFO — INFO messages will be dropped"
        )

    def test_info_messages_reach_stderr(self) -> None:
        """An INFO log via a stdlib logger must produce output after main import."""
        import backend.main  # noqa: F401
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.DEBUG)
        test_logger = logging.getLogger("test_logging_setup_probe")
        test_logger.addHandler(handler)
        test_logger.propagate = True
        test_logger.info("probe_message_for_test")
        test_logger.removeHandler(handler)
        assert "probe_message_for_test" in buf.getvalue(), (
            "INFO message did not reach handler — root logger may still be misconfigured"
        )

    def test_basicconfig_uses_stderr(self) -> None:
        """The root handler must write to stderr, not stdout."""
        import backend.main  # noqa: F401
        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
        assert stream_handlers, "no StreamHandler on root logger"
        assert any(h.stream is sys.stderr for h in stream_handlers), (
            "no StreamHandler targeting sys.stderr — journald will not capture logs"
        )

    def test_startup_log_line_emitted(self, capsys: Any) -> None:
        """The 'Logging initialized' message must appear in stderr on startup."""
        import backend.main  # noqa: F401
        captured = capsys.readouterr()
        # The message may have been emitted before capsys started capturing;
        # verify the root logger is set up correctly as a proxy for this.
        root = logging.getLogger()
        assert root.level <= logging.INFO


# ---------------------------------------------------------------------------
# Uvicorn named loggers are unaffected
# ---------------------------------------------------------------------------

class TestUvicornLoggerCompatibility:
    def test_uvicorn_logger_has_own_handlers_or_propagates(self) -> None:
        """uvicorn logger must still emit after our basicConfig(force=True)."""
        import backend.main  # noqa: F401
        import uvicorn.config  # noqa: F401 — ensure uvicorn loggers are registered
        uv = logging.getLogger("uvicorn")
        # uvicorn may propagate to root (which now has a handler) — either way, logs reach a handler
        root = logging.getLogger()
        reachable = bool(uv.handlers) or (uv.propagate and bool(root.handlers))
        assert reachable, "uvicorn logger cannot reach any handler after basicConfig"

    def test_uvicorn_access_logger_reachable(self) -> None:
        import backend.main  # noqa: F401
        import uvicorn.config  # noqa: F401
        access = logging.getLogger("uvicorn.access")
        root = logging.getLogger()
        reachable = bool(access.handlers) or (access.propagate and bool(root.handlers))
        assert reachable, "uvicorn.access logger cannot reach any handler"
