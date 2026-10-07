#!/usr/bin/env bash
# I²C is enabled by the root install.sh. This wrapper remains for compatibility.
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: enable_i2c.sh must be run with sudo." >&2
  exit 1
fi
echo "I2C is configured automatically by sudo ./install.sh"
echo "Re-run: sudo $(cd "$(dirname "$0")/.." && pwd)/install.sh"
exit 0
