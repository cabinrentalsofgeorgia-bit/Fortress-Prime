#!/usr/bin/env python3
"""
deploy_judge.py — Deploy a trained LoRA adapter as an Ollama judge model.

Generates an Ollama Modelfile that applies the LoRA adapter to qwen2.5:7b,
copies the adapter to the target node, creates the Ollama model, runs a
smoke test, and writes a deployment manifest.

Usage:
  python -m src.judge.deploy_judge \\
      --judge-name vrs_concierge_judge \\
      --adapter /mnt/fortress_nas/judge-artifacts/<name>-<date>/ \\
      --target-node 192.168.0.106 \\
      --base-ollama-model qwen2.5:7b \\
      [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"deploy_judge"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("deploy_judge")

_NODE_LABELS: dict[str, str] = {
    "192.168.0.100": "spark-2",
    "192.168.0.104": "spark-1",
    "192.168.0.105": "spark-3",
    "192.168.0.106": "spark-4",
}

_MODELFILE_TEMPLATE = """\
FROM {base_model}
ADAPTER {adapter_path}
SYSTEM "{system_prompt}"
PARAMETER temperature 0.1
PARAMETER num_predict 128
"""

_JUDGE_SYSTEM = (
    'You are a quality judge. Output JSON only: '
    '{{"decision": "confident|uncertain|escalate", "reasoning": "<one sentence>"}}'
)

_SMOKE_PROMPT = (
    'Prompt: When is checkout?\n\n'
    'Response: Checkout is at 11am.\n\n'
    'Evaluate quality. Return JSON.'
)


def _run_remote(ip: str, cmd: str, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=10", f"admin@{ip}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout or r.stderr).strip()


def _rsync(src: Path, target_ip: str, dst: str) -> int:
    r = subprocess.run(
        ["rsync", "-av", "--progress", str(src) + "/",
         f"admin@{target_ip}:{dst}/"],
        capture_output=True, timeout=300,
    )
    return r.returncode


def deploy_judge(
    judge_name: str,
    adapter_path: Path,
    target_ip: str,
    base_model: str,
    dry_run: bool,
) -> dict:
    manifest_file = adapter_path / "training_manifest.json"
    if not manifest_file.exists() and not dry_run:
        raise FileNotFoundError(f"training_manifest.json not found at {adapter_path}")

    version     = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    model_name  = f"{judge_name}:{version}"
    node_label  = _NODE_LABELS.get(target_ip, target_ip)
    remote_dir  = f"/tmp/judge-adapters/{judge_name}-{version}"

    log.info("deploy_judge judge=%s → %s (%s) model=%s dry_run=%s",
             judge_name, node_label, target_ip, model_name, dry_run)

    if dry_run:
        log.info("[DRY RUN] Would rsync %s → %s:%s", adapter_path, target_ip, remote_dir)
        log.info("[DRY RUN] Would create Ollama model %s on %s", model_name, node_label)
        return {"dry_run": True, "judge_name": judge_name, "version": version,
                "target_node": node_label, "model_name": model_name}

    # Sync adapter to target node
    log.info("Rsyncing adapter to %s:%s", target_ip, remote_dir)
    rc = _rsync(adapter_path, target_ip, remote_dir)
    if rc != 0:
        raise RuntimeError(f"rsync failed (exit {rc})")
    log.info("Adapter synced.")

    # Write Modelfile on target node
    modelfile_content = _MODELFILE_TEMPLATE.format(
        base_model=base_model,
        adapter_path=remote_dir,
        system_prompt=_JUDGE_SYSTEM,
    )
    modelfile_remote = f"{remote_dir}/Modelfile"
    rc, out = _run_remote(target_ip, f"cat > {modelfile_remote} << 'MODELEOF'\n{modelfile_content}\nMODELEOF")
    log.info("Modelfile written on remote: rc=%d", rc)

    # Create Ollama model
    log.info("Creating Ollama model %s on %s", model_name, node_label)
    rc, out = _run_remote(
        target_ip,
        f"ollama create {model_name} -f {modelfile_remote}",
        timeout=300,
    )
    if rc != 0:
        raise RuntimeError(f"ollama create failed (exit {rc}): {out[:200]}")
    log.info("Model created: %s", out[:100])

    # Smoke test
    log.info("Smoke test on %s", node_label)
    rc, smoke = _run_remote(
        target_ip,
        f"ollama run {model_name} '{_SMOKE_PROMPT}'",
        timeout=30,
    )
    smoke_ok = False
    if rc == 0:
        try:
            parsed = json.loads(smoke.strip())
            smoke_ok = parsed.get("decision") in ("confident", "uncertain", "escalate")
        except (json.JSONDecodeError, AttributeError):
            smoke_ok = any(w in smoke.lower() for w in ("confident", "uncertain", "escalate"))
    log.info("Smoke test: ok=%s output=%r", smoke_ok, smoke[:100])

    # Update fortress_atlas.yaml — add model to node's model list
    atlas_path = Path(__file__).resolve().parents[2] / "fortress_atlas.yaml"
    if atlas_path.exists():
        try:
            import yaml
            with open(atlas_path) as f:
                atlas = yaml.safe_load(f)
            nodes = atlas.get("fortress_prime", {}).get("cluster", {}).get("nodes", [])
            for node in nodes:
                if node.get("management_ip") == target_ip:
                    models = node.setdefault("models", [])
                    if not any(m.get("name") == model_name for m in models):
                        models.append({"name": model_name, "tier": "judge"})
            with open(atlas_path, "w") as f:
                yaml.dump(atlas, f, default_flow_style=False, sort_keys=False)
            log.info("fortress_atlas.yaml updated with %s on %s", model_name, node_label)
        except Exception as exc:
            log.warning("Could not update atlas: %s", exc)

    result = {
        "judge_name":       judge_name,
        "model_name":       model_name,
        "version":          version,
        "target_node":      node_label,
        "target_ip":        target_ip,
        "base_model":       base_model,
        "adapter_path":     str(adapter_path),
        "remote_dir":       remote_dir,
        "deployed_at":      datetime.now(tz=timezone.utc).isoformat(),
        "smoke_test_ok":    smoke_ok,
        "smoke_output":     smoke[:300],
    }
    (adapter_path / "deployment_manifest.json").write_text(json.dumps(result, indent=2))
    log.info("Deployment manifest written. smoke_ok=%s", smoke_ok)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-name",          required=True)
    parser.add_argument("--adapter",             required=True, type=Path)
    parser.add_argument("--target-node",         default="192.168.0.106")
    parser.add_argument("--base-ollama-model",   default="qwen2.5:7b")
    parser.add_argument("--dry-run",             action="store_true")
    args = parser.parse_args()

    if not args.adapter.exists() and not args.dry_run:
        log.error("Adapter path not found: %s", args.adapter)
        return 1

    try:
        result = deploy_judge(
            args.judge_name, args.adapter,
            args.target_node, args.base_ollama_model,
            args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        log.error("Deploy failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
