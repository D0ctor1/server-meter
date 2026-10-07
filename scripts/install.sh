#!/usr/bin/env bash
# Install server-meter onto Ubuntu Server (Raspberry Pi 5 / ARM64).
# Does not download Bosch BSEC (proprietary). See docs/bme690-bsec.md.
set -euo pipefail

PREFIX="${PREFIX:-/opt/server-meter}"
CONFIG_DIR="${CONFIG_DIR:-/etc/server-meter}"
SERVICE_USER="${SERVICE_USER:-server-meter}"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  python3 \
  python3-venv \
  python3-dev \
  python3-pip \
  build-essential \
  i2c-tools \
  adduser

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  adduser --system --group --home "${PREFIX}" --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

if getent group i2c >/dev/null 2>&1; then
  usermod -aG i2c "${SERVICE_USER}" || true
fi

mkdir -p "${PREFIX}" "${CONFIG_DIR}"
# Copy application files. History is never stored here.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'config/config.yaml' \
    "${SRC_DIR}/" "${PREFIX}/"
else
  cp -a "${SRC_DIR}/." "${PREFIX}/"
  rm -rf "${PREFIX}/.git" "${PREFIX}/venv" "${PREFIX}/.venv"
fi

python3 -m venv "${PREFIX}/venv"
"${PREFIX}/venv/bin/pip" install --upgrade pip
"${PREFIX}/venv/bin/pip" install -r "${PREFIX}/requirements.txt"

if [[ ! -f "${CONFIG_DIR}/config.yaml" ]]; then
  cp "${PREFIX}/config/config.example.yaml" "${CONFIG_DIR}/config.yaml"
  echo "Wrote ${CONFIG_DIR}/config.yaml — set web.auth.password before starting."
fi
chmod 640 "${CONFIG_DIR}/config.yaml"
chown "root:${SERVICE_USER}" "${CONFIG_DIR}/config.yaml"

install -m 0644 "${PREFIX}/systemd/server-meter.service" /etc/systemd/system/server-meter.service
systemctl daemon-reload
systemctl enable server-meter.service

echo
echo "Installed server-meter to ${PREFIX}"
echo "1. Edit ${CONFIG_DIR}/config.yaml (password, I2C address 0x76/0x77)."
echo "2. Optional: install Bosch BSEC 3.2+ — docs/bme690-bsec.md"
echo "3. Enable I2C: ${PREFIX}/scripts/enable_i2c.sh && sudo i2cdetect -y 1"
echo "4. Start: sudo systemctl start server-meter"
echo "5. Open http://<pi-ip>:8080"
echo
echo "Sensor history is RAM-only. After reboot the graphs start empty."
