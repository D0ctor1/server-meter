#!/usr/bin/env bash
# Remove the systemd service and optional install prefix.
# Does not wipe /etc/server-meter unless --purge is given.
set -euo pipefail

PREFIX="${PREFIX:-/opt/server-meter}"
CONFIG_DIR="${CONFIG_DIR:-/etc/server-meter}"
SERVICE_USER="${SERVICE_USER:-server-meter}"
PURGE=0

if [[ "${1:-}" == "--purge" ]]; then
  PURGE=1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 [--purge]" >&2
  exit 1
fi

systemctl stop server-meter.service 2>/dev/null || true
systemctl disable server-meter.service 2>/dev/null || true
rm -f /etc/systemd/system/server-meter.service
systemctl daemon-reload

rm -rf "${PREFIX}"

if [[ "${PURGE}" -eq 1 ]]; then
  rm -rf "${CONFIG_DIR}"
  if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    deluser --system "${SERVICE_USER}" 2>/dev/null || userdel "${SERVICE_USER}" 2>/dev/null || true
  fi
  echo "Purged ${CONFIG_DIR} and user ${SERVICE_USER}."
else
  echo "Left ${CONFIG_DIR} in place. Use --purge to delete config and the service user."
fi

echo "Uninstalled. No sensor history existed on disk."
