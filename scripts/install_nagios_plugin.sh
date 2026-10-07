#!/usr/bin/env bash
# Install check_server_meter.sh onto a Nagios Core host.
# Does not install extra interpreters or extra config files.
# Does not modify nagios.cfg or the Nagios Python environment.
# Idempotent: updates only this plugin and preserves the configuration block.
set -euo pipefail

# === installer configuration (edit if your Nagios paths differ) ===
PLUGIN_DIR="${PLUGIN_DIR:-/usr/lib/nagios/plugins}"
PLUGIN_NAME="check_server_meter.sh"
PLUGIN_USER="${PLUGIN_USER:-nagios}"
PLUGIN_GROUP="${PLUGIN_GROUP:-nagios}"
# === end installer configuration ===

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC_DIR}/${PLUGIN_NAME}"
DEST="${PLUGIN_DIR}/${PLUGIN_NAME}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -f "$SRC" ]]; then
  echo "Missing plugin source: $SRC" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required. Install curl, then re-run." >&2
  exit 1
fi

mkdir -p "$PLUGIN_DIR"

staging="$(mktemp)"
trap 'rm -f "$staging"' EXIT

if [[ -f "$DEST" ]] && grep -q '^# === server-meter plugin configuration ===' "$DEST"; then
  {
    sed '/^# === server-meter plugin configuration ===/,$d' "$SRC"
    awk '/^# === server-meter plugin configuration ===/,/^# === end configuration ===/' "$DEST"
    sed '1,/^# === end configuration ===/d' "$SRC"
  } > "$staging"
else
  cp "$SRC" "$staging"
fi

install -m 0700 "$staging" "$DEST"

if getent passwd "$PLUGIN_USER" >/dev/null 2>&1 && getent group "$PLUGIN_GROUP" >/dev/null 2>&1; then
  chown "${PLUGIN_USER}:${PLUGIN_GROUP}" "$DEST"
else
  echo "WARNING: user/group ${PLUGIN_USER}:${PLUGIN_GROUP} not found; left $(stat -c '%U:%G %a' "$DEST" 2>/dev/null || echo the installed file)."
  echo "Set PLUGIN_USER/PLUGIN_GROUP and re-run, or chown the plugin to the Nagios daemon user."
fi

chmod 0700 "$DEST"

cat <<EOF
Installed ${DEST}
Mode 0700. This file contains SERVER_METER_PASSWORD — do not make it world-readable.

Edit URL, username and password in the configuration block at the top of:
  ${DEST}

Then test (no arguments):
  ${DEST}
  echo \$?

Nagios command:
  define command {
      command_name  check_server_meter
      command_line  ${DEST}
  }

This installer does not change nagios.cfg or Python.
EOF
