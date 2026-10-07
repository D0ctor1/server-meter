#!/bin/sh
# Nagios Core plugin for server-meter.
# Self-contained: edit the configuration block below, then run with no arguments.
# Requires: curl, sed, awk, grep, cut, printf.
# Exit: 0=OK 1=WARNING 2=CRITICAL 3=UNKNOWN
#
# This file holds the HTTP password. Install it mode 0700 owned by the Nagios
# plugin user (typically nagios:nagios). Never enable shell tracing.

# === server-meter plugin configuration ===
SERVER_METER_URL="http://192.168.1.50:8080"
SERVER_METER_USERNAME="admin"
SERVER_METER_PASSWORD="CHANGE_ME"
CONNECT_TIMEOUT=5
REQUEST_TIMEOUT=10
CURL_INSECURE=false
# === end configuration ===

STATE_OK=0
STATE_WARNING=1
STATE_CRITICAL=2
STATE_UNKNOWN=3

finish() {
  code=$1
  shift
  printf '%s\n' "$*"
  exit "$code"
}

sanitize() {
  awk -v p="$SERVER_METER_PASSWORD" '
    p == "" { print; next }
    {
      s = $0
      while ((i = index(s, p)) > 0) {
        s = substr(s, 1, i - 1) "***" substr(s, i + length(p))
      }
      print s
    }
  '
}

usage() {
  cat <<'EOF'
Usage:
  check_server_meter.sh
  check_server_meter.sh -h|--help

Edit the configuration block at the top of this script, then run it with no
arguments. Nagios should execute the script as-is.

Configuration:
  SERVER_METER_URL
  SERVER_METER_USERNAME
  SERVER_METER_PASSWORD
  CONNECT_TIMEOUT
  REQUEST_TIMEOUT
  CURL_INSECURE

Nagios exit codes:
  0 OK
  1 WARNING
  2 CRITICAL
  3 UNKNOWN

This file contains the HTTP password. Keep mode 0700 (nagios:nagios).
The plugin never prints the password, performance data, or curl errors.
EOF
}

json_string() {
  printf '%s' "$1" | tr '\n' ' ' | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | sed -n '1p'
}

json_number() {
  printf '%s' "$1" | tr '\n' ' ' | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\(-\{0,1\}[0-9][0-9.]*\).*/\1/p' | sed -n '1p'
}

json_bool() {
  printf '%s' "$1" | tr '\n' ' ' | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\(true\|false\|null\).*/\1/p' | sed -n '1p'
}

is_number() {
  printf '%s' "$1" | grep -Eq '^-?[0-9]+([.][0-9]+)?$'
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit "$STATE_UNKNOWN"
fi

if [ "$#" -ne 0 ]; then
  finish "$STATE_UNKNOWN" "UNKNOWN - this plugin takes no arguments; edit SERVER_METER_URL in the script. See --help."
fi

if [ -z "$SERVER_METER_URL" ]; then
  finish "$STATE_UNKNOWN" "UNKNOWN - SERVER_METER_URL is empty"
fi

if [ "$SERVER_METER_PASSWORD" = "CHANGE_ME" ] || [ -z "$SERVER_METER_PASSWORD" ]; then
  finish "$STATE_UNKNOWN" "UNKNOWN - set SERVER_METER_PASSWORD in check_server_meter.sh"
fi

if ! command -v curl >/dev/null 2>&1; then
  finish "$STATE_UNKNOWN" "UNKNOWN - curl is not installed on the Nagios host"
fi

url=$SERVER_METER_URL
url=${url%/}
case "$url" in
  */api/monitoring) ;;
  *) url="$url/api/monitoring" ;;
esac

insecure_args=""
if [ "$CURL_INSECURE" = "true" ] || [ "$CURL_INSECURE" = "True" ] || [ "$CURL_INSECURE" = "1" ]; then
  insecure_args="--insecure"
fi

set +e
# shellcheck disable=SC2086
raw=$(curl \
  --silent \
  --show-error \
  --connect-timeout "$CONNECT_TIMEOUT" \
  --max-time "$REQUEST_TIMEOUT" \
  --user "$SERVER_METER_USERNAME:$SERVER_METER_PASSWORD" \
  $insecure_args \
  --header "Accept: application/json" \
  --write-out "\n%{http_code}" \
  "$url" 2>&1)
curl_rc=$?
set -e

safe=$(printf '%s\n' "$raw" | sanitize)
http_code=$(printf '%s\n' "$safe" | sed -n '$p')
body=$(printf '%s\n' "$safe" | sed '$d')

