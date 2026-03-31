"""
Bootstrap reproducible DGX runtime secrets and flags.

Safe to rerun:
- creates /home/admin/Fortress-Prime/.env.security if missing
- preserves existing JWT keys by default
- can rotate JWT keys explicitly with --rotate-jwt

This keeps the local runtime contract out of git while making host recovery
repeatable after restarts, rebuilds, or machine replacement.
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECURITY_ENV_PATH = PROJECT_ROOT.parent / ".env.security"
DGX_ENV_PATH = PROJECT_ROOT / ".env.dgx"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _generate_rsa_keypair_base64() -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        private_path = Path(tmp_dir) / "jwt_private.pem"
        public_path = Path(tmp_dir) / "jwt_public.pem"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(private_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "openssl",
                "rsa",
                "-in",
                str(private_path),
                "-pubout",
                "-out",
                str(public_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        private_b64 = base64.b64encode(private_path.read_bytes()).decode("ascii")
        public_b64 = base64.b64encode(public_path.read_bytes()).decode("ascii")
        return private_b64, public_b64


def bootstrap_runtime(rotate_jwt: bool) -> list[str]:
    notes: list[str] = []
    values = _parse_env_file(SECURITY_ENV_PATH)

    has_private = bool(values.get("JWT_RSA_PRIVATE_KEY"))
    has_public = bool(values.get("JWT_RSA_PUBLIC_KEY"))

    if rotate_jwt or not (has_private and has_public):
        private_b64, public_b64 = _generate_rsa_keypair_base64()
        values["JWT_RSA_PRIVATE_KEY"] = private_b64
        values["JWT_RSA_PUBLIC_KEY"] = public_b64
        values["JWT_KEY_ID"] = values.get("JWT_KEY_ID") or "fgp-rs256-v1"
        _write_env_file(SECURITY_ENV_PATH, values)
        if rotate_jwt:
            notes.append(f"Rotated JWT keypair in `{SECURITY_ENV_PATH}`.")
        else:
            notes.append(f"Created JWT keypair in `{SECURITY_ENV_PATH}`.")
    else:
        notes.append(f"JWT keypair already present in `{SECURITY_ENV_PATH}`.")

    if DGX_ENV_PATH.exists():
        notes.append(f"Found runtime overlay `{DGX_ENV_PATH}`.")
    else:
        notes.append(f"Runtime overlay `{DGX_ENV_PATH}` is missing; copy from `.env.dgx.example`.")

    notes.append("Keep `DB_AUTO_CREATE_TABLES=false` for the live DGX runtime.")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Fortress DGX runtime secrets.")
    parser.add_argument(
        "--rotate-jwt",
        action="store_true",
        help="Rotate the JWT RSA keypair in .env.security.",
    )
    args = parser.parse_args()

    for note in bootstrap_runtime(rotate_jwt=args.rotate_jwt):
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
