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
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESUME=0
SKIP_UPGRADE=0
BME690_CHIP_ID="0x61"
DETECTED_BUS=""
DETECTED_ADDR=""
BSEC_LIB=""
BSEC_CONFIG=""
BSEC_OK=0
INSTALL_YAML_CREDENTIALS_MATCH=0
INSTALL_FACTORY_PASSWORD_ACTIVE=0

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
  # /lib holds Bosch BSEC artifacts that are not in git. Excluding the whole
  # directory (and protecting it) prevents rsync --delete from trying to remove
  # a non-empty PREFIX/lib ("cannot delete non-empty directory: lib").
  # /venv is created separately and must not be wiped by the source tree copy.
  if ! rsync -a --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '/venv/' \
    --exclude '/lib/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude 'config/config.yaml' \
    --filter 'P /venv/' \
    --filter 'P /lib/' \
    "${SRC_DIR}/" "${PREFIX}/"
  then
    fail "Failed to copy application tree" \
      "rsync ${SRC_DIR}/ -> ${PREFIX}/ failed. Existing /etc/server-meter and ${STATE_DIR} were not modified."
  fi
}

venv_path_is_safe() {
  local venv_dir="$1"
  local prefix_real
  if [[ "${PREFIX}" != /* ]] || [[ -z "${PREFIX}" ]]; then
    return 1
  fi
  if [[ "${venv_dir}" != "${PREFIX}/venv" ]]; then
    return 1
  fi
  case "${PREFIX}" in
    /|/usr|/usr/*|/lib|/lib/*|/lib64|/lib64/*|/bin|/bin/*|/sbin|/sbin/*|/etc|/etc/*|/var|/var/*|/root|/root/*|/home|/opt)
      return 1
      ;;
  esac
  prefix_real="$(readlink -f "${PREFIX}" 2>/dev/null || printf '%s' "${PREFIX}")"
  case "${prefix_real}" in
    /|/usr|/usr/*|/lib|/lib/*|/lib64|/lib64/*|/bin|/bin/*|/sbin|/sbin/*|/etc|/etc/*|/var|/var/*|/root|/root/*|/home|/opt)
      return 1
      ;;
  esac
  if [[ -e "${venv_dir}" ]]; then
    local venv_real
    venv_real="$(readlink -f "${venv_dir}" 2>/dev/null || true)"
    if [[ -n "${venv_real}" && "${venv_real}" != "${prefix_real}/venv" ]]; then
      return 1
    fi
  fi
  return 0
}

venv_python_usable() {
  local venv_dir="$1"
  [[ -x "${venv_dir}/bin/python" ]] || return 1
  [[ -f "${venv_dir}/pyvenv.cfg" ]] || return 1
  "${venv_dir}/bin/python" -c "import sys" >/dev/null 2>&1 || return 1
  local current_py cfg_py
  current_py="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  cfg_py="$(awk -F' *= *' '/^version/ {print $2; exit}' "${venv_dir}/pyvenv.cfg" | cut -d. -f1,2)"
  [[ -n "${cfg_py}" && "${cfg_py}" == "${current_py}" ]]
}

ensure_venv() {
  local venv_dir="${PREFIX}/venv"
  if ! venv_path_is_safe "${venv_dir}"; then
    fail "Python environment" "refusing to create or remove a venv outside ${PREFIX}/venv."
  fi
  if venv_python_usable "${venv_dir}"; then
    if ! python3 -m venv --upgrade "${venv_dir}"; then
      fail "Python environment" "python3 -m venv --upgrade ${venv_dir} failed."
    fi
    return
  fi
  if [[ -e "${venv_dir}" ]]; then
    if ! venv_path_is_safe "${venv_dir}"; then
      fail "Python environment" "refusing to remove unexpected venv path."
    fi
    rm -rf "${venv_dir}"
  fi
  if ! python3 -m venv "${venv_dir}"; then
    fail "Python environment" "python3 -m venv ${venv_dir} failed."
  fi
}

setup_venv() {
  ensure_venv
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
  # Existing YAML is kept as-is (password, locale, bind address, SMTP, …).
  # Missing web.locale is not injected; the app defaults to CZ.
  # Legacy history.max_samples 10000/20000 is bumped to 2000000 only.
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
  install -m 0644 "${PREFIX}/systemd/server-meter-self-restart.service" \
    /etc/systemd/system/server-meter-self-restart.service
  install -m 0644 "${PREFIX}/systemd/server-meter-host-reboot.service" \
    /etc/systemd/system/server-meter-host-reboot.service
  mkdir -p /etc/polkit-1/rules.d
  install -m 0644 "${PREFIX}/systemd/50-server-meter.rules" \
    /etc/polkit-1/rules.d/50-server-meter.rules
  systemctl daemon-reload
  systemctl enable server-meter.service
  # Helper units are started on demand; never enable them for boot.
  systemctl reload polkit 2>/dev/null || systemctl try-reload-or-restart polkit 2>/dev/null || true
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
    if curl -fsS http://127.0.0.1:8080/api/health 2>/dev/null | grep -qE '"status":"(ok|healthy)"'; then
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

http_capture() {
  # $1 = URL, $2 = body file, remaining args are extra curl options.
  # Prints the HTTP status code. Never dumps Authorization headers.
  local url="$1"
  local body="$2"
  shift 2
  curl -sS -o "${body}" -w '%{http_code}' "$@" "${url}" || true
}

redact_api_body() {
  # Keep a short, secret-free snippet for diagnostics.
  local body="$1"
  python3 - "${body}" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")[:400]
for needle in ("authorization:", "password:", "passwd=", "argon2", "bearer "):
    if needle in text.lower():
        text = "[redacted]"
        break
print(text.replace("\r", " ").replace("\n", " "))
PY
}

probe_auth_json() {
  PYTHONPATH="${PREFIX}" "$(python_bin)" "${PREFIX}/scripts/install_auth_probe.py" --config "${CONFIG_FILE}"
}

write_netrc() {
  local netrc="/run/server-meter-install.netrc"
  rm -f "${netrc}"
  "$(python_bin)" - "${CONFIG_FILE}" "${netrc}" <<'PY'
import sys
from pathlib import Path
import yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
auth = (cfg or {}).get("web", {}).get("auth") or {}
username = str(auth.get("username") or "")
password = str(auth.get("password") or "")
if not username or not password:
    raise SystemExit(2)
Path(sys.argv[2]).write_text(
    f"machine 127.0.0.1 login {username} password {password}\n"
    f"machine localhost login {username} password {password}\n",
    encoding="utf-8",
)
PY
  chmod 600 "${netrc}"
  printf '%s\n' "${netrc}"
}

fail_http() {
  local title="$1"
  local endpoint="$2"
  local status="$3"
  local body_file="$4"
  local extra="$5"
  local body_snip
  body_snip="$(redact_api_body "${body_file}" 2>/dev/null || printf '%s' '[unreadable]')"
  rm -f "${body_file}"
  fail "${title}" \
"Endpoint: ${endpoint}
HTTP status: ${status}
Authentication: ${extra}
Credentials are not printed.

$(service_diagnostics)

Response snippet: ${body_snip}"
}

test_api() {
  step 11 "Testing API"
  local health_body health_status probe
  health_body="$(mktemp /run/server-meter/api-health.XXXXXX)"
  health_status="$(http_capture http://127.0.0.1:8080/api/health "${health_body}")"
  if [[ "${health_status}" != "200" ]] || ! grep -qE '"status":"(ok|healthy)"' "${health_body}"; then
    fail_http "HTTP /api/health failed" "/api/health" "${health_status:-000}" "${health_body}" "not required (public liveness)"
  fi
  rm -f "${health_body}"

  if ! probe="$(probe_auth_json)"; then
    fail "User database check failed" \
"The service is up but the installer could not verify an administrator in SQLite.
${probe}

$(service_diagnostics)"
  fi
  local yaml_match admin_count factory
  yaml_match="$(printf '%s' "${probe}" | "$(python_bin)" -c 'import json,sys; print(json.load(sys.stdin).get("yaml_credentials_match"))')"
  admin_count="$(printf '%s' "${probe}" | "$(python_bin)" -c 'import json,sys; print(json.load(sys.stdin).get("enabled_admin_count"))')"
  factory="$(printf '%s' "${probe}" | "$(python_bin)" -c 'import json,sys; print(json.load(sys.stdin).get("factory_password_active"))')"
  INSTALL_FACTORY_PASSWORD_ACTIVE=0
  if [[ "${factory}" == "True" ]]; then
    INSTALL_FACTORY_PASSWORD_ACTIVE=1
  fi
  INSTALL_YAML_CREDENTIALS_MATCH=0
  if [[ "${yaml_match}" == "True" ]]; then
    INSTALL_YAML_CREDENTIALS_MATCH=1
  fi
  if [[ "${admin_count}" != "1" && "${admin_count}" != [1-9]* ]]; then
    fail "No enabled administrator" \
"SQLite user store has no enabled admin. Existing accounts were not rewritten.
$(service_diagnostics)"
  fi

  local unauth_body unauth_status
  unauth_body="$(mktemp /run/server-meter/api-unauth.XXXXXX)"
  local path
  for path in /api/current /api/history /api/nagios/check; do
    unauth_status="$(http_capture "http://127.0.0.1:8080${path}" "${unauth_body}")"
    if [[ "${unauth_status}" != "401" ]]; then
      fail_http "Protected API is not authenticating" "${path}" "${unauth_status:-000}" "${unauth_body}" "none (anonymous request)"
    fi
  done
  rm -f "${unauth_body}"

  if [[ "${INSTALL_YAML_CREDENTIALS_MATCH}" -ne 1 ]]; then
    # Reinstall with an existing SQLite admin whose password is no longer the
    # YAML seed. Do not invent credentials and do not treat 401 as success of
    # a credentialed call. Liveness + auth-required + admin-exists is enough.
    ok
    return
  fi

  local netrc current_body current_status nagios_hdr nagios_body hist_body hist_status
  netrc="$(write_netrc)"
  current_body="$(mktemp /run/server-meter/api-current.XXXXXX)"
  current_status="$(http_capture http://127.0.0.1:8080/api/current "${current_body}" --netrc-file "${netrc}")"
  nagios_hdr="$(mktemp /run/server-meter/api-nagios-h.XXXXXX)"
  nagios_body="$(mktemp /run/server-meter/api-nagios.XXXXXX)"
  curl -sS --netrc-file "${netrc}" -D "${nagios_hdr}" -o "${nagios_body}" http://127.0.0.1:8080/api/nagios/check >/dev/null || true
  hist_body="$(mktemp /run/server-meter/api-history.XXXXXX)"
  hist_status="$(http_capture http://127.0.0.1:8080/api/history "${hist_body}" --netrc-file "${netrc}")"
  rm -f "${netrc}"

  if [[ "${current_status}" != "200" ]] || ! grep -q '"timestamp"' "${current_body}"; then
    if [[ "${current_status}" == "401" || "${current_status}" == "403" ]]; then
      fail_http "HTTP /api/current authentication failed" "/api/current" "${current_status}" "${current_body}" "attempted (YAML seed matched SQLite; secret not shown)"
    fi
    fail_http "HTTP /api/current failed" "/api/current" "${current_status:-000}" "${current_body}" "attempted (secret not shown)"
  fi
  rm -f "${current_body}"
  if ! grep -qiE 'X-Nagios-Status:[[:space:]]*[0-3]' "${nagios_hdr}"; then
    local nagios_snip
    nagios_snip="$(redact_api_body "${nagios_hdr}") $(redact_api_body "${nagios_body}")"
    rm -f "${nagios_hdr}" "${nagios_body}" "${hist_body}"
    fail "HTTP /api/nagios/check failed" "Expected X-Nagios-Status header (0-3).
${nagios_snip}"
  fi
  rm -f "${nagios_hdr}" "${nagios_body}"
  if [[ "${hist_status}" != "200" ]] || ! grep -q '"source":"ram"' "${hist_body}" || ! grep -q '"persistent":false' "${hist_body}"; then
    fail_http "RAM history check failed" "/api/history" "${hist_status:-000}" "${hist_body}" "attempted (secret not shown)"
  fi
  rm -f "${hist_body}"
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
  if [[ "${INSTALL_YAML_CREDENTIALS_MATCH}" -ne 1 ]]; then
    ok
    return
  fi
  local netrc current_body current_status
  netrc="$(write_netrc)"
  current_body="$(mktemp /run/server-meter/api-sample.XXXXXX)"
  local i
  current_status=""
  for i in $(seq 1 20); do
    current_status="$(http_capture http://127.0.0.1:8080/api/current "${current_body}" --netrc-file "${netrc}")"
    if [[ "${current_status}" == "200" ]] && grep -q '"available":true' "${current_body}"; then
      break
    fi
    sleep 1
  done
  rm -f "${netrc}"
  if [[ "${current_status}" != "200" ]] || ! grep -q '"available":true' "${current_body}"; then
    fail_http "HTTP /api/current has no sample yet" "/api/current" "${current_status:-000}" "${current_body}" \
      "attempted (secret not shown). systemd is running but the first BME690 sample did not appear."
  fi
  rm -f "${current_body}"
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
EOF
  if [[ "${INSTALL_FACTORY_PASSWORD_ACTIVE}" -eq 1 ]]; then
    cat <<EOF

Username:
admin

Password:
CHANGE_ME

CHANGE THE PASSWORD BEFORE NORMAL OPERATION.
The YAML factory password still matches the SQLite administrator.
EOF
  else
    cat <<EOF

Existing administrator account was kept.
This installer did not change user passwords.
Log in with the password already set in Settings → Users.
YAML web.auth.password is only used to seed the first admin.
EOF
  fi
  cat <<EOF

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

if [[ "${INSTALL_SH_SOURCE_ONLY:-}" != "1" ]]; then
  main "$@"
fi
