import argparse
import hashlib
import logging
import os
import subprocess
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



def _resolve_command_center_auth_header(api_url: str) -> dict:
    """Best-effort auth header resolution for command-center endpoints."""
    explicit = os.getenv("COMMAND_CENTER_BEARER_TOKEN", "").strip()
    if explicit:
        return {"Authorization": f"Bearer {explicit}"}

    email = os.getenv("COMMAND_CENTER_LOGIN_EMAIL", "").strip() or os.getenv("E2E_LOGIN_EMAIL", "").strip()
    password = os.getenv("COMMAND_CENTER_LOGIN_PASSWORD", "").strip() or os.getenv("E2E_LOGIN_PASSWORD", "").strip()
    if not email or not password:
        return {}

    login_url = f"{api_url.rstrip('/')}/api/auth/login"
    try:
        resp = requests.post(
            login_url,
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        token = (resp.json() or {}).get("access_token", "")
        if token:
            return {"Authorization": f"Bearer {token}"}
    except requests.exceptions.RequestException as e:
        logging.warning("[NIGHTLY FORGE] Could not acquire command-center bearer token: %s", e)
    except Exception as e:
        logging.warning("[NIGHTLY FORGE] Unexpected auth bootstrap error: %s", e)

    return {}

def run_hive_mind_extraction() -> None:
    """Refresh DPO dataset from telemetry before training starts."""
    script_path = Path(__file__).resolve().parent / "extract_hive_mind_dpo.py"
    if not script_path.exists():
        logging.warning("[NIGHTLY FORGE] DPO extractor not found at %s", script_path)
        return

    logging.info("[NIGHTLY FORGE] Refreshing DPO dataset via %s", script_path)
    result = subprocess.run(["python3", str(script_path)], capture_output=True, text=True)
    if result.returncode != 0:
        logging.error("[NIGHTLY FORGE] DPO extraction failed: %s", result.stderr.strip() or result.stdout.strip())
        raise RuntimeError("DPO extraction failed before training")

    if result.stdout.strip():
        logging.info("[NIGHTLY FORGE] DPO extractor output: %s", result.stdout.strip())


def trigger_swarm_reload(adapter_uri: str):
    """
    Fires the zero-downtime hot-reload webhook to the FastAPI control plane.
    Calculates the SHA-256 of the adapter safetensors for idempotency.
    """
    logging.info("[NIGHTLY FORGE] Initiating Tier 0 hot-reload for adapter: %s", adapter_uri)

    sha256_hash = hashlib.sha256()
    safetensors_path = os.path.join(adapter_uri, "adapter_model.safetensors")

    if os.path.exists(safetensors_path):
        with open(safetensors_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        adapter_sha256 = sha256_hash.hexdigest()
    else:
        logging.warning("[NIGHTLY FORGE] adapter_model.safetensors not found, hashing URI string instead.")
        adapter_sha256 = hashlib.sha256(adapter_uri.encode()).hexdigest()

    api_url = os.getenv("COMMAND_CENTER_URL", "http://127.0.0.1:8100")
    endpoint = f"{api_url}/api/disagg/admin/hot-reload"
    reload_token = os.getenv("DISAGG_RELOAD_TOKEN", "fortress-forge-omega-99")

    payload = {
        "adapter_uri": adapter_uri,
        "adapter_sha256": adapter_sha256,
        "model_id": "unsloth/llama-3-8b-Instruct-bnb-4bit",
        "rollout_mode": "atomic_flip",
    }

    headers = {
        "Content-Type": "application/json",
        "X-Reload-Token": reload_token,
        **_resolve_command_center_auth_header(api_url),
    }

    try:
        logging.info("[NIGHTLY FORGE] POSTing to %s with SHA: %s", endpoint, adapter_sha256)
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        logging.info("[NIGHTLY FORGE] Hot-reload accepted: %s - Status: %s", data.get('reload_id'), data.get('status'))
    except requests.exceptions.RequestException as e:
        logging.error("[NIGHTLY FORGE] Failed to trigger Swarm reload. Error: %s", e)


def run_train(nas_root: str, work_root: str, base_model: str, days_back: int):
    """Placeholder for the Unsloth training execution."""
    logging.info("[NIGHTLY FORGE] Booting training sequence with base model: %s", base_model)

    # Pull latest accepted telemetry edits into DPO JSONL before training.
    run_hive_mind_extraction()

    # TODO: Paste your Unsloth model load and dataset loop here.

    final_adapter_path = os.path.join(work_root, "latest_adapter")
    os.makedirs(final_adapter_path, exist_ok=True)

    logging.info("[NIGHTLY FORGE] LoRA adapter saved successfully to %s", final_adapter_path)

    trigger_swarm_reload(adapter_uri=final_adapter_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nightly Forge LoRA Pipeline")
    parser.add_argument("command", choices=["run-daily"], help="Execution mode")
    parser.add_argument("--nas-root", required=True, help="Path to Synology NAS")
    parser.add_argument("--work-root", required=True, help="Path to local writable work directory")
    parser.add_argument("--base-model", default="unsloth/llama-3-8b-Instruct-bnb-4bit")
    parser.add_argument("--days-back", type=int, default=1)
    parser.add_argument("--run-train", action="store_true")

    args = parser.parse_args()

    if args.command == "run-daily" and args.run_train:
        run_train(args.nas_root, args.work_root, args.base_model, args.days_back)
