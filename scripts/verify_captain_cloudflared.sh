#!/usr/bin/env bash
set -euo pipefail

TUNNEL_ID="${TUNNEL_ID:-aa7222a3-c1c9-4ee3-97c8-fb46b41a654e}"
EXPECTED_PROTOCOL="${EXPECTED_PROTOCOL:-http2}"
EXPECTED_HA_CONNECTIONS="${EXPECTED_HA_CONNECTIONS:-4}"
PUBLIC_URL="${PUBLIC_URL:-https://crog-ai.com/login}"
WWW_LOGIN_URL="${WWW_LOGIN_URL:-https://www.crog-ai.com/login}"
CONFIG_PATH="${CONFIG_PATH:-/etc/cloudflared/config.yml}"
SERVICE_NAME="${SERVICE_NAME:-cloudflared.service}"
METRICS_URL="${METRICS_URL:-http://127.0.0.1:20241/metrics}"

STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LOG_TAG="[captain-cloudflared-smoke ${STAMP}]"

log() {
  echo "${LOG_TAG} $*"
}

die() {
  echo "${LOG_TAG} FATAL: $*" >&2
  exit 1
}

command -v cloudflared >/dev/null 2>&1 || die "cloudflared not found"
command -v systemctl >/dev/null 2>&1 || die "systemctl not found"
command -v curl >/dev/null 2>&1 || die "curl not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"

[[ -f "${CONFIG_PATH}" ]] || die "config file missing at ${CONFIG_PATH}"

log "Checking ${SERVICE_NAME} active state"
systemctl is-active --quiet "${SERVICE_NAME}" || die "${SERVICE_NAME} is not active"

log "Validating tunnel config"
cloudflared tunnel --config "${CONFIG_PATH}" ingress validate >/dev/null

log "Checking configured transport pin"
python3 - "${CONFIG_PATH}" "${EXPECTED_PROTOCOL}" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
expected = sys.argv[2]
protocol = None
for raw_line in config_path.read_text().splitlines():
    line = raw_line.strip()
    if line.startswith("protocol:"):
        protocol = line.split(":", 1)[1].strip()
        break
if protocol != expected:
    raise SystemExit(f"expected protocol {expected!r}, got {protocol!r}")
print(protocol)
PY

log "Checking package version"
cloudflared --version

log "Checking tunnel connector state"
TUNNEL_INFO="$(cloudflared tunnel info "${TUNNEL_ID}")"
echo "${TUNNEL_INFO}"

TUNNEL_INFO="${TUNNEL_INFO}" python3 - "${EXPECTED_HA_CONNECTIONS}" <<'PY'
import re
import os
import sys

expected = int(sys.argv[1])
text = os.environ["TUNNEL_INFO"]
counts = [int(match) for match in re.findall(r'(\d+)x[a-z]{3}\d+', text)]
actual = sum(counts)
if actual < expected:
    raise SystemExit(f"expected at least {expected} ha connections, got {actual}")
print(f"ha_connections={actual}")
PY

log "Checking metrics endpoint"
python3 - "${METRICS_URL}" "${EXPECTED_HA_CONNECTIONS}" <<'PY'
import sys
import urllib.request

metrics_url = sys.argv[1]
expected = int(sys.argv[2])
text = urllib.request.urlopen(metrics_url, timeout=5).read().decode()
values = {}
for key in (
    "cloudflared_tunnel_ha_connections",
    "cloudflared_tunnel_request_errors",
    "cloudflared_tunnel_total_requests",
):
    for line in text.splitlines():
        if line.startswith(key + " "):
            values[key] = line.split()[-1]
            break
missing = [key for key in (
    "cloudflared_tunnel_ha_connections",
    "cloudflared_tunnel_request_errors",
    "cloudflared_tunnel_total_requests",
) if key not in values]
if missing:
    raise SystemExit(f"missing metrics: {', '.join(missing)}")
ha = int(float(values["cloudflared_tunnel_ha_connections"]))
errors = float(values["cloudflared_tunnel_request_errors"])
if ha < expected:
    raise SystemExit(f"expected at least {expected} HA connections in metrics, got {ha}")
if errors > 2:
    raise SystemExit(f"expected at most 2 transient tunnel request errors, got {errors}")
for key in (
    "cloudflared_tunnel_ha_connections",
    "cloudflared_tunnel_request_errors",
    "cloudflared_tunnel_total_requests",
):
    print(f"{key} {values[key]}")
PY

