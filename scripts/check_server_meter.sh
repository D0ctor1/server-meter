#!/usr/bin/env bash
# Nagios Core plugin for server-meter.
# Talks to GET /api/monitoring over HTTP. Does not import Python from
# server-meter and does not require Python 3 on the Nagios host.
# Exit: 0=OK 1=WARNING 2=CRITICAL 3=UNKNOWN
set -eu
set +o xtrace

STATE_OK=0
STATE_WARNING=1
STATE_CRITICAL=2
STATE_UNKNOWN=3

HOST=""
PORT="8080"
URL=""
USER=""
PASSWORD=""
CONFFILE=""
TIMEOUT="8"

usage() {
  cat <<'EOF'
Usage: check_server_meter.sh [-H host] [-p port] [-U url] [-u user] [-P password] [-f conffile] [-t timeout]
       check_server_meter.sh <HOST> <PORT>

Credentials should come from /etc/nagios/private/server-meter.conf (mode 640),
not from Nagios object files.
EOF
}

load_conf() {
  local file="$1"
  [ -r "$file" ] || return 0
  local key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    key="${line%%=*}"
    val="${line#*=}"
    key="$(printf '%s' "$key" | tr -d ' \t\r')"
    val="$(printf '%s' "$val" | tr -d '\r')"
    val="${val#\"}"
    val="${val%\"}"
    val="${val#\'}"
    val="${val%\'}"
    case "$key" in
      USER|USERNAME|user|username) USER="${USER:-$val}" ;;
      PASSWORD|password) PASSWORD="${PASSWORD:-$val}" ;;
      HOST|host) HOST="${HOST:-$val}" ;;
      PORT|port) PORT="${PORT:-$val}" ;;
      URL|url) URL="${URL:-$val}" ;;
      TIMEOUT|timeout) TIMEOUT="${TIMEOUT:-$val}" ;;
    esac
  done < "$file"
}

finish() {
  local code="$1"
  local text="$2"
  printf '%s\n' "$text"
  exit "$code"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit "$STATE_UNKNOWN"
fi

if [ "$#" -ge 1 ] && [ "${1#-}" = "$1" ]; then
  HOST="$1"
  shift
  if [ "$#" -ge 1 ] && [ "${1#-}" = "$1" ]; then
    PORT="$1"
    shift
  fi
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    -H) HOST="${2:-}"; shift 2 ;;
    -p) PORT="${2:-}"; shift 2 ;;
    -U) URL="${2:-}"; shift 2 ;;
    -u) USER="${2:-}"; shift 2 ;;
    -P) PASSWORD="${2:-}"; shift 2 ;;
    -f) CONFFILE="${2:-}"; shift 2 ;;
    -t) TIMEOUT="${2:-}"; shift 2 ;;
    --help|-h) usage; exit "$STATE_UNKNOWN" ;;
    *) finish "$STATE_UNKNOWN" "UNKNOWN - unexpected argument" ;;
  esac
done

if [ -z "$CONFFILE" ]; then
  for candidate in \
    /etc/nagios/private/server-meter.conf \
    /etc/nagios4/private/server-meter.conf \
    /usr/local/nagios/etc/private/server-meter.conf
  do
    if [ -r "$candidate" ]; then
      CONFFILE="$candidate"
      break
    fi
  done
fi
if [ -n "$CONFFILE" ]; then
  load_conf "$CONFFILE"
fi

if [ -z "$URL" ]; then
  if [ -z "$HOST" ]; then
    finish "$STATE_UNKNOWN" "UNKNOWN - host is required"
  fi
  URL="http://${HOST}:${PORT}/api/monitoring"
fi

if ! command -v curl >/dev/null 2>&1; then
  finish "$STATE_UNKNOWN" "UNKNOWN - curl is not installed on the Nagios host"
fi

AUTH_ARGS=()
if [ -n "$USER" ]; then
  AUTH_ARGS=(-u "${USER}:${PASSWORD}")
fi

BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT

set +e
HTTP_CODE="$(curl -sS -o "$BODY" -w '%{http_code}' --max-time "$TIMEOUT" \
  -H 'Accept: application/json' "${AUTH_ARGS[@]}" "$URL" 2>"${BODY}.err")"
CURL_RC=$?
set -e

if [ "$CURL_RC" -ne 0 ]; then
  finish "$STATE_CRITICAL" "CRITICAL - cannot reach server-meter"
fi
if [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "403" ]; then
  finish "$STATE_CRITICAL" "CRITICAL - HTTP ${HTTP_CODE} authenticating to server-meter"
fi
if [ "$HTTP_CODE" != "200" ]; then
  finish "$STATE_CRITICAL" "CRITICAL - HTTP ${HTTP_CODE} contacting server-meter"
fi

JSON="$(cat "$BODY")"

parse_with_python() {
  local py="$1"
  printf '%s' "$JSON" | "$py" - <<'PY'
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception:
    sys.stdout.write("PARSE_ERROR\n")
    sys.exit(3)

state = str(data.get("overall") or "UNKNOWN").upper()
if state not in ("OK", "WARNING", "CRITICAL", "UNKNOWN"):
    state = "UNKNOWN"
sensor = data.get("sensor") or {}
system = data.get("system") or {}
thresholds = data.get("thresholds") or {}

def fmt(value, digits):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if digits == 0:
        return str(int(round(number)))
    return ("%." + str(digits) + "f") % number

metrics = (
    ("temperature", sensor.get("temperature"), "C", 1, "temperature"),
    ("humidity", sensor.get("humidity"), "%", 1, "humidity"),
    ("pressure", sensor.get("pressure"), "hPa", 1, "pressure"),
    ("gas_resistance", sensor.get("gas_resistance"), "Ohm", 0, "gas_resistance"),
    ("iaq", sensor.get("iaq"), "", 1, "iaq"),
    ("eco2", sensor.get("eco2"), "ppm", 0, "eco2"),
    ("bvoc", sensor.get("bvoc"), "ppm", 3, "bvoc"),
    ("cpu_temp", system.get("cpu_temperature"), "C", 1, "cpu_temperature"),
    ("ram", system.get("ram_usage_percent"), "%", 1, "ram_usage"),
    ("sensor_age", sensor.get("age_seconds"), "s", 0, "sensor_unavailable"),
)
text = []
perf = []
for label, value, unit, digits, th_name in metrics:
    shown = fmt(value, digits)
    if shown is None:
        continue
    text.append("%s=%s%s" % (label, shown, unit))
    spec = thresholds.get(th_name) or {}
    warn = spec.get("warning_high")
    crit = spec.get("critical_high")
    warn_s = "" if warn is None else str(warn)
    crit_s = "" if crit is None else str(crit)
    perf.append("%s=%s;%s;%s" % (label, shown, warn_s, crit_s))
sys.stdout.write(state + "\n")
sys.stdout.write((" ".join(text) if text else "no sample") + "\n")
sys.stdout.write(" ".join(perf) + "\n")
PY
}

