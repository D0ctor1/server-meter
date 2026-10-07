#!/usr/bin/env bash
# Install check_server_meter.sh and Nagios object configuration.
# Does not install extra interpreters. Plugin config stays inside the .sh.
# Idempotent: one plugin file, one object file, no _2 / _new copies.
set -euo pipefail

# === installer configuration (edit if your Nagios paths differ) ===
PLUGIN_NAME="check_server_meter.sh"
PLUGIN_USER="${PLUGIN_USER:-nagios}"
PLUGIN_GROUP="${PLUGIN_GROUP:-nagios}"
PLUGIN_DIR="${PLUGIN_DIR:-}"
NAGIOS_BIN="${NAGIOS_BIN:-}"
NAGIOS_CFG="${NAGIOS_CFG:-}"
NAGIOS_OBJECTS_DIR="${NAGIOS_OBJECTS_DIR:-}"
NAGIOS_HOST_NAME="${NAGIOS_HOST_NAME:-server-meter}"
NAGIOS_HOST_ADDRESS="${NAGIOS_HOST_ADDRESS:-}"
INCLUDE_HOST="${INCLUDE_HOST:-auto}"
NAGIOS_RELOAD="${NAGIOS_RELOAD:-1}"
NAGIOS_SERVICE="${NAGIOS_SERVICE:-}"
INSTALL_OBJECTS="${INSTALL_OBJECTS:-1}"
SKIP_ROOT_CHECK="${SKIP_ROOT_CHECK:-0}"
# === end installer configuration ===

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC_DIR}/${PLUGIN_NAME}"
OBJECT_SRC="${SRC_DIR}/nagios/server-meter.cfg"

if [[ "${SKIP_ROOT_CHECK}" != "1" && "${EUID}" -ne 0 ]]; then
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

detect_plugin_dir() {
  if [[ -n "$PLUGIN_DIR" ]]; then
    return 0
  fi
  if [[ -d /usr/local/nagios/libexec ]]; then
    PLUGIN_DIR=/usr/local/nagios/libexec
  elif [[ -d /usr/lib/nagios/plugins ]]; then
    PLUGIN_DIR=/usr/lib/nagios/plugins
  else
    PLUGIN_DIR=/usr/local/nagios/libexec
  fi
}

detect_nagios_bin() {
  if [[ -n "$NAGIOS_BIN" ]]; then
    return 0
  fi
  if [[ -x /usr/local/nagios/bin/nagios ]]; then
    NAGIOS_BIN=/usr/local/nagios/bin/nagios
  elif command -v nagios >/dev/null 2>&1; then
    NAGIOS_BIN="$(command -v nagios)"
  elif command -v nagios4 >/dev/null 2>&1; then
    NAGIOS_BIN="$(command -v nagios4)"
  elif [[ -x /usr/sbin/nagios4 ]]; then
    NAGIOS_BIN=/usr/sbin/nagios4
  elif [[ -x /usr/sbin/nagios ]]; then
    NAGIOS_BIN=/usr/sbin/nagios
  else
    NAGIOS_BIN=""
  fi
}

detect_nagios_cfg() {
  if [[ -n "$NAGIOS_CFG" ]]; then
    return 0
  fi
  if [[ -f /usr/local/nagios/etc/nagios.cfg ]]; then
    NAGIOS_CFG=/usr/local/nagios/etc/nagios.cfg
  elif [[ -f /etc/nagios4/nagios.cfg ]]; then
    NAGIOS_CFG=/etc/nagios4/nagios.cfg
  elif [[ -f /etc/nagios/nagios.cfg ]]; then
    NAGIOS_CFG=/etc/nagios/nagios.cfg
  else
    NAGIOS_CFG=""
  fi
}

