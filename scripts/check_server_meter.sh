#!/bin/sh
# Nagios Core plugin for server-meter.
# One script, many services: check_server_meter.sh [metric]
# No argument (or "health") is the overall health check.
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

# Nagios WARNING/CRITICAL for per-metric services. Not medical limits.
# Email Settings on the Pi are a separate SMTP path (hysteresis/duration).
TEMP_WARNING=45
TEMP_CRITICAL=50
HUMIDITY_WARNING=80
HUMIDITY_CRITICAL=90
IAQ_WARNING=150
IAQ_CRITICAL=250
ECO2_WARNING=1500
ECO2_CRITICAL=2500
BVOC_WARNING=1.0
BVOC_CRITICAL=2.0
CPU_TEMP_WARNING=70
CPU_TEMP_CRITICAL=80
CPU_LOAD_WARNING=85
CPU_LOAD_CRITICAL=95
RAM_WARNING=85
RAM_CRITICAL=95
SENSOR_AGE_WARNING=15
SENSOR_AGE_CRITICAL=30
IAQ_ACCURACY_WARNING=1
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
  check_server_meter.sh health
  check_server_meter.sh <metric>
  check_server_meter.sh -h|--help

Metrics:
  temperature
  humidity
  pressure
  gas_resistance
  iaq
  iaq_accuracy
  static_iaq
  static_iaq_accuracy
  eco2
  bvoc
  cpu_temperature
  cpu_load
  ram
  sensor
  health

No argument is the overall health check (backward compatible).

Edit SERVER_METER_URL / SERVER_METER_USERNAME / SERVER_METER_PASSWORD
in this script. Keep mode 0700. The plugin never prints the password.

Nagios exit codes:
  0 OK
  1 WARNING
  2 CRITICAL
  3 UNKNOWN
EOF
}

