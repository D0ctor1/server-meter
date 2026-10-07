# Nagios Core 4.4.5

server-meter exposes `GET /api/nagios/check`.

- HTTP status is **always 200** when the process is reachable.
- The body starts with `OK`, `WARNING`, `CRITICAL`, or `UNKNOWN`.
- Header `X-Nagios-Status` is `0`, `1`, `2`, or `3`.
- Header `X-Nagios-State` repeats the word.

This endpoint uses the same HTTP Basic Auth as the rest of the UI. It does
**not** bypass authentication.

## What is checked

Configured in YAML (`nagios.thresholds`):

- Process reachable (otherwise the plugin returns CRITICAL itself)
- BME690 communication / last sample age (`sensor_max_age_seconds`)
- Raspberry Pi CPU temperature
- RAM usage percent
- 1-minute load average
- Firmware throttle bits when Ubuntu exposes them
- IAQ (only if BSEC provided a value)

## Remote check (preferred)

Nagios often runs on another host. Use the shipped plugin:

```nagios
define command {
    command_name    check_server_meter
    command_line    $USER1$/check_server_meter.py --url http://$HOSTADDRESS$:8080/api/nagios/check --user $ARG1$ --password $ARG2$
}

define service {
    use                 generic-service
    host_name           raspberrypi
    service_description server-meter
    check_command       check_server_meter!admin!YOUR_PASSWORD
}
```

Install the plugin on the Nagios server:

```bash
sudo install -m 0755 scripts/check_server_meter.py /usr/local/nagios/libexec/check_server_meter.py
```

`check_http` can work but string matching is awkward because WARNING/CRITICAL
still return HTTP 200:

```nagios
define command {
    command_name    check_server_meter_http
    command_line    $USER1$/check_http -H $HOSTADDRESS$ -p 8080 -u /api/nagios/check -a $ARG1$:$ARG2$ --onredirect=critical -e 200
}
```

That only proves the endpoint is up. Prefer `check_server_meter.py` so the
plugin exit code follows `X-Nagios-Status`.

Do **not** put the password in the URL query string.

## Local check

On the Pi itself:

```bash
/opt/server-meter/venv/bin/python /opt/server-meter/scripts/check_server_meter.py \
  --url http://127.0.0.1:8080/api/nagios/check \
  --user admin --password 'YOUR_PASSWORD'
echo $?
```

## Example bodies

```
OK - BME690 reachable; temperature=24.1C, humidity=45.2%, pressure=1008.2hPa, gas=123.4kOhm, sensor_age=2s, cpu_temp=48.2C, ram=31%
WARNING - Raspberry Pi RAM usage 82%; temperature=24.1C, humidity=45.2%, pressure=1008.2hPa, gas=123.4kOhm, sensor_age=2s, cpu_temp=48.2C, ram=82%
CRITICAL - BME690 communication failure; sensor_age=n/a, cpu_temp=48.2C, ram=31%
UNKNOWN - sensor state unknown; sensor_age=n/a, cpu_temp=48.2C, ram=31%
```

## TLS

Basic Auth sends the password on every request. On an untrusted network put
server-meter behind nginx/Caddy with TLS and keep `web.host: 127.0.0.1`.
