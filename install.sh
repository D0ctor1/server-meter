#!/usr/bin/env bash
# Unattended installer / upgrader for server-meter on Raspberry Pi 5 + Ubuntu Server 26.04 ARM64.
# Idempotent. Never writes BME690 history or BSEC state to the SD card.
set -euo pipefail

PREFIX="${PREFIX:-/opt/server-meter}"
CONFIG_DIR="${CONFIG_DIR:-/etc/server-meter}"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
SERVICE_USER="${SERVICE_USER:-server-meter}"
STATE_DIR="${STATE_DIR:-/var/lib/server-meter}"
RESUME_FLAG="${STATE_DIR}/install-resume"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
RESUME=0
SKIP_UPGRADE=0
BME690_CHIP_ID="0x61"
DETECTED_BUS=""
DETECTED_ADDR=""
BSEC_LIB=""
BSEC_CONFIG=""
BSEC_OK=0

if [[ "${1:-}" == "--resume" ]]; then
  RESUME=1
  SKIP_UPGRADE=1
  shift
fi
if [[ "${1:-}" == "--skip-upgrade" ]]; then
  SKIP_UPGRADE=1
  shift
fi

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE="${NEEDRESTART_MODE:-l}"

step() {
  printf '[%s/12] %-36s' "$1" "$2"
}

ok() {
  printf ' OK\n'
}

fail() {
  local title="$1"
  shift
  printf '\n'
  cat <<EOF
=================================================
ERROR: ${title}
=================================================

$*

The installation has been stopped.
=================================================
EOF
  exit 1
}

warn() {
  printf ' WARNING: %s\n' "$*"
}

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "install.sh must be run with sudo." "Run: sudo ./install.sh"
  fi
}

python_bin() {
  if [[ -x "${PREFIX}/venv/bin/python" ]]; then
    printf '%s\n' "${PREFIX}/venv/bin/python"
  else
    printf '%s\n' "python3"
  fi
}

primary_ip() {
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "${ip}" ]]; then
    ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)"
  fi
  printf '%s\n' "${ip:-127.0.0.1}"
}

check_os() {
  step 1 "Checking operating system"
  if [[ ! -f /etc/os-release ]]; then
    fail "server-meter supports Raspberry Pi 5 / ARM64 / Ubuntu Server only." \
      "Missing /etc/os-release."
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  local arch
  arch="$(uname -m)"
  if [[ "${ID:-}" != "ubuntu" ]]; then
    fail "server-meter supports Raspberry Pi 5 / ARM64 / Ubuntu Server only." \
      "Detected OS: ${ID:-unknown} ${VERSION_ID:-}"
  fi
  case "${VERSION_ID:-}" in
    26.04*) ;;
    *)
      fail "server-meter supports Raspberry Pi 5 / ARM64 / Ubuntu Server only." \
        "Detected Ubuntu ${VERSION_ID:-unknown}. Required: 26.04."
      ;;
  esac
  if [[ "${arch}" != "aarch64" ]]; then
    fail "server-meter supports Raspberry Pi 5 / ARM64 / Ubuntu Server only." \
      "Detected architecture: ${arch} (required: aarch64)."
  fi
  ok
}

check_pi() {
  step 2 "Checking Raspberry Pi"
  local model=""
  if [[ -r /proc/device-tree/model ]]; then
    model="$(tr -d '\0' < /proc/device-tree/model)"
  fi
  if [[ "${model}" == *"Raspberry Pi 5"* ]]; then
    ok
    return
  fi
  if [[ -z "${model}" ]]; then
    warn "Could not read /proc/device-tree/model; continuing on ARM64 Ubuntu."
    return
  fi
  fail "server-meter supports Raspberry Pi 5 / ARM64 / Ubuntu Server only." \
    "Detected board: ${model}"
}

apt_deps() {
  step 3 "Installing dependencies"
  apt-get update -qq
  if [[ "${SKIP_UPGRADE}" -eq 0 ]]; then
    apt-get upgrade -y -qq
  fi
  apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-dev \
    python3-pip \
    build-essential \
    i2c-tools \
    git \
    curl \
    adduser \
    rsync \
    ca-certificates \
    iproute2 \
    procps
  ok
}