# First exact "key": value in the JSON object (flat keys first in /api/monitoring).
# Quoted-key match so iaq is not confused with iaq_accuracy or static_iaq.
json_string() {
  printf '%s' "$1" | tr '\n' ' ' | awk -v key="$2" '
    BEGIN { needle = "\"" key "\"" }
    {
      s = $0
      while ((i = index(s, needle)) > 0) {
        rest = substr(s, i + length(needle))
        if (match(rest, /^[[:space:]]*:[[:space:]]*"/)) {
          rest = substr(rest, RLENGTH + 1)
          if (match(rest, /^[^"]*/)) {
            print substr(rest, RSTART, RLENGTH)
            exit
          }
        }
        s = substr(s, i + 1)
      }
    }
  '
}

json_number() {
  printf '%s' "$1" | tr '\n' ' ' | awk -v key="$2" '
    BEGIN { needle = "\"" key "\"" }
    {
      s = $0
      while ((i = index(s, needle)) > 0) {
        rest = substr(s, i + length(needle))
        if (match(rest, /^[[:space:]]*:[[:space:]]*/)) {
          rest = substr(rest, RLENGTH + 1)
          if (match(rest, /^-?[0-9]+(\.[0-9]+)?/)) {
            print substr(rest, RSTART, RLENGTH)
            exit
          }
        }
        s = substr(s, i + 1)
      }
    }
  '
}

json_bool() {
  printf '%s' "$1" | tr '\n' ' ' | awk -v key="$2" '
    BEGIN { needle = "\"" key "\"" }
    {
      s = $0
      while ((i = index(s, needle)) > 0) {
        rest = substr(s, i + length(needle))
        if (match(rest, /^[[:space:]]*:[[:space:]]*/)) {
          rest = substr(rest, RLENGTH + 1)
          if (match(rest, /^(true|false|null)/)) {
            print substr(rest, RSTART, RLENGTH)
            exit
          }
        }
        s = substr(s, i + 1)
      }
    }
  '
}

is_number() {
  printf '%s' "$1" | grep -Eq '^-?[0-9]+([.][0-9]+)?$'
}

fmt() {
  awk -v v="$1" -v d="$2" 'BEGIN { printf("%.*f", d, v + 0) }'
}

ge() {
  awk -v a="$1" -v b="$2" 'BEGIN { exit (a + 0 >= b + 0) ? 0 : 1 }'
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit "$STATE_UNKNOWN"
fi

METRIC=${1:-health}
if [ "$#" -gt 1 ]; then
  finish "$STATE_UNKNOWN" "UNKNOWN - usage: check_server_meter.sh [metric]. See --help."
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
  *) finish "$STATE_UNKNOWN" "UNKNOWN - invalid response from server-meter" ;;
esac

emit_high() {
  title=$1
  value=$2
  unit=$3
  warn=$4
  crit=$5
  label=$6
  digits=$7
  if [ -z "$value" ] || [ "$value" = "null" ] || ! is_number "$value"; then
    finish "$STATE_UNKNOWN" "UNKNOWN - $title is not available"
  fi
  shown=$(fmt "$value" "$digits")
  warn_s=""
  crit_s=""
  if is_number "$warn"; then
    warn_s=$warn
  fi
  if is_number "$crit"; then
    crit_s=$crit
  fi
  unit_txt=""
  if [ -n "$unit" ]; then
    unit_txt=" $unit"
  fi
  perf="$label=$shown"
  if [ -n "$warn_s" ] || [ -n "$crit_s" ]; then
    perf="$label=$shown;$warn_s;$crit_s"
  fi
  if is_number "$crit_s" && ge "$value" "$crit_s"; then
    finish "$STATE_CRITICAL" "CRITICAL - $title=$shown$unit_txt (critical >= $crit_s$unit_txt) | $perf"
  fi
  if is_number "$warn_s" && ge "$value" "$warn_s"; then
    finish "$STATE_WARNING" "WARNING - $title=$shown$unit_txt (warning >= $warn_s$unit_txt) | $perf"
  fi
  finish "$STATE_OK" "OK - $title=$shown$unit_txt | $perf"
}

emit_info() {
  title=$1
  value=$2
  unit=$3
  label=$4
  digits=$5
  if [ -z "$value" ] || [ "$value" = "null" ] || ! is_number "$value"; then
    finish "$STATE_UNKNOWN" "UNKNOWN - $title is not available"
  fi
  shown=$(fmt "$value" "$digits")
  unit_txt=""
  if [ -n "$unit" ]; then
    unit_txt=" $unit"
  fi
  finish "$STATE_OK" "OK - $title=$shown$unit_txt | $label=$shown"
}

check_health() {
  overall=$(json_string "$body" "overall")
  overall=$(printf '%s' "$overall" | tr '[:lower:]' '[:upper:]')
  case "$overall" in
    OK) code=$STATE_OK ;;
    WARNING) code=$STATE_WARNING ;;
    CRITICAL) code=$STATE_CRITICAL ;;
    UNKNOWN) code=$STATE_UNKNOWN ;;
    *) finish "$STATE_UNKNOWN" "UNKNOWN - invalid response from server-meter" ;;
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
}

check_sensor() {
  available=$(json_bool "$body" sensor_available)
  age=$(json_number "$body" sensor_age_seconds)
  warn=$SENSOR_AGE_WARNING
  crit=$SENSOR_AGE_CRITICAL
  if [ "$available" = "false" ] || [ "$available" = "null" ] || [ -z "$available" ]; then
    finish "$STATE_CRITICAL" "CRITICAL - BME690 sensor unavailable"
  fi
  if is_number "$age"; then
    shown=$(fmt "$age" 0)
    perf="sensor_age=$shown;$warn;$crit"
    if is_number "$crit" && ge "$age" "$crit"; then
      finish "$STATE_CRITICAL" "CRITICAL - BME690 data too old: $shown seconds | $perf"
    fi
    if is_number "$warn" && ge "$age" "$warn"; then
      finish "$STATE_WARNING" "WARNING - BME690 data age=$shown seconds (warning >= $warn s) | $perf"
    fi
    finish "$STATE_OK" "OK - BME690 sensor available, age=$shown s | $perf"
  fi
  finish "$STATE_OK" "OK - BME690 sensor available"
}