detect_objects_dir() {
  if [[ -n "$NAGIOS_OBJECTS_DIR" ]]; then
    return 0
  fi
  if [[ -d /usr/local/nagios/etc/objects ]]; then
    NAGIOS_OBJECTS_DIR=/usr/local/nagios/etc/objects
  elif [[ -d /etc/nagios4/conf.d ]]; then
    NAGIOS_OBJECTS_DIR=/etc/nagios4/conf.d
  elif [[ -d /etc/nagios/conf.d ]]; then
    NAGIOS_OBJECTS_DIR=/etc/nagios/conf.d
  elif [[ -n "$NAGIOS_CFG" ]]; then
    NAGIOS_OBJECTS_DIR="$(dirname "$NAGIOS_CFG")/objects"
  else
    NAGIOS_OBJECTS_DIR=""
  fi
}

host_already_defined() {
  local search_root="$1"
  local our_file="$2"
  [[ -n "$search_root" && -d "$search_root" ]] || return 1
  grep -R --include='*.cfg' -E "^[[:space:]]*host_name[[:space:]]+${NAGIOS_HOST_NAME}([[:space:]]|;|$)" "$search_root" 2>/dev/null \
    | grep -v ":${our_file}:" \
    | grep -v "/${our_file##*/}:" \
    | grep -q .
}

detect_plugin_dir
DEST="${PLUGIN_DIR}/${PLUGIN_NAME}"
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
  if ! chown "${PLUGIN_USER}:${PLUGIN_GROUP}" "$DEST" 2>/dev/null; then
    echo "WARNING: could not chown ${DEST} to ${PLUGIN_USER}:${PLUGIN_GROUP}."
  fi
else
  echo "WARNING: user/group ${PLUGIN_USER}:${PLUGIN_GROUP} not found; left $(stat -c '%U:%G %a' "$DEST" 2>/dev/null || echo the installed file)."
  echo "Set PLUGIN_USER/PLUGIN_GROUP and re-run, or chown the plugin to the Nagios daemon user."
fi

chmod 0700 "$DEST"