ensure_user_and_dirs() {
  if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    adduser --system --group --home "${PREFIX}" --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
  fi
  if ! getent group i2c >/dev/null 2>&1; then
    groupadd --system i2c
  fi
  usermod -aG i2c "${SERVICE_USER}"
  mkdir -p "${PREFIX}" "${CONFIG_DIR}" "${STATE_DIR}" /run/server-meter \
    "${PREFIX}/lib"
  chmod 0750 /run/server-meter
  chown "${SERVICE_USER}:${SERVICE_USER}" /run/server-meter
  chmod 0755 "${PREFIX}"
  chown "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}"
  chmod 0750 "${STATE_DIR}"
  if [[ -f "${STATE_DIR}/users.db" ]]; then
    chown "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}/users.db"
    chmod 0600 "${STATE_DIR}/users.db"
  fi
  # Directory must be traversable by the service user (640 on the file is not enough).
  chown "root:${SERVICE_USER}" "${CONFIG_DIR}"
  chmod 0750 "${CONFIG_DIR}"
}

sync_tree() {
  if [[ "${SRC_DIR}" == "${PREFIX}" ]]; then
    return
  fi
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'config/config.yaml' \
    --exclude 'lib/libalgobsec.so' \
    --exclude 'lib/libalgobsec.a' \
    --exclude 'lib/bsec_iaq.config' \
    --exclude 'lib/*.zip' \
    "${SRC_DIR}/" "${PREFIX}/"
}

setup_venv() {
  python3 -m venv "${PREFIX}/venv"
  "${PREFIX}/venv/bin/pip" install --upgrade pip setuptools -q
  "${PREFIX}/venv/bin/pip" install -r "${PREFIX}/requirements.txt" -q
  # Install the local package into the venv so `python -m server_meter` works
  # under systemd even if cwd is not on sys.path (Python 3.14).
  "${PREFIX}/venv/bin/pip" install --no-deps --force-reinstall "${PREFIX}" -q
  chmod -R a+rX "${PREFIX}/server_meter" "${PREFIX}/web" "${PREFIX}/config" || true
  if ! PYTHONPATH="${PREFIX}" "${PREFIX}/venv/bin/python" -c "import server_meter, fastapi, uvicorn, yaml, argon2"; then
    fail "Python environment" "venv cannot import server-meter. Check pip output above."
  fi
}

enable_i2c() {
  step 4 "Enabling I2C"
  if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_i2c 0 >/dev/null 2>&1 || true
  fi
  local boot_cfg=""
  for candidate in /boot/firmware/config.txt /boot/config.txt; do
    if [[ -f "${candidate}" ]]; then
      boot_cfg="${candidate}"
      break
    fi
  done
  if [[ -z "${boot_cfg}" ]]; then
    fail "I2C" "Could not find /boot/firmware/config.txt (Ubuntu Raspberry Pi image)."
  fi
  if ! grep -qE '^dtparam=i2c_arm=on' "${boot_cfg}"; then
    printf '\n# server-meter\ndtparam=i2c_arm=on\n' >> "${boot_cfg}"
  fi
  mkdir -p /etc/modules-load.d
  printf 'i2c-dev\n' > /etc/modules-load.d/server-meter-i2c.conf
  modprobe i2c-dev 2>/dev/null || true
  mkdir -p /etc/udev/rules.d
  printf 'KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"\n' \
    > /etc/udev/rules.d/60-server-meter-i2c.rules
  udevadm control --reload-rules 2>/dev/null || true
  udevadm trigger --subsystem-match=i2c-dev 2>/dev/null || true
  if [[ -e /dev/i2c-1 ]] || [[ -e /dev/i2c-0 ]] || [[ -e /dev/i2c-2 ]]; then
    chgrp i2c /dev/i2c-* 2>/dev/null || true
    chmod 0660 /dev/i2c-* 2>/dev/null || true
    ok
    return
  fi
  if [[ "${RESUME}" -eq 1 ]]; then
    fail "I2C DEVICE MISSING" \
      "No /dev/i2c-* after reboot. Check Ubuntu Pi firmware and dtparam=i2c_arm=on in /boot/firmware/config.txt."
  fi
  schedule_reboot
}

