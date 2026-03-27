#!/usr/bin/env bash
# Fortress Prime: NemoClaw Cluster Bootstrap (Node 2 Leader)
set -euo pipefail

echo ">>> [FORTRESS] Bootstrapping NemoClaw Leader on 192.168.0.100..."

# 1. Environment Verification
if [ -z "${NVIDIA_API_KEY:-}" ]; then
    echo "ERROR: NVIDIA_API_KEY is not set. Aborting."
    exit 1
fi

# 2. DGX Spark / Docker Optimization (Critical for OpenShell)
echo ">>> Applying Spark CGroup v2 Fixes..."
sudo python3 -c "
import json, os
path = '/etc/docker/daemon.json'
d = json.load(open(path)) if os.path.exists(path) else {}
d['default-cgroupns-mode'] = 'host'
with open(path, 'w') as f: json.dump(d, f, indent=2)
"
sudo systemctl restart docker

# 3. Install NemoClaw CLI via NVIDIA's official March 2026 script
echo ">>> Installing NemoClaw CLI and OpenShell..."
if sudo ss -ltn "( sport = :8080 )" | awk 'NR>1 {print $4}' | grep -q ':8080'; then
    echo "ERROR: Port 8080 is already in use. NemoClaw/OpenShell onboarding requires 8080."
    echo "       Current listener(s):"
    sudo ss -ltnp "( sport = :8080 )" || true
    echo "       Stop or remap the conflicting service and rerun bootstrap."
    exit 1
fi

INSTALLER_TMP="$(mktemp /tmp/nemoclaw-installer.XXXXXX.sh)"
curl -fsSL https://nvidia.com/nemoclaw.sh -o "${INSTALLER_TMP}"
# Some installer versions still attempt onboarding even with --no-onboard.
# Force non-interactive mode, ignore installer onboard failure, then verify binary.
NEMOCLAW_NON_INTERACTIVE=1 bash "${INSTALLER_TMP}" --no-onboard || true
rm -f "${INSTALLER_TMP}"

# 4. Verify Binary Presence
export PATH="$PATH:/usr/local/bin:/usr/bin"
if ! command -v nemoclaw &> /dev/null; then
    if command -v node &> /dev/null; then
        NODE_VERSION="$(node -v 2>/dev/null || true)"
        NODE_VERSION="${NODE_VERSION#v}"
        if [ -n "${NODE_VERSION}" ] && [ -x "${HOME}/.nvm/versions/node/v${NODE_VERSION}/bin/nemoclaw" ]; then
            export PATH="${HOME}/.nvm/versions/node/v${NODE_VERSION}/bin:${PATH}"
        fi
    fi
fi
if ! command -v nemoclaw &> /dev/null; then
    echo "ERROR: NemoClaw installation failed. Check network/permissions."
    exit 1
fi

# 5. Onboard the cluster
# Current nemoclaw CLI (2026.3.x) only supports:
#   nemoclaw onboard [--non-interactive]
# It auto-discovers provider/model settings via onboarding config + env.
echo ">>> Onboarding Cluster (non-interactive)..."
NEMOCLAW_NON_INTERACTIVE=1 NVIDIA_API_KEY="$NVIDIA_API_KEY" nemoclaw onboard --non-interactive

# 6. Final Health Check: Target the OpenShell Gateway (the true engine)
echo ">>> Testing OpenShell Gateway on Node 2 (8080)..."
curl -s -X GET http://localhost:8080/health | grep -q 'status":"OK"' && echo ">>> SUCCESS: Node 2 OpenShell is Operational."

# Verify the NemoClaw Local Dashboard (18789)
curl -s -I http://localhost:18789 | grep -q "200 OK" && echo ">>> SUCCESS: NemoClaw Dashboard is Live."