check_accuracy() {
  title=$1
  key=$2
  label=$3
  value=$(json_number "$body" "$key")
  if [ -z "$value" ] || [ "$value" = "null" ] || ! is_number "$value"; then
    finish "$STATE_UNKNOWN" "UNKNOWN - $title is not available"
  fi
  shown=$(fmt "$value" 0)
  if ge "$value" 2; then
    finish "$STATE_OK" "OK - $title=$shown | $label=$shown"
  fi
  if ge "$IAQ_ACCURACY_WARNING" "$value" || [ "$shown" = "0" ] || [ "$shown" = "1" ]; then
    finish "$STATE_WARNING" "WARNING - $title=$shown (calibrating; not a health limit) | $label=$shown"
  fi
  finish "$STATE_OK" "OK - $title=$shown | $label=$shown"
}

case "$METRIC" in
  ""|health)
    check_health
    ;;
  temperature)
    emit_high "BME690 temperature" "$(json_number "$body" temperature_c)" "C" \
      "$TEMP_WARNING" "$TEMP_CRITICAL" temperature 1
    ;;
  humidity)
    emit_high "BME690 humidity" "$(json_number "$body" humidity_percent)" "%" \
      "$HUMIDITY_WARNING" "$HUMIDITY_CRITICAL" humidity 1
    ;;
  pressure)
    emit_info "BME690 pressure" "$(json_number "$body" pressure_hpa)" "hPa" pressure 1
    ;;
  gas_resistance)
    emit_info "BME690 gas resistance" "$(json_number "$body" gas_resistance_ohm)" "Ohm" gas_resistance 0
    ;;
  iaq)
    emit_high "BME690 IAQ" "$(json_number "$body" iaq)" "" \
      "$IAQ_WARNING" "$IAQ_CRITICAL" iaq 1
    ;;
  iaq_accuracy)
    check_accuracy "BME690 IAQ accuracy" iaq_accuracy iaq_accuracy
    ;;
  static_iaq)
    emit_high "BME690 static IAQ" "$(json_number "$body" static_iaq)" "" \
      "$IAQ_WARNING" "$IAQ_CRITICAL" static_iaq 1
    ;;
  static_iaq_accuracy)
    check_accuracy "BME690 static IAQ accuracy" static_iaq_accuracy static_iaq_accuracy
    ;;
  eco2)
    emit_high "BME690 eCO2" "$(json_number "$body" eco2_ppm)" "ppm" \
      "$ECO2_WARNING" "$ECO2_CRITICAL" eco2 0
    ;;
  bvoc)
    emit_high "BME690 bVOC" "$(json_number "$body" bvoc_ppm)" "ppm" \
      "$BVOC_WARNING" "$BVOC_CRITICAL" bvoc 2
    ;;
  cpu_temperature)
    emit_high "CPU temperature" "$(json_number "$body" cpu_temperature_c)" "C" \
      "$CPU_TEMP_WARNING" "$CPU_TEMP_CRITICAL" cpu_temperature 1
    ;;
  cpu_load)
    emit_high "CPU load" "$(json_number "$body" cpu_load_percent)" "%" \
      "$CPU_LOAD_WARNING" "$CPU_LOAD_CRITICAL" cpu_load 1
    ;;
  ram)
    emit_high "RAM usage" "$(json_number "$body" ram_used_percent)" "%" \
      "$RAM_WARNING" "$RAM_CRITICAL" ram 1
    ;;
  sensor)
    check_sensor
    ;;
  *)
    finish "$STATE_UNKNOWN" "UNKNOWN - unknown metric '$METRIC'. See --help."
    ;;
esac
