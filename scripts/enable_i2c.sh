#!/usr/bin/env bash
# Enable I²C on Ubuntu Server for Raspberry Pi 5.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_i2c 0 || true
fi

BOOT_CFG=""
for candidate in /boot/firmware/config.txt /boot/config.txt; do
  if [[ -f "${candidate}" ]]; then
    BOOT_CFG="${candidate}"
    break
  fi
done

if [[ -n "${BOOT_CFG}" ]] && ! grep -qE '^dtparam=i2c_arm=on' "${BOOT_CFG}"; then
  printf '\n# server-meter\ndtparam=i2c_arm=on\n' >> "${BOOT_CFG}"
  echo "Enabled dtparam=i2c_arm=on in ${BOOT_CFG} (reboot required)."
fi

if [[ -d /etc/modules-load.d ]] && [[ ! -f /etc/modules-load.d/server-meter-i2c.conf ]]; then
  printf 'i2c-dev\n' > /etc/modules-load.d/server-meter-i2c.conf
fi
modprobe i2c-dev 2>/dev/null || true

if ! getent group i2c >/dev/null 2>&1; then
  groupadd --system i2c || true
fi

if [[ -e /dev/i2c-1 ]]; then
  echo "I2C device present: /dev/i2c-1"
  echo "Scan with: i2cdetect -y 1"
else
  echo "I2C device not present yet. Reboot after enabling dtparam=i2c_arm=on."
fi
