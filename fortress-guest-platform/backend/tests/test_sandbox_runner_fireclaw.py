"""Sandbox runtime dispatch — loads sandbox_runner without executing backend.services.__init__."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


def _ensure_services_pkg() -> None:
    name = "backend.services"
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = [str(_BACKEND / "services")]
        sys.modules[name] = m


def _load(mod_name: str, rel: str):
    path = _BACKEND / rel
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_ensure_services_pkg()
_load("backend.services.sandbox_types", "services/sandbox_types.py")
_load("backend.services.fireclaw_serial", "services/fireclaw_serial.py")
_fc_runner = _load("backend.services.fireclaw_runner", "services/fireclaw_runner.py")
_sandbox_runner = _load("backend.services.sandbox_runner", "services/sandbox_runner.py")
run_firecracker_interrogate = _fc_runner.run_firecracker_interrogate
get_sandbox_runtime_name = _sandbox_runner.get_sandbox_runtime_name
run_sandbox_python = _sandbox_runner.run_sandbox_python

from backend.core.config import settings


@pytest.fixture(autouse=True)
def _restore_sandbox_settings(monkeypatch: pytest.MonkeyPatch):
    keys = (
        "sandbox_runtime",
        "sandbox_firecracker_helper",
        "sandbox_kernel_image",
        "sandbox_rootfs_image",
        "sandbox_work_dir",
        "sandbox_firecracker_bin",
        "sandbox_vcpu_count",
        "sandbox_memory_mb",
        "sandbox_payload_mb",
        "sandbox_kernel_boot_args",
    )
    before = {k: getattr(settings, k, None) for k in keys}
    yield
    for k, v in before.items():
        monkeypatch.setattr(settings, k, v, raising=False)


def test_get_runtime_name_firecracker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sandbox_runtime", "firecracker")
    assert get_sandbox_runtime_name() == "firecracker"


def test_firecracker_missing_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sandbox_runtime", "firecracker")
    monkeypatch.setattr(settings, "sandbox_firecracker_helper", "")
    monkeypatch.setattr(settings, "sandbox_kernel_image", "/k")
    monkeypatch.setattr(settings, "sandbox_rootfs_image", "/r")
    r = run_sandbox_python("print(1)")
    assert r.exit_code == 127
    assert "SANDBOX_FIRECRACKER_HELPER" in r.stderr


def test_firecracker_helper_invocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = tmp_path / "mock_helper.sh"
    helper.write_text(
        "#!/bin/sh\n"
        'echo "FIRECLAW_RESULT{\\"exit_code\\":0,\\"stdout\\":\\"hi\\",\\"stderr\\":\\"\\"}"\n',
        encoding="utf-8",
    )
    helper.chmod(0o755)

    workdir = tmp_path / "fc_work"
    workdir.mkdir()

    monkeypatch.setattr(settings, "sandbox_runtime", "firecracker")
    monkeypatch.setattr(settings, "sandbox_firecracker_helper", str(helper))
    monkeypatch.setattr(settings, "sandbox_kernel_image", "/fake/vmlinux")
    monkeypatch.setattr(settings, "sandbox_rootfs_image", "/fake/rootfs.ext4")
    monkeypatch.setattr(settings, "sandbox_work_dir", str(workdir))
    monkeypatch.setattr(settings, "sandbox_firecracker_bin", "/usr/bin/false")
    monkeypatch.setattr(settings, "sandbox_vcpu_count", 1)
    monkeypatch.setattr(settings, "sandbox_memory_mb", 512)
    monkeypatch.setattr(settings, "sandbox_payload_mb", 8)
    monkeypatch.setattr(settings, "sandbox_kernel_boot_args", "")

    r = run_sandbox_python("print(1)")
    assert r.exit_code == 0
    assert r.stdout == "hi"


def test_docker_runtime_not_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sandbox_runtime", "docker")
    r = run_sandbox_python("x")
    assert "not implemented" in r.stdout.lower() or "firecracker" in r.stdout.lower()


def test_unknown_runtime_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sandbox_runtime", "unknown-mode")
    r = run_sandbox_python("x")
    assert "shim" in r.stdout


def test_interrogate_writes_request_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recv = tmp_path / "received.json"
    helper = tmp_path / "capture.sh"
    helper.write_text(
        "#!/bin/sh\n"
        f"cp \"$1\" \"{recv}\"\n"
        'echo \'{"status": "success", "finding": "ok"}\'\n',
        encoding="utf-8",
    )
    helper.chmod(0o755)
    workdir = tmp_path / "fc_work"
    workdir.mkdir()

    payload = tmp_path / "doc.pdf"
    payload.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")

    monkeypatch.setattr(settings, "sandbox_runtime", "firecracker")
    monkeypatch.setattr(settings, "sandbox_firecracker_helper", str(helper))
    monkeypatch.setattr(settings, "sandbox_kernel_image", "/k/vmlinux")
    monkeypatch.setattr(settings, "sandbox_rootfs_image", "/k/root.ext4")
    monkeypatch.setattr(settings, "sandbox_work_dir", str(workdir))
    monkeypatch.setattr(settings, "sandbox_interrogate_max_mb", 48)
    monkeypatch.setattr(settings, "sandbox_payload_mb", 32)

    r = run_firecracker_interrogate(payload, timeout_seconds=30)
    assert r.exit_code == 0
    assert "success" in r.stdout

    data = json.loads(recv.read_text(encoding="utf-8"))
    assert data.get("mode") == "interrogate"
    assert data.get("payload_host_path") == str(payload.resolve())


def test_firecracker_writes_request_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recv = tmp_path / "received.json"
    helper = tmp_path / "capture.sh"
    helper.write_text(
        "#!/bin/sh\n"
        f"cp \"$1\" \"{recv}\"\n"
        'echo "FIRECLAW_RESULT{\\"exit_code\\":0,\\"stdout\\":\\"done\\",\\"stderr\\":\\"\\"}"\n',
        encoding="utf-8",
    )
    helper.chmod(0o755)
    workdir = tmp_path / "fc_work"
    workdir.mkdir()

    monkeypatch.setattr(settings, "sandbox_runtime", "firecracker")
    monkeypatch.setattr(settings, "sandbox_firecracker_helper", str(helper))
    monkeypatch.setattr(settings, "sandbox_kernel_image", "/k/vmlinux")
    monkeypatch.setattr(settings, "sandbox_rootfs_image", "/k/root.ext4")
    monkeypatch.setattr(settings, "sandbox_work_dir", str(workdir))

    run_sandbox_python("a = 1")

    data = json.loads(recv.read_text(encoding="utf-8"))
    assert data["kernel"] == "/k/vmlinux"
    assert data["rootfs"] == "/k/root.ext4"
    assert data["code"] == "a = 1"
    assert "timeout_seconds" in data