schedule_reboot() {
  mkdir -p "${STATE_DIR}"
  printf '%s\n' "${PREFIX}/install.sh --resume" > "${RESUME_FLAG}"
  cat > /etc/systemd/system/server-meter-install-resume.service <<EOF
[Unit]
Description=Resume server-meter installation after I2C overlay
After=multi-user.target systemd-modules-load.service
ConditionPathExists=${RESUME_FLAG}

[Service]
Type=oneshot
ExecStart=${PREFIX}/install.sh --resume
RemainAfterExit=no
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable server-meter-install-resume.service
  ok
  cat <<EOF

=================================================
I2C overlay enabled. A reboot is required for /dev/i2c-1.
Installation will continue automatically after reboot.
Rebooting in 8 seconds…
=================================================
EOF
  sleep 8
  systemctl reboot
  exit 0
}

clear_resume() {
  rm -f "${RESUME_FLAG}"
  systemctl disable server-meter-install-resume.service >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/server-meter-install-resume.service
  systemctl daemon-reload >/dev/null 2>&1 || true
}

read_chip_id() {
  local bus="$1"
  local addr="$2"
  local chip
  chip="$(i2cget -y "${bus}" "${addr}" 0xD0 b 2>/dev/null || true)"
  if [[ -z "${chip}" ]]; then
    chip="$(i2cget -y -f "${bus}" "${addr}" 0xD0 b 2>/dev/null || true)"
  fi
  printf '%s\n' "${chip,,}"
}

detect_bme690() {
  step 5 "Detecting BME690"
  DETECTED_BUS=""
  DETECTED_ADDR=""
  local bus addr chip
  for bus in 1 0 2; do
    if [[ ! -e "/dev/i2c-${bus}" ]]; then
      continue
    fi
    for addr in 0x76 0x77; do
      chip="$(read_chip_id "${bus}" "${addr}")"
      if [[ "${chip}" == "0x61" ]]; then
        DETECTED_BUS="${bus}"
        DETECTED_ADDR="${addr}"
        break 2
      fi
    done
  done
  if [[ -z "${DETECTED_BUS}" || -z "${DETECTED_ADDR}" ]]; then
    local scan_json
    mkdir -p /run/server-meter
    scan_json="$("$(python_bin)" "${PREFIX}/scripts/probe_bme690.py" --scan --buses 1,0,2 2>/run/server-meter/probe-scan.err || true)"
    DETECTED_BUS="$(printf '%s' "${scan_json}" | "$(python_bin)" -c 'import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    d={}
hits=d.get("found") or []
print(hits[0]["bus"] if hits else "")')"
    DETECTED_ADDR="$(printf '%s' "${scan_json}" | "$(python_bin)" -c 'import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    d={}
hits=d.get("found") or []
print(hex(hits[0]["address"]) if hits else "")')"
  fi
  if [[ -z "${DETECTED_BUS}" || -z "${DETECTED_ADDR}" ]]; then
    fail "BME690 NOT DETECTED" \
"I2C bus: 1 (also scanned 0 and 2)
Expected addresses: 0x76 or 0x77
Expected chip ID: ${BME690_CHIP_ID}

Please verify:

RED    -> Raspberry Pi PIN 1  (3.3V)
BLACK  -> Raspberry Pi PIN 6  (GND)
BLUE   -> Raspberry Pi PIN 3  (GPIO2 / SDA)
YELLOW -> Raspberry Pi PIN 5  (GPIO3 / SCL)

Do not connect VCC to 5V (PIN 2 / PIN 4).
Then run: sudo ./install.sh"
  fi
  ok
}

