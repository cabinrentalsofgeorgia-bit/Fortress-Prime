#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/admin/Fortress-Prime"
SYSTEMD_DIR="${ROOT_DIR}/deploy/systemd"

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

install -m 0755 "${SYSTEMD_DIR}/run-fortress-backend.sh" /usr/local/bin/run-fortress-backend.sh
install -m 0755 "${SYSTEMD_DIR}/run-fortress-dashboard.sh" /usr/local/bin/run-fortress-dashboard.sh
install -m 0755 "${SYSTEMD_DIR}/run-fortress-channex-egress.sh" /usr/local/bin/run-fortress-channex-egress.sh
install -m 0755 "${SYSTEMD_DIR}/run-fortress-event-consumer.sh" /usr/local/bin/run-fortress-event-consumer.sh
install -m 0644 "${SYSTEMD_DIR}/fortress-backend.service" /etc/systemd/system/fortress-backend.service
install -m 0644 "${SYSTEMD_DIR}/fortress-dashboard.service" /etc/systemd/system/fortress-dashboard.service
install -m 0644 "${SYSTEMD_DIR}/fortress-channex-egress.service" /etc/systemd/system/fortress-channex-egress.service
install -m 0644 "${SYSTEMD_DIR}/fortress-event-consumer.service" /etc/systemd/system/fortress-event-consumer.service
install -m 0644 "${SYSTEMD_DIR}/fortress-deadline-sweeper.service" /etc/systemd/system/fortress-deadline-sweeper.service
install -m 0644 "${SYSTEMD_DIR}/fortress-deadline-sweeper.timer" /etc/systemd/system/fortress-deadline-sweeper.timer

sudo -u admin env \
  PATH="/home/admin/.nvm/versions/node/v20.20.0/bin:/usr/bin:/bin" \
  NEXT_PUBLIC_APP_URL="https://crog-ai.com" \
  FGP_BACKEND_URL="http://127.0.0.1:8100" \
  bash -lc 'cd /home/admin/Fortress-Prime/fortress-guest-platform/frontend-next && npm run build'

systemctl daemon-reload
systemctl enable fortress-backend.service fortress-dashboard.service fortress-channex-egress.service fortress-event-consumer.service fortress-deadline-sweeper.timer
systemctl restart fortress-backend.service fortress-dashboard.service fortress-channex-egress.service fortress-event-consumer.service
systemctl restart fortress-deadline-sweeper.timer

systemctl --no-pager --full status fortress-backend.service
systemctl --no-pager --full status fortress-dashboard.service
systemctl --no-pager --full status fortress-channex-egress.service
systemctl --no-pager --full status fortress-event-consumer.service
systemctl --no-pager --full status fortress-deadline-sweeper.timer
