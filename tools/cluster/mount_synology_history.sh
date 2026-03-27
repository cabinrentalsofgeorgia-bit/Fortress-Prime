#!/usr/bin/env bash
# Fortress Prime: Synology History Mount for Librarian
set -euo pipefail

SPARK_NODE_IP="${SPARK_NODE_IP:-192.168.0.104}"
SYNOLOGY_HOST="${SYNOLOGY_HOST:-192.168.0.250}"
SYNOLOGY_EXPORT="${SYNOLOGY_EXPORT:-/volume1/history}"
MOUNT_POINT="${MOUNT_POINT:-/opt/fortress/data/history}"
SANDBOX_NAME="${SANDBOX_NAME:-Librarian}"

echo ">>> [FORTRESS] Mounting Synology History to Spark 1 (${SPARK_NODE_IP})..."

# 1. Ensure mount point exists in the Librarian's jail
sudo mkdir -p "${MOUNT_POINT}"

# 2. Mount via NFS (optimized for the internal fabric)
sudo mount -t nfs "${SYNOLOGY_HOST}:${SYNOLOGY_EXPORT}" "${MOUNT_POINT}" \
  -o nfsvers=4,proto=tcp,hard,intr,rsize=1048576,wsize=1048576

# 3. Update OpenShell manifest to allow Librarian read-only access
# This keeps the history available to the agent while preventing writes.
openshell sandbox update "${SANDBOX_NAME}" --mount "${MOUNT_POINT}:/mnt/history:ro"

echo ">>> [FORTRESS] Synology History mounted and exposed to ${SANDBOX_NAME}."
