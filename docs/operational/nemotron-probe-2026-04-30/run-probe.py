"""Run a single probe against the Nemotron-3-Super frontier and capture metrics."""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ENDPOINT = "http://10.10.10.3:8000/v1/chat/completions"
RUN_DIR = Path(sys.argv[0]).parent
PROBE_NAME = sys.argv[1]  # A, B, C, D, E
BODY_PATH = RUN_DIR / "requests" / f"probe-{PROBE_NAME}-body.json"
RESP_PATH = RUN_DIR / "responses" / f"probe-{PROBE_NAME}-response.json"
METRICS_PATH = RUN_DIR / "responses" / f"probe-{PROBE_NAME}-metrics.json"

body_bytes = BODY_PATH.read_bytes()
print(f"=== Probe {PROBE_NAME} ===  body={len(body_bytes)}B", flush=True)

req = urllib.request.Request(
    ENDPOINT,
    data=body_bytes,
    headers={"Content-Type": "application/json"},
    method="POST",
)
started = time.monotonic()
try:
    with urllib.request.urlopen(req, timeout=900) as resp:
        raw = resp.read()
        status = resp.status
except urllib.error.HTTPError as e:
    raw = e.read()
    status = e.code
ended = time.monotonic()
wall = round(ended - started, 2)

RESP_PATH.write_bytes(raw)
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print(f"  HTTP {status} non-JSON response, wrote raw to {RESP_PATH}", flush=True)
    METRICS_PATH.write_text(json.dumps({"probe": PROBE_NAME, "http_status": status, "wall_seconds": wall, "error": "non-JSON response"}, indent=2))
    sys.exit(1)

if status != 200:
    print(f"  HTTP {status}: {data}", flush=True)
    METRICS_PATH.write_text(json.dumps({"probe": PROBE_NAME, "http_status": status, "wall_seconds": wall, "error": data}, indent=2))
    sys.exit(1)

# Extract metrics
choice = data.get("choices", [{}])[0]
msg = choice.get("message", {})
content = msg.get("content") or ""
reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
finish = choice.get("finish_reason")
usage = data.get("usage", {})

metrics = {
    "probe": PROBE_NAME,
    "http_status": status,
    "wall_seconds": wall,
    "content_chars": len(content),
    "content_is_null": msg.get("content") is None,
    "reasoning_chars": len(reasoning),
    "reasoning_is_null": msg.get("reasoning_content") is None and msg.get("reasoning") is None,
    "finish_reason": finish,
    "prompt_tokens": usage.get("prompt_tokens"),
    "completion_tokens": usage.get("completion_tokens"),
    "total_tokens": usage.get("total_tokens"),
    "first_50_content": content[:50],
    "first_50_reasoning": reasoning[:50],
}
METRICS_PATH.write_text(json.dumps(metrics, indent=2))
print(json.dumps({k: v for k, v in metrics.items() if k not in ("first_50_content", "first_50_reasoning")}, indent=2))