parse_with_jq() {
  printf '%s' "$JSON" | jq -r '
    (.overall // "UNKNOWN"),
    (
      [
        (if .sensor.temperature != null then "temperature=\(.sensor.temperature)C" else empty end),
        (if .sensor.humidity != null then "humidity=\(.sensor.humidity)%" else empty end),
        (if .sensor.pressure != null then "pressure=\(.sensor.pressure)hPa" else empty end),
        (if .sensor.gas_resistance != null then "gas_resistance=\(.sensor.gas_resistance)Ohm" else empty end),
        (if .sensor.iaq != null then "iaq=\(.sensor.iaq)" else empty end),
        (if .sensor.eco2 != null then "eco2=\(.sensor.eco2)ppm" else empty end),
        (if .sensor.bvoc != null then "bvoc=\(.sensor.bvoc)ppm" else empty end),
        (if .system.cpu_temperature != null then "cpu_temp=\(.system.cpu_temperature)C" else empty end),
        (if .system.ram_usage_percent != null then "ram=\(.system.ram_usage_percent)%" else empty end),
        (if .sensor.age_seconds != null then "sensor_age=\(.sensor.age_seconds)s" else empty end)
      ] | if length == 0 then "no sample" else join(" ") end
    ),
    (
      [
        (if .sensor.temperature != null then "temperature=\(.sensor.temperature);\(.thresholds.temperature.warning_high // "");\(.thresholds.temperature.critical_high // "")" else empty end),
        (if .sensor.humidity != null then "humidity=\(.sensor.humidity);\(.thresholds.humidity.warning_high // "");\(.thresholds.humidity.critical_high // "")" else empty end),
        (if .sensor.pressure != null then "pressure=\(.sensor.pressure);\(.thresholds.pressure.warning_high // "");\(.thresholds.pressure.critical_high // "")" else empty end),
        (if .sensor.gas_resistance != null then "gas_resistance=\(.sensor.gas_resistance);\(.thresholds.gas_resistance.warning_high // "");\(.thresholds.gas_resistance.critical_high // "")" else empty end),
        (if .sensor.iaq != null then "iaq=\(.sensor.iaq);\(.thresholds.iaq.warning_high // "");\(.thresholds.iaq.critical_high // "")" else empty end),
        (if .sensor.eco2 != null then "eco2=\(.sensor.eco2);\(.thresholds.eco2.warning_high // "");\(.thresholds.eco2.critical_high // "")" else empty end),
        (if .sensor.bvoc != null then "bvoc=\(.sensor.bvoc);\(.thresholds.bvoc.warning_high // "");\(.thresholds.bvoc.critical_high // "")" else empty end),
        (if .system.cpu_temperature != null then "cpu_temp=\(.system.cpu_temperature);\(.thresholds.cpu_temperature.warning_high // "");\(.thresholds.cpu_temperature.critical_high // "")" else empty end),
        (if .system.ram_usage_percent != null then "ram=\(.system.ram_usage_percent);\(.thresholds.ram_usage.warning_high // "");\(.thresholds.ram_usage.critical_high // "")" else empty end),
        (if .sensor.age_seconds != null then "sensor_age=\(.sensor.age_seconds);\(.thresholds.sensor_unavailable.warning_high // "");\(.thresholds.sensor_unavailable.critical_high // "")" else empty end)
      ] | join(" ")
    )
  '
}

PARSED=""
if command -v jq >/dev/null 2>&1; then
  PARSED="$(parse_with_jq || true)"
elif command -v python2 >/dev/null 2>&1; then
  PARSED="$(parse_with_python python2 || true)"
elif command -v python >/dev/null 2>&1; then
  PARSED="$(parse_with_python python || true)"
elif command -v python3 >/dev/null 2>&1; then
  PARSED="$(parse_with_python python3 || true)"
else
  finish "$STATE_UNKNOWN" "UNKNOWN - install jq or python2 to parse JSON (do not install Python 3 only for this plugin)"
fi

if [ -z "$PARSED" ] || [ "$(printf '%s\n' "$PARSED" | head -n1)" = "PARSE_ERROR" ]; then
  finish "$STATE_UNKNOWN" "UNKNOWN - invalid JSON from server-meter"
fi

STATE_WORD="$(printf '%s\n' "$PARSED" | sed -n '1p' | tr '[:lower:]' '[:upper:]')"
TEXT="$(printf '%s\n' "$PARSED" | sed -n '2p')"
PERF="$(printf '%s\n' "$PARSED" | sed -n '3p')"

case "$STATE_WORD" in
  OK) CODE="$STATE_OK" ;;
  WARNING) CODE="$STATE_WARNING" ;;
  CRITICAL) CODE="$STATE_CRITICAL" ;;
  UNKNOWN) CODE="$STATE_UNKNOWN" ;;
  *) CODE="$STATE_UNKNOWN"; STATE_WORD="UNKNOWN" ;;
esac

if [ -n "$PERF" ]; then
  finish "$CODE" "${STATE_WORD} - ${TEXT} | ${PERF}"
fi
finish "$CODE" "${STATE_WORD} - ${TEXT}"