is_aarch64_shared_object() {
  local path="$1"
  [[ -f "${path}" ]] || return 1
  python3 - "${path}" <<'PY'
import sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()[:20]
if data[:4] != b"\x7fELF" or len(data) < 20:
    raise SystemExit(1)
# e_machine little-endian uint16 at offset 18; EM_AARCH64 = 183
raise SystemExit(0 if int.from_bytes(data[18:20], "little") == 183 else 1)
PY
}

link_bsec_shared() {
  local archive="$1"
  local dest="$2"
  if [[ "${archive}" == *.so ]]; then
    cp -a "${archive}" "${dest}"
    return 0
  fi
  if gcc -shared -o "${dest}" \
      -Wl,--whole-archive "${archive}" -Wl,--no-whole-archive \
      -lm -lrt -lpthread 2>/run/server-meter/bsec-link.err; then
    return 0
  fi
  gcc -shared -o "${dest}" \
    -Wl,--whole-archive "${archive}" -Wl,--no-whole-archive \
    -lm -lrt -lpthread -Wl,-z,notext 2>/run/server-meter/bsec-link.err
}

install_local_bsec_so() {
  local candidate
  for candidate in \
    "${PREFIX}/lib/libalgobsec.so" \
    "${SRC_DIR}/lib/libalgobsec.so" \
    "/usr/local/lib/libalgobsec.so" \
    "/usr/lib/libalgobsec.so" \
    "/opt/bosch/bsec/libalgobsec.so" \
    "${SERVER_METER_BSEC_LIB:-}"
  do
    if [[ -n "${candidate}" && -f "${candidate}" ]] && is_aarch64_shared_object "${candidate}"; then
      mkdir -p "${PREFIX}/lib"
      if [[ "${candidate}" != "${PREFIX}/lib/libalgobsec.so" ]]; then
        cp -a "${candidate}" "${PREFIX}/lib/libalgobsec.so"
      fi
      BSEC_LIB="${PREFIX}/lib/libalgobsec.so"
      if [[ -f "${PREFIX}/lib/bsec_iaq.config" ]]; then
        BSEC_CONFIG="${PREFIX}/lib/bsec_iaq.config"
      fi
      return 0
    fi
  done
  return 1
}

download_official_bsec() {
  local work json archive kind config
  work="/run/server-meter/bsec"
  json="${work}/result.json"
  rm -rf "${work}"
  mkdir -p "${work}" "${PREFIX}/lib"
  local script="${PREFIX}/scripts/fetch_bsec.py"
  if [[ ! -f "${script}" ]]; then
    script="${SRC_DIR}/scripts/fetch_bsec.py"
  fi
  if ! python3 "${script}" --work-dir "${work}" --json-out "${json}" \
      >"${work}/fetch.log" 2>&1; then
    return 1
  fi
  archive="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("archive",""))' "${json}")"
  kind="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("archive_kind",""))' "${json}")"
  config="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("config",""))' "${json}")"
  if [[ -z "${archive}" || ! -f "${archive}" ]]; then
    return 1
  fi
  if [[ "${kind}" == "so" ]]; then
    cp -a "${archive}" "${PREFIX}/lib/libalgobsec.so"
  elif ! link_bsec_shared "${archive}" "${PREFIX}/lib/libalgobsec.so"; then
    return 1
  fi
  if ! is_aarch64_shared_object "${PREFIX}/lib/libalgobsec.so"; then
    rm -f "${PREFIX}/lib/libalgobsec.so"
    return 1
  fi
  chmod 644 "${PREFIX}/lib/libalgobsec.so"
  chown root:root "${PREFIX}/lib/libalgobsec.so"
  BSEC_LIB="${PREFIX}/lib/libalgobsec.so"
  if [[ -n "${config}" && -f "${config}" ]]; then
    cp -a "${config}" "${PREFIX}/lib/bsec_iaq.config"
    chmod 644 "${PREFIX}/lib/bsec_iaq.config"
    chown root:root "${PREFIX}/lib/bsec_iaq.config"
    BSEC_CONFIG="${PREFIX}/lib/bsec_iaq.config"
  fi
  rm -rf "${work}"
  return 0
}

