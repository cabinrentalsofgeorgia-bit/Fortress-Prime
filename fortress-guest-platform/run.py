"""Fortress Guest Platform — Launch script with .pyc fallback."""
import sys
import os
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
from pathlib import Path

class PycFallbackFinder(importlib.abc.MetaPathFinder):
    """If a .py file is missing but a .pyc exists, load from .pyc."""
    def find_spec(self, fullname, path, target=None):
        parts = fullname.split(".")
        if path is None:
            search_dirs = sys.path
        else:
            search_dirs = list(path)
        
        for search_dir in search_dirs:
            pkg_init = os.path.join(search_dir, parts[-1], "__init__.py")
            if os.path.exists(pkg_init):
                return None

            py_file = os.path.join(search_dir, parts[-1] + ".py")
            if os.path.exists(py_file):
                return None

            pyc_file = os.path.join(search_dir, "__pycache__", f"{parts[-1]}.cpython-312.pyc")
            if os.path.exists(pyc_file):
                ghost_py = os.path.join(search_dir, parts[-1] + ".py")
                loader = importlib.machinery.SourcelessFileLoader(fullname, pyc_file)
                spec = importlib.util.spec_from_loader(
                    fullname,
                    loader,
                    origin=ghost_py,
                    is_package=False,
                )
                if spec:
                    spec.has_location = True
                return spec
        return None

sys.meta_path.insert(0, PycFallbackFinder())

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
sys.path.insert(0, str(APP_ROOT))


def _load_env_file(path: Path) -> None:
    """
    Minimal .env parser for startup-time env injection.
    Uses setdefault so explicit process env still wins.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


# Ensure auth/runtime env is available regardless of launch method.
_load_env_file(APP_ROOT / ".env")
_load_env_file(PROJECT_ROOT / ".env.security")

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
