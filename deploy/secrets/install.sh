#!/usr/bin/env bash
# install.sh — wire fortress-load-secrets + manifest + systemd drop-in.
#
# Idempotent: safe to re-run after pulling updates. Run as root:
#     sudo bash deploy/secrets/install.sh
#
# Steps:
#   1. Copy fortress-load-secrets.sh -> /usr/local/bin/fortress-load-secrets
#   2. Copy secrets.manifest        -> /etc/fortress/secrets.manifest (0640)
#   3. Copy systemd drop-in         -> /etc/systemd/system/fortress-arq-worker.service.d/00-secrets.conf
#   4. systemctl daemon-reload
#
# Does NOT restart the worker — operator decides when. Does NOT install
# pass entries — those are populated separately:
#     pass insert fortress/mailboxes/<name>

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh: must run as root (sudo)" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")"/../.. && pwd)"
SECRETS_DIR="${REPO_DIR}/deploy/secrets"
SYSTEMD_DIR="${REPO_DIR}/deploy/systemd"

install -m 0755 "${SECRETS_DIR}/fortress-load-secrets.sh" \
  /usr/local/bin/fortress-load-secrets
echo "installed /usr/local/bin/fortress-load-secrets"

mkdir -p /etc/fortress
install -m 0640 -o root -g root \
  "${SECRETS_DIR}/secrets.manifest" \
  /etc/fortress/secrets.manifest
echo "installed /etc/fortress/secrets.manifest"

mkdir -p /etc/systemd/system/fortress-arq-worker.service.d
install -m 0644 \
  "${SYSTEMD_DIR}/fortress-arq-worker.service.d/00-secrets.conf" \
  /etc/systemd/system/fortress-arq-worker.service.d/00-secrets.conf
echo "installed systemd drop-in"

systemctl daemon-reload
echo "systemctl daemon-reload complete"

cat <<'NEXT'

Next steps (operator):
  1. Confirm gpg-agent caches the admin user's passphrase persistently
     (see deploy/secrets/README.md). Without this, systemd cannot
     decrypt pass entries and ExecStartPre will fail.
  2. Verify entries resolve as the admin user:
        sudo -u admin pass show fortress/mailboxes/legal-cpanel >/dev/null && echo OK
  3. Restart the worker:
        sudo systemctl restart fortress-arq-worker
  4. Tail the boot log:
        sudo journalctl -u fortress-arq-worker -n 100 --no-pager
NEXT