if [[ -z "$NAGIOS_HOST_ADDRESS" ]]; then
  NAGIOS_HOST_ADDRESS="$(sed -n 's/^SERVER_METER_URL="[^"]*:\/\/\([^:/]*\).*/\1/p' "$DEST" | head -n 1 || true)"
fi
if [[ -z "$NAGIOS_HOST_ADDRESS" ]]; then
  NAGIOS_HOST_ADDRESS="192.168.1.50"
fi

OBJECT_DEST=""
if [[ "$INSTALL_OBJECTS" == "1" ]]; then
  if [[ ! -f "$OBJECT_SRC" ]]; then
    echo "Missing Nagios object template: $OBJECT_SRC" >&2
    exit 1
  fi
  detect_nagios_cfg
  detect_objects_dir
  if [[ -z "$NAGIOS_OBJECTS_DIR" ]]; then
    echo "WARNING: could not detect Nagios objects directory. Plugin is installed; objects were skipped."
    echo "Set NAGIOS_OBJECTS_DIR and NAGIOS_CFG, then re-run."
  else
    mkdir -p "$NAGIOS_OBJECTS_DIR"
    OBJECT_DEST="${NAGIOS_OBJECTS_DIR}/server-meter.cfg"
    include_host="$INCLUDE_HOST"
    if [[ "$include_host" == "auto" ]]; then
      search_root="$(dirname "$NAGIOS_OBJECTS_DIR")"
      if host_already_defined "$search_root" "$OBJECT_DEST"; then
        include_host="0"
        echo "Existing host ${NAGIOS_HOST_NAME} found; not duplicating define host."
      else
        include_host="1"
      fi
    fi

    rendered="$(mktemp)"
    sed -e "s|__PLUGIN_PATH__|${DEST}|g" \
        -e "s|__HOST_NAME__|${NAGIOS_HOST_NAME}|g" \
        -e "s|__HOST_ADDRESS__|${NAGIOS_HOST_ADDRESS}|g" \
        "$OBJECT_SRC" > "$rendered"
    if [[ "$include_host" != "1" && "$include_host" != "true" && "$include_host" != "yes" ]]; then
      awk '
        /# __BEGIN_HOST__/ {skip=1; next}
        /# __END_HOST__/ {skip=0; next}
        skip {next}
        {print}
      ' "$rendered" > "${rendered}.out"
      mv "${rendered}.out" "$rendered"
    else
      sed -i '/# __BEGIN_HOST__/d;/# __END_HOST__/d' "$rendered"
    fi
    install -m 0644 "$rendered" "$OBJECT_DEST"
    rm -f "$rendered"
    echo "Installed Nagios objects: ${OBJECT_DEST}"

    if [[ -n "$NAGIOS_CFG" && -f "$NAGIOS_CFG" ]]; then
      already=0
      if grep -Eq "^[[:space:]]*cfg_file[[:space:]]*=[[:space:]]*${OBJECT_DEST}[[:space:]]*$" "$NAGIOS_CFG"; then
        already=1
      fi
      objects_parent="$NAGIOS_OBJECTS_DIR"
      if grep -Eq "^[[:space:]]*cfg_dir[[:space:]]*=[[:space:]]*${objects_parent}[[:space:]]*$" "$NAGIOS_CFG"; then
        already=1
      fi
      if [[ "$already" -eq 0 ]]; then
        {
          echo ""
          echo "# server-meter (added by install_nagios_plugin.sh)"
          echo "cfg_file=${OBJECT_DEST}"
        } >> "$NAGIOS_CFG"
        echo "Added cfg_file=${OBJECT_DEST} to ${NAGIOS_CFG}"
      fi
    fi
  fi
fi

validate_and_reload() {
  detect_nagios_bin
  detect_nagios_cfg
  if [[ -z "$NAGIOS_BIN" || -z "$NAGIOS_CFG" ]]; then
    echo "Nagios binary or nagios.cfg not found; skipped validation/reload."
    echo "Set NAGIOS_BIN and NAGIOS_CFG, then run: \$NAGIOS_BIN -v \$NAGIOS_CFG"
    return 0
  fi
  echo "Validating: ${NAGIOS_BIN} -v ${NAGIOS_CFG}"
  set +e
  "${NAGIOS_BIN}" -v "${NAGIOS_CFG}"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    echo "Nagios configuration is invalid. Reload was NOT performed." >&2
    return "$rc"
  fi
  if [[ "$NAGIOS_RELOAD" != "1" && "$NAGIOS_RELOAD" != "true" ]]; then
    echo "Validation succeeded. Reload skipped (NAGIOS_RELOAD=${NAGIOS_RELOAD})."
    return 0
  fi
  if [[ -n "$NAGIOS_SERVICE" ]]; then
    systemctl reload "$NAGIOS_SERVICE"
    echo "Reloaded systemd unit ${NAGIOS_SERVICE}."
    return 0
  fi
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-unit-files --type=service 2>/dev/null | grep -q '^nagios\.service'; then
      systemctl reload nagios
      echo "Reloaded nagios."
      return 0
    fi
    if systemctl list-unit-files --type=service 2>/dev/null | grep -q '^nagios4\.service'; then
      systemctl reload nagios4
      echo "Reloaded nagios4."
      return 0
    fi
  fi
  echo "Validation succeeded. Reload the Nagios service yourself (systemctl reload nagios)."
}

if [[ "$INSTALL_OBJECTS" == "1" ]]; then
  validate_and_reload
fi

cat <<EOF
Installed ${DEST}
Mode 0700. This file contains SERVER_METER_PASSWORD — do not make it world-readable.

Edit URL, username, password and thresholds in the configuration block at the top of:
  ${DEST}

Then test:
  ${DEST} --help
  ${DEST}
  ${DEST} temperature
  echo \$?

Nagios command:
  define command {
      command_name  check_server_meter
      command_line  ${DEST} \$ARG1\$
  }

This installer does not install Python. It updates this plugin and the
server-meter.cfg object file only (adds cfg_file= to nagios.cfg when missing).
EOF