find_bsec() {
  step 6 "Installing BME690/BSEC"
  mkdir -p "${PREFIX}/lib"
  if [[ "${SERVER_METER_BSEC_REFRESH:-}" != "1" ]] && install_local_bsec_so; then
    ok
    return
  fi
  if [[ "${SERVER_METER_SKIP_BSEC:-}" == "1" ]]; then
    ok
    return
  fi
  # Official Bosch ZIP from software-downloads.html. Proprietary license:
  # running install.sh downloads it for this machine (not redistributed in git).
  if download_official_bsec; then
    ok
    return
  fi
  install_local_bsec_so || true
  ok
}

write_config() {
  step 7 "Creating server-meter"
  ensure_user_and_dirs
  ok
  # Existing YAML is kept as-is (password, locale, bind address, …).
  # Missing web.locale is not injected; the app defaults to CZ.
  step 8 "Creating configuration"
  "$(python_bin)" "${PREFIX}/scripts/write_initial_config.py" \
    --example "${PREFIX}/config/config.example.yaml" \
    --dest "${CONFIG_FILE}" \
    --bus "${DETECTED_BUS}" \
    --address "${DETECTED_ADDR}" \
    --bsec-lib "${BSEC_LIB}" \
    --bsec-config "${BSEC_CONFIG}" >/run/server-meter/write-config.out
  chown "root:${SERVICE_USER}" "${CONFIG_DIR}"
  chmod 0750 "${CONFIG_DIR}"
  chmod 660 "${CONFIG_FILE}"
  chown "root:${SERVICE_USER}" "${CONFIG_FILE}"
  if ! su -s /bin/sh "${SERVICE_USER}" -c "test -r '${CONFIG_FILE}'"; then
    fail "Configuration not readable" \
      "${CONFIG_FILE} exists but user ${SERVICE_USER} cannot read it.
$(stat -c '%a %U %G %n' "${CONFIG_DIR}" "${CONFIG_FILE}" 2>/dev/null || true)"
  fi
  if ! su -s /bin/sh "${SERVICE_USER}" -c "test -w '${CONFIG_FILE}'"; then
    warn "Configuration is not writable by ${SERVICE_USER}; Settings UI cannot save SMTP (need 660)."
  fi
  ok
}

install_systemd_extras() {
  step 9 "Installing systemd"
  mkdir -p /etc/systemd/journald.conf.d
  if [[ -f "${PREFIX}/docs/journald-volatile.conf" ]]; then
    cp "${PREFIX}/docs/journald-volatile.conf" \
      /etc/systemd/journald.conf.d/server-meter-volatile.conf
  fi
  install -m 0644 "${PREFIX}/systemd/server-meter.service" \
    /etc/systemd/system/server-meter.service
  systemctl daemon-reload
  systemctl enable server-meter.service
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then
    local cidr
    for cidr in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
      if ! ufw status | grep -F "8080" | grep -q "${cidr}"; then
        ufw allow from "${cidr}" to any port 8080 proto tcp comment 'server-meter lan' >/dev/null
      fi
    done
  fi
  ok
}

service_diagnostics() {
  {
    echo "--- systemctl status ---"
    systemctl status server-meter.service --no-pager -l || true
    echo "--- journal ---"
    journalctl -u server-meter --no-pager -n 80 || true
    echo "--- listeners ---"
    ss -lntp 2>/dev/null | grep -E '8080|python' || echo "nothing on 8080"
    echo "--- config perms ---"
    stat -c '%a %U %G %n' "${CONFIG_DIR}" "${CONFIG_FILE}" 2>/dev/null || true
    if su -s /bin/sh "${SERVICE_USER}" -c "test -x '${CONFIG_DIR}' && test -r '${CONFIG_FILE}'"; then
      echo "readable by ${SERVICE_USER}"
    else
      echo "NOT readable by ${SERVICE_USER}"
    fi
    echo "--- preflight root ---"
    PYTHONPATH="${PREFIX}" "${PREFIX}/venv/bin/python" -c \
      "from server_meter.config import load_config; c=load_config('${CONFIG_FILE}'); print('config', c.web.host, c.web.port, c.sensor.driver)" \
      || true
    echo "--- preflight ${SERVICE_USER} ---"
    su -s /bin/sh "${SERVICE_USER}" -c \
      "PYTHONPATH='${PREFIX}' '${PREFIX}/venv/bin/python' -c \"from server_meter.config import load_config; c=load_config('${CONFIG_FILE}'); print('config', c.web.host, c.web.port, c.sensor.driver)\"" \
      || true
  } 2>&1
}