if [ "$curl_rc" -ne 0 ]; then
  reason="connection failed"
  case "$safe" in
    *timed\ out*|*Timeout*|*timeout*) reason="connection timeout" ;;
    *Could\ not\ resolve*|*resolve\ host*) reason="dns failure" ;;
    *SSL*|*certificate*) reason="tls error" ;;
    *Connection\ refused*) reason="connection refused" ;;
  esac
  finish "$STATE_CRITICAL" "CRITICAL - server-meter unreachable: $reason"
fi

if ! printf '%s' "$http_code" | grep -Eq '^[0-9]{3}$'; then
  finish "$STATE_CRITICAL" "CRITICAL - server-meter unreachable"
fi

if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
  finish "$STATE_CRITICAL" "CRITICAL - HTTP $http_code authenticating to server-meter"
fi

if [ "$http_code" != "200" ]; then
  finish "$STATE_CRITICAL" "CRITICAL - HTTP $http_code contacting server-meter"
fi

case "$body" in
  *"{"*) ;;
  *) finish "$STATE_UNKNOWN" "UNKNOWN - server-meter returned invalid monitoring data" ;;
esac

overall=$(json_string "$body" "overall")
overall=$(printf '%s' "$overall" | tr '[:lower:]' '[:upper:]')

case "$overall" in
  OK) code=$STATE_OK ;;
  WARNING) code=$STATE_WARNING ;;
  CRITICAL) code=$STATE_CRITICAL ;;
  UNKNOWN) code=$STATE_UNKNOWN ;;
  *) finish "$STATE_UNKNOWN" "UNKNOWN - server-meter returned invalid monitoring data" ;;
esac

TEXT=""
PERF=""

add_item() {
  label=$1
  value=$2
  unit=$3
  warn=$4
  crit=$5
  text_name=$6
  if [ -z "$value" ] || [ "$value" = "null" ]; then
    return 0
  fi
  if ! is_number "$value"; then
    return 0
  fi
  if [ -n "$TEXT" ]; then
    TEXT="$TEXT "
  fi
  TEXT="$TEXT$text_name=$value$unit"
  warn_s=""
  crit_s=""
  if is_number "$warn"; then
    warn_s=$warn
  fi
  if is_number "$crit"; then
    crit_s=$crit
  fi
  if [ -n "$PERF" ]; then
    PERF="$PERF "
  fi
  PERF="$PERF$label=$value;$warn_s;$crit_s"
}

add_item temperature "$(json_number "$body" temperature_c)" "C" "$(json_number "$body" temperature_warning)" "$(json_number "$body" temperature_critical)" temperature
add_item humidity "$(json_number "$body" humidity_percent)" "%" "$(json_number "$body" humidity_warning)" "$(json_number "$body" humidity_critical)" humidity
add_item pressure "$(json_number "$body" pressure_hpa)" "hPa" "" "" pressure
add_item gas_resistance "$(json_number "$body" gas_resistance_ohm)" "Ohm" "" "" gas_resistance
add_item iaq "$(json_number "$body" iaq)" "" "$(json_number "$body" iaq_warning)" "$(json_number "$body" iaq_critical)" IAQ
add_item iaq_accuracy "$(json_number "$body" iaq_accuracy)" "" "" "" iaq_accuracy
add_item static_iaq "$(json_number "$body" static_iaq)" "" "" "" static_iaq
add_item static_iaq_accuracy "$(json_number "$body" static_iaq_accuracy)" "" "" "" static_iaq_accuracy
add_item eco2 "$(json_number "$body" eco2_ppm)" "ppm" "$(json_number "$body" eco2_warning)" "$(json_number "$body" eco2_critical)" eco2
add_item bvoc "$(json_number "$body" bvoc_ppm)" "ppm" "$(json_number "$body" bvoc_warning)" "$(json_number "$body" bvoc_critical)" bvoc
add_item cpu_temp "$(json_number "$body" cpu_temperature_c)" "C" "$(json_number "$body" cpu_temperature_warning)" "$(json_number "$body" cpu_temperature_critical)" cpu_temp
add_item cpu_load "$(json_number "$body" cpu_load_percent)" "%" "" "" cpu_load
add_item ram "$(json_number "$body" ram_used_percent)" "%" "$(json_number "$body" ram_warning)" "$(json_number "$body" ram_critical)" ram
add_item sensor_age "$(json_number "$body" sensor_age_seconds)" "s" "$(json_number "$body" sensor_age_warning)" "$(json_number "$body" sensor_age_critical)" sensor_age

available=$(json_bool "$body" sensor_available)
prefix="server-meter reachable"
if [ "$overall" != "OK" ]; then
  prefix="server-meter"
fi
if [ "$available" = "false" ]; then
  prefix="server-meter sensor unavailable"
fi
if [ -z "$TEXT" ]; then
  TEXT="no sample"
fi

if [ -n "$PERF" ]; then
  finish "$code" "$overall - $prefix, $TEXT | $PERF"
fi
finish "$code" "$overall - $prefix, $TEXT"
