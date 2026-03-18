#!/usr/bin/env bash
# ABOUTME: Deploy tablebuilder-service to a target host.
# ABOUTME: Installs systemd unit and restarts the service.
set -euo pipefail

TARGET="${1:?Usage: $0 <host>}"
SVC="tablebuilder-service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat "${SCRIPT_DIR}/${SVC}.service" | /usr/bin/ssh "${TARGET}" \
  "sudo tee /etc/systemd/system/${SVC}.service > /dev/null"

/usr/bin/ssh "${TARGET}" \
  "sudo systemctl daemon-reload && sudo systemctl enable ${SVC} && sudo systemctl restart ${SVC}"

echo "Deployed ${SVC} to ${TARGET}"