start_service() {
  step 10 "Starting service"
  systemctl reset-failed server-meter.service 2>/dev/null || true
  systemctl stop server-meter.service 2>/dev/null || true
  sleep 1
  if ! systemctl start server-meter.service; then
    fail "systemd failed to start server-meter" "$(service_diagnostics)"
  fi
  local i
  for i in $(seq 1 45); do
    if curl -fsS http://127.0.0.1:8080/api/health 2>/dev/null | grep -q '"status":"ok"'; then
      ok
      if [[ -f /etc/systemd/journald.conf.d/server-meter-volatile.conf ]]; then
        systemctl restart systemd-journald 2>/dev/null || true
      fi
      return
    fi
    sleep 1
  done
  fail "HTTP /api/health failed" "$(service_diagnostics)"
}

write_netrc() {
  local netrc="/run/server-meter-install.netrc"
  "$(python_bin)" - "${CONFIG_FILE}" "${netrc}" <<'PY'
import sys
from pathlib import Path
import yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
auth = cfg["web"]["auth"]
Path(sys.argv[2]).write_text(
    f"machine 127.0.0.1 login {auth['username']} password {auth['password']}\n"
    f"machine localhost login {auth['username']} password {auth['password']}\n",
    encoding="utf-8",
)
PY
  chmod 600 "${netrc}"
  printf '%s\n' "${netrc}"
}

test_api() {
  step 11 "Testing API"
  local netrc
  netrc="$(write_netrc)"
  local current nagios hist
  if ! curl -fsS http://127.0.0.1:8080/api/health 2>/dev/null | grep -q '"status":"ok"'; then
    rm -f "${netrc}"
    fail "HTTP /api/health failed" "$(service_diagnostics)"
  fi
  current="$(curl -sS --netrc-file "${netrc}" http://127.0.0.1:8080/api/current || true)"
  # ASGI/Uvicorn sends header names lowercase (x-nagios-status). HTTP is
  # case-insensitive; this grep must be too. Do not use curl -f: Nagios is
  # always HTTP 200, and a 5xx body is more useful than an empty capture.
  nagios="$(curl -sS --netrc-file "${netrc}" -D - http://127.0.0.1:8080/api/nagios/check || true)"
  hist="$(curl -sS --netrc-file "${netrc}" http://127.0.0.1:8080/api/history || true)"
  rm -f "${netrc}"
  if [[ "${current}" != *'"timestamp"'* ]]; then
    fail "HTTP /api/current failed" "Basic Auth or API error.
${current}"
  fi
  if ! printf '%s' "${nagios}" | grep -qiE 'X-Nagios-Status:[[:space:]]*[0-3]'; then
    fail "HTTP /api/nagios/check failed" "Expected X-Nagios-Status header (0-3).
${nagios}"
  fi
  if [[ "${hist}" != *'"source":"ram"'* ]] || [[ "${hist}" != *'"persistent":false'* ]]; then
    fail "RAM history check failed" "API must serve RAM-only history.
${hist}"
  fi
  ok
}

