#!/usr/bin/env python3
"""
Host-local HTTP bridge into the vLLM container namespace.

The vLLM container on Captain is healthy but not published onto the host
network. This bridge keeps the model reachable at a stable loopback address for
local automation without restarting the model container or exposing a public
port.
"""

from __future__ import annotations

import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


BIND_HOST = os.getenv("VLLM_BRIDGE_BIND", "127.0.0.1")
BIND_PORT = int(os.getenv("VLLM_BRIDGE_PORT", "18001"))
# AUDIT NOTE (2026-04-22): Container "vllm-70b-captain" does not exist in `docker ps`.
# fortress-vllm-bridge.service is active but non-functional. Before re-enabling,
# stand up the target container or update VLLM_BRIDGE_CONTAINER env var.
CONTAINER_NAME = os.getenv("VLLM_BRIDGE_CONTAINER", "vllm-70b-captain")
TARGET_BASE_URL = os.getenv("VLLM_BRIDGE_TARGET_URL", "http://127.0.0.1:8000").rstrip("/")
DOCKER_BIN = os.getenv("DOCKER_BIN", "/usr/bin/docker")


class VllmBridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def _proxy(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b""
        target_url = f"{TARGET_BASE_URL}{self.path}"
        command = [
            DOCKER_BIN,
            "exec",
            "-i",
            CONTAINER_NAME,
            "curl",
            "-sS",
            "-D",
            "-",
            "-X",
            self.command,
            target_url,
        ]

        for header_name in ("Accept", "Content-Type", "Authorization"):
            header_value = self.headers.get(header_name)
            if header_value:
                command.extend(["-H", f"{header_name}: {header_value}"])

        if body:
            command.extend(["--data-binary", "@-"])

        result = subprocess.run(
            command,
            input=body,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            error_payload = result.stderr or b"vLLM bridge upstream failure"
            self.send_response(502)
            self.send_header("Content-Length", str(len(error_payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(error_payload)
            return

        header_blob, _, response_body = result.stdout.partition(b"\r\n\r\n")
        header_lines = header_blob.decode("latin1").split("\r\n") if header_blob else []
        status_code = 200
        if header_lines and header_lines[0].startswith("HTTP/"):
            parts = header_lines[0].split()
            if len(parts) > 1 and parts[1].isdigit():
                status_code = int(parts[1])

        self.send_response(status_code)
        sent_content_length = False
        for line in header_lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized = key.lower()
            if normalized in {"transfer-encoding", "connection", "content-encoding"}:
                continue
            if normalized == "content-length":
                sent_content_length = True
            self.send_header(key, value.strip())
        if not sent_content_length:
            self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response_body)


def main() -> None:
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), VllmBridgeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
