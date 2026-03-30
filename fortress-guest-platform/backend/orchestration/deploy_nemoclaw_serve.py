from __future__ import annotations

import os

import ray
from ray import serve

from backend.orchestration.nemoclaw_serve import deployment


def main() -> None:
    ray_address = os.getenv("FORTRESS_RAY_ADDRESS", "192.168.0.100:6390")
    app_name = os.getenv("FORTRESS_NEMOCLAW_APP_NAME", "nemoclaw-alpha")
    http_host = os.getenv("FORTRESS_NEMOCLAW_HTTP_HOST", "0.0.0.0")
    http_port = int(os.getenv("FORTRESS_NEMOCLAW_HTTP_PORT", "8000"))

    ray.init(address=ray_address, ignore_reinit_error=True)
    serve.start(
        detached=True,
        http_options={
            "host": http_host,
            "port": http_port,
        },
    )
    serve.run(
        deployment,
        blocking=False,
        name=app_name,
        route_prefix="/",
    )
    print(f"NemoClaw Serve deployed as {app_name} on {ray_address} with HTTP {http_host}:{http_port}")


if __name__ == "__main__":
    main()