test_sensor() {
  step 12 "Testing sensor"
  local probe
  if ! probe="$("$(python_bin)" "${PREFIX}/scripts/probe_bme690.py" --bus "${DETECTED_BUS}" --address "${DETECTED_ADDR}")"; then
    fail "Sensor measurement failed" "${probe:-BME690 did not return a temperature sample.}"
  fi
  local temp bsec
  temp="$(printf '%s' "${probe}" | "$(python_bin)" -c 'import json,sys; print(json.load(sys.stdin).get("temperature"))')"
  bsec="$(printf '%s' "${probe}" | "$(python_bin)" -c 'import json,sys; print(json.load(sys.stdin).get("bsec_loaded"))')"
  if [[ "${temp}" == "None" || -z "${temp}" ]]; then
    fail "Sensor measurement failed" "Temperature sample was empty."
  fi
  if [[ "${bsec}" == "True" ]]; then
    BSEC_OK=1
  fi
  local netrc current
  netrc="$(write_netrc)"
  local i
  current=""
  for i in $(seq 1 20); do
    current="$(curl -fsS --netrc-file "${netrc}" http://127.0.0.1:8080/api/current || true)"
    if [[ "${current}" == *'"available":true'* ]]; then
      break
    fi
    sleep 1
  done
  rm -f "${netrc}"
  if [[ "${current}" != *'"available":true'* ]]; then
    fail "HTTP /api/current has no sample yet" \
      "systemd is running but the first BME690 sample did not appear."
  fi
  ok
}

print_success() {
  local ip
  ip="$(primary_ip)"
  local bsec_line="BSEC: not installed (Bosch license — see below)"
  if [[ "${BSEC_OK}" -eq 1 ]]; then
    bsec_line="BSEC: initialized"
  fi
  cat <<EOF

====================================================
SERVER-METER INSTALLATION COMPLETE
====================================================

Web:
http://${ip}:8080

Username:
admin

Password:
CHANGE_ME

CHANGE THE PASSWORD BEFORE NORMAL OPERATION.

Edit:
${CONFIG_FILE}

Then:
sudo systemctl restart server-meter

Nagios endpoint:
http://${ip}:8080/api/nagios/check

I2C: bus ${DETECTED_BUS} address ${DETECTED_ADDR} chip ${BME690_CHIP_ID}
${bsec_line}

Acceptance:
  Raspberry Pi / Ubuntu 26.04 / ARM64
  I2C enabled
  BME690 detected (chip ID ${BME690_CHIP_ID})
  Sensor measurement valid
  Configuration valid
  systemd active
  HTTP /api/health OK
  /api/current returns data
  Nagios endpoint OK
  RAM history active (persistent=false)
  no persistent sensor storage
====================================================
EOF
  if [[ "${BSEC_OK}" -eq 0 ]]; then
    if [[ -n "${BSEC_LIB}" && -f "${BSEC_LIB}" ]]; then
      cat <<EOF

====================================================
BSEC library is installed, but IAQ did not initialize
====================================================

${BSEC_LIB} is present. Temperature / humidity / pressure / gas work.
IAQ, eCO2 and bVOC stay empty until BSEC accepts the subscription.

  journalctl -u server-meter --no-pager -n 80 | grep -i bsec
====================================================
EOF
    else
      cat <<EOF

====================================================
BLOCKER: Bosch BSEC 3.x library is not present
====================================================

Bosch BSEC is proprietary. install.sh tried the official ZIP from
https://www.bosch-sensortec.com/en/software-tools/software-downloads.html
but could not install PiFour_Armv8 libalgobsec for this Pi.

IAQ, eCO2 and bVOC stay empty until BSEC is present. Retry:

  sudo ./install.sh

License:
https://www.bosch-sensortec.com/media/boschsensortec/downloads/software/bme688_development_software/2024_12/20241219_clickthrough_license_terms_bsec_bme680_bme688_bme690.pdf

Temperature, humidity, pressure and gas resistance already work.
====================================================
EOF
    fi
  fi
}

main() {
  need_root
  check_os
  check_pi
  apt_deps
  printf '      preparing %s and Python venv ...\n' "${PREFIX}"
  ensure_user_and_dirs
  sync_tree
  setup_venv
  enable_i2c
  detect_bme690
  find_bsec
  write_config
  install_systemd_extras
  start_service
  test_api
  test_sensor
  clear_resume
  print_success
}

main "$@"
