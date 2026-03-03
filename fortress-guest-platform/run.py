"""Fortress Guest Platform — Launch script with .pyc fallback."""
import sys
import os
import importlib
import importlib.abc
import importlib.machinery
import importlib.util

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8100,
        log_level="info",
    )
