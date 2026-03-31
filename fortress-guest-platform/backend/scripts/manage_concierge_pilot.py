"""
Manage the Division 1 Concierge outbound pilot in the DGX runtime overlay.

Examples:
  python backend/scripts/manage_concierge_pilot.py status
  python backend/scripts/manage_concierge_pilot.py arm \
      --guest-id 029cdb93-df00-4d4e-a730-2fcc3f7177e7 \
      --property-slug above-the-timberline
  python backend/scripts/manage_concierge_pilot.py disarm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DGX_ENV_PATH = PROJECT_ROOT / ".env.dgx"
BASE_ENV_PATH = PROJECT_ROOT / ".env"
SECURITY_ENV_PATH = PROJECT_ROOT.parent / ".env.security"
DEFAULT_SERVICE = "fortress-backend.service"

PILOT_KEYS = {
    "ENABLE_AUTO_REPLIES",
    "CONCIERGE_RECOVERY_SMS_ENABLED",
    "CONCIERGE_STRIKE_ENABLED",
    "CONCIERGE_STRIKE_ALLOWED_GUEST_IDS",
    "CONCIERGE_STRIKE_ALLOWED_PROPERTY_SLUGS",
    "CONCIERGE_STRIKE_ALLOWED_LOYALTY_TIERS",
}


def _parse_env_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Runtime overlay not found: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in _parse_env_lines(path):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _merged_runtime_values(env_path: Path) -> dict[str, str]:
    merged: dict[str, str] = {}
    for candidate in (BASE_ENV_PATH, env_path, SECURITY_ENV_PATH):
        if candidate.exists():
            merged.update(_read_env_values(candidate))
    return merged


def _set_env_values(path: Path, updates: dict[str, str]) -> None:
    lines = _parse_env_lines(path)
    remaining = dict(updates)
    rewritten: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rewritten.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            rewritten.append(f"{key}={remaining.pop(key)}")
        else:
            rewritten.append(raw)
    if remaining:
        if rewritten and rewritten[-1].strip():
            rewritten.append("")
        rewritten.append("# Managed by backend/scripts/manage_concierge_pilot.py")
        for key, value in remaining.items():
            rewritten.append(f"{key}={value}")
    path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def _restart_service(service_name: str) -> None:
    subprocess.run(["sudo", "systemctl", "restart", service_name], check=True)


def _wait_for_service_active(service_name: str, *, timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _service_status(service_name) == "active":
            time.sleep(3)
            return
        time.sleep(0.5)
    raise TimeoutError(f"{service_name} did not become active within {timeout_seconds:.1f}s")


def _service_status(service_name: str) -> str:
    result = subprocess.run(
        ["systemctl", "is-active", service_name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown"


def _arm(values: dict[str, str], args: argparse.Namespace) -> dict[str, str]:
    updates = dict(values)
    updates["ENABLE_AUTO_REPLIES"] = "true"
    updates["CONCIERGE_RECOVERY_SMS_ENABLED"] = "true"
    updates["CONCIERGE_STRIKE_ENABLED"] = "true"
    updates["CONCIERGE_STRIKE_ALLOWED_GUEST_IDS"] = args.guest_id
    updates["CONCIERGE_STRIKE_ALLOWED_PROPERTY_SLUGS"] = args.property_slug
    if args.loyalty_tiers is not None:
        updates["CONCIERGE_STRIKE_ALLOWED_LOYALTY_TIERS"] = args.loyalty_tiers
    return updates


def _disarm(values: dict[str, str], args: argparse.Namespace) -> dict[str, str]:
    updates = dict(values)
    updates["ENABLE_AUTO_REPLIES"] = "false"
    updates["CONCIERGE_RECOVERY_SMS_ENABLED"] = "false"
    updates["CONCIERGE_STRIKE_ENABLED"] = "false"
    if args.clear_allowlists:
        updates["CONCIERGE_STRIKE_ALLOWED_GUEST_IDS"] = ""
        updates["CONCIERGE_STRIKE_ALLOWED_PROPERTY_SLUGS"] = ""
        updates["CONCIERGE_STRIKE_ALLOWED_LOYALTY_TIERS"] = ""
    return updates


def _print_status(path: Path, service_name: str) -> None:
    values = _read_env_values(path)
    print(f"env_path={path}")
    print(f"service={service_name}")
    print(f"service_status={_service_status(service_name)}")
    for key in sorted(PILOT_KEYS):
        print(f"{key}={values.get(key, '')}")


async def _verify_live_route(path: Path, args: argparse.Namespace) -> int:
    values = _merged_runtime_values(path)
    token = (
        values.get("INTERNAL_API_TOKEN")
        or values.get("SWARM_API_KEY")
        or ""
    ).strip()
    if not token:
        raise RuntimeError("INTERNAL_API_TOKEN or SWARM_API_KEY must be set for verify.")

    base_url = (values.get("INTERNAL_API_BASE_URL") or "http://127.0.0.1:8100").strip().rstrip("/")
    payload = {
        "guest_id": args.guest_id,
        "reservation_id": args.reservation_id,
        "body": args.body,
        "consensus_conviction": args.consensus_conviction,
        "minimum_conviction": args.minimum_conviction,
    }

    deadline = time.monotonic() + args.connect_wait_seconds
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
        while True:
            try:
                response = await client.post(
                    f"{base_url}/api/agent/tools/guest-send-sms",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                break
            except httpx.ConnectError as exc:
                last_error = exc
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.5)

    body = response.json()
    summary = {
        "http_status": response.status_code,
        "status": body.get("status"),
        "error_message": body.get("error_message"),
        "workflow": (body.get("data") or {}).get("workflow"),
        "audit_log": (body.get("data") or {}).get("audit_log"),
        "delivery": (body.get("data") or {}).get("delivery"),
    }
    print(json.dumps(summary, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the Division 1 Concierge outbound pilot.")
    parser.add_argument("--env-file", default=str(DGX_ENV_PATH), help="Path to the runtime overlay file.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="systemd service to restart.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show current pilot env values and service state.")
    status_parser.set_defaults(handler="status")

    arm_parser = subparsers.add_parser("arm", help="Enable live outbound pilot for an explicit cohort.")
    arm_parser.add_argument("--guest-id", required=True, help="Single allowed guest UUID.")
    arm_parser.add_argument("--property-slug", required=True, help="Single allowed property slug.")
    arm_parser.add_argument(
        "--loyalty-tiers",
        default=None,
        help="Optional comma-separated loyalty tiers allowlist (leave unset for no tier filter).",
    )
    arm_parser.add_argument("--no-restart", action="store_true", help="Do not restart the backend service.")
    arm_parser.add_argument(
        "--restart-wait-seconds",
        type=float,
        default=20.0,
        help="How long to wait for the service to become active after restart.",
    )
    arm_parser.set_defaults(handler="arm")

    disarm_parser = subparsers.add_parser("disarm", help="Disable live outbound pilot.")
    disarm_parser.add_argument("--clear-allowlists", action="store_true", help="Clear stored cohort allowlists too.")
    disarm_parser.add_argument("--no-restart", action="store_true", help="Do not restart the backend service.")
    disarm_parser.add_argument(
        "--restart-wait-seconds",
        type=float,
        default=20.0,
        help="How long to wait for the service to become active after restart.",
    )
    disarm_parser.set_defaults(handler="disarm")

    verify_parser = subparsers.add_parser("verify", help="Probe the live guest-send-sms route.")
    verify_parser.add_argument("--guest-id", required=True, help="Guest UUID to test.")
    verify_parser.add_argument("--reservation-id", required=True, help="Reservation UUID to test.")
    verify_parser.add_argument(
        "--body",
        default="Verification probe from manage_concierge_pilot.py",
        help="Body to send to the live route.",
    )
    verify_parser.add_argument("--consensus-conviction", type=float, default=0.91, help="Conviction supplied to the bridge.")
    verify_parser.add_argument("--minimum-conviction", type=float, default=0.8, help="Minimum conviction supplied to the bridge.")
    verify_parser.add_argument("--timeout-seconds", type=float, default=60.0, help="HTTP timeout for the live probe.")
    verify_parser.add_argument(
        "--connect-wait-seconds",
        type=float,
        default=10.0,
        help="How long to retry connection errors while the backend socket comes up.",
    )
    verify_parser.set_defaults(handler="verify")

    args = parser.parse_args()
    env_path = Path(args.env_file).expanduser().resolve()

    if args.handler == "status":
        _print_status(env_path, args.service)
        return 0
    if args.handler == "verify":
        return asyncio.run(_verify_live_route(env_path, args))

    values = _read_env_values(env_path)
    updates = _arm(values, args) if args.handler == "arm" else _disarm(values, args)
    _set_env_values(env_path, updates)

    if not args.no_restart:
        _restart_service(args.service)
        _wait_for_service_active(args.service, timeout_seconds=args.restart_wait_seconds)

    _print_status(env_path, args.service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