log "Checking crog-ai.com ingress maps to Next.js :3001 (not FastAPI :8100)"
python3 - "${CONFIG_PATH}" <<'PY'
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
text = config_path.read_text()
lines = text.splitlines()

def rule_for_hostname(target: str, required_path: str | None = None):
    host_re = re.compile(
        rf"^\s*-\s*hostname:\s*{re.escape(target)}\s*$|^\s*hostname:\s*{re.escape(target)}\s*$"
    )
    for i, line in enumerate(lines):
        if not host_re.match(line):
            continue
        path_value = None
        service_value = None
        for j in range(i + 1, min(i + 8, len(lines))):
            path_match = re.match(r"^\s*path:\s*(.+?)\s*$", lines[j])
            if path_match:
                path_value = path_match.group(1).strip().strip('"').strip("'")
            m = re.match(r"^\s*service:\s*(.+?)\s*$", lines[j])
            if m:
                service_value = m.group(1).strip()
                break
        if service_value is None:
            continue
        if required_path is None and path_value is not None:
            continue
        if required_path is not None and path_value != required_path:
            continue
        return {"service": service_value, "path": path_value}
    return None

for hn in ("crog-ai.com", "www.crog-ai.com"):
    root_rule = rule_for_hostname(hn)
    if root_rule is None:
        continue
    svc = root_rule["service"]
    if re.search(r":8100\b", svc) or re.search(r"localhost:8100|127\.0\.0\.1:8100", svc):
        raise SystemExit(
            f"ingress for {hn} points to FastAPI ({svc}). "
            "Staff UI must be Next.js on port 3001, e.g. http://127.0.0.1:3001 — "
            "otherwise https://crog-ai.com/login will never load the Command Center."
        )
    if not re.search(r":3001\b", svc):
        raise SystemExit(
            f"ingress for {hn} is {svc!r} — expected http://127.0.0.1:3001 (or localhost:3001) for Command Center"
        )
    print(f"ingress_ok {hn} -> {svc}")

for hn in ("crog-ai.com", "www.crog-ai.com"):
    orchestrator_rule = rule_for_hostname(hn, "^/orchestrator(?:/.*)?$")
    if orchestrator_rule is None:
        raise SystemExit(f"missing /orchestrator path rule for {hn}")
    svc = orchestrator_rule["service"]
    if not re.search(r":18180\b", svc):
        raise SystemExit(
            f"/orchestrator ingress for {hn} is {svc!r} — expected http://192.168.0.100:18180"
        )
    print(f"orchestrator_ingress_ok {hn} -> {svc}")

# If no crog-ai rule found, warn only (some tunnels use catch-all)
if rule_for_hostname("crog-ai.com") is None:
    print("note: no explicit hostname: crog-ai.com in config (skipping port check)")
PY

log "Checking public reachability (apex)"
HTTP_STATUS_LINE="$(curl -I --max-time 15 --silent --show-error "${PUBLIC_URL}" | python3 -c "import sys
for raw in sys.stdin:
    line = raw.strip()
    if line.startswith('HTTP/'):
        print(line)
        break
")"
[[ -n "${HTTP_STATUS_LINE}" ]] || die "no HTTP status line returned from ${PUBLIC_URL}"
echo "${HTTP_STATUS_LINE}"

case "${HTTP_STATUS_LINE}" in
  HTTP/*" 2"*|HTTP/*" 3"*)
    ;;
  *)
    die "unexpected public status: ${HTTP_STATUS_LINE}"
    ;;
esac

log "Checking www hostname (must reach tunnel, not Cloudflare 404)"
WWW_STATUS="$(curl -I --max-time 15 --silent --show-error "${WWW_LOGIN_URL}" | python3 -c "import sys
for raw in sys.stdin:
    line = raw.strip()
    if line.startswith('HTTP/'):
        print(line)
        break
")"
[[ -n "${WWW_STATUS}" ]] || die "no HTTP status line returned from ${WWW_LOGIN_URL}"
echo "${WWW_STATUS}"
case "${WWW_STATUS}" in
  HTTP/*" 404"*)
    die "${WWW_LOGIN_URL} returned 404. DNS may exist but www is not bound to this tunnel in Cloudflare Zero Trust (Public hostnames), or www must redirect to apex. See docs/CAPTAIN_CLOUDFLARED_RUNBOOK.md (www hostname)."
    ;;
  HTTP/*" 2"*|HTTP/*" 3"*)
    ;;
  *)
    die "unexpected www status: ${WWW_STATUS}"
    ;;
esac

log "Captain cloudflared smoke passed"
