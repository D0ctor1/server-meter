#!/usr/bin/env bash
# Remove server-meter. Keeps /etc/server-meter unless --purge is confirmed.
set -euo pipefail

PREFIX="${PREFIX:-/opt/server-meter}"
CONFIG_DIR="${CONFIG_DIR:-/etc/server-meter}"
SERVICE_USER="${SERVICE_USER:-server-meter}"
PURGE=0
YES=0

usage() {
  cat <<EOF
This will remove server-meter.

Usage: sudo $0 [--yes] [--purge]

Without --purge the configuration at ${CONFIG_DIR} is kept.
--purge also deletes ${CONFIG_DIR} and the ${SERVICE_USER} system user.
EOF
}

for arg in "$@"; do
  case "${arg}" in
    --purge) PURGE=1 ;;
    --yes|-y) YES=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: ${arg}" >&2; usage; exit 1 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: uninstall.sh must be run with sudo." >&2
  exit 1
fi

if [[ "${YES}" -ne 1 ]]; then
  echo "This will remove server-meter."
  if [[ "${PURGE}" -eq 1 ]]; then
    echo "WARNING: --purge will delete ${CONFIG_DIR} (including the password)."
  else
    echo "Configuration at ${CONFIG_DIR} will be kept."
  fi
  printf "Type yes to continue: "
  read -r answer
  if [[ "${answer}" != "yes" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

systemctl stop server-meter.service 2>/dev/null || true
systemctl disable server-meter.service 2>/dev/null || true
systemctl disable server-meter-install-resume.service 2>/dev/null || true
rm -f /etc/systemd/system/server-meter.service
rm -f /etc/systemd/system/server-meter-install-resume.service
systemctl daemon-reload

rm -rf "${PREFIX}"
rm -f /var/lib/server-meter/install-resume

if [[ "${PURGE}" -eq 1 ]]; then
  rm -rf "${CONFIG_DIR}"
  rm -rf /var/lib/server-meter
  rm -f /etc/modules-load.d/server-meter-i2c.conf
  rm -f /etc/udev/rules.d/60-server-meter-i2c.rules
  rm -f /etc/systemd/journald.conf.d/server-meter-volatile.conf
  if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    deluser --system "${SERVICE_USER}" 2>/dev/null || userdel "${SERVICE_USER}" 2>/dev/null || true
  fi
  echo "Purged ${CONFIG_DIR} and user ${SERVICE_USER}."
else
  echo "Left ${CONFIG_DIR} in place. Use --purge to delete config and the service user."
fi

echo "Uninstalled. No sensor history existed on disk."
