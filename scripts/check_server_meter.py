#!/usr/bin/env python3
"""Legacy Nagios helper. Do NOT install this file as check_server_meter.sh.

The supported plugin is scripts/check_server_meter.sh (pure bash, curl only).
Nagios Core 4.4.5 hosts often have only Python 2.7; this file needs Python 3
and must never replace the .sh plugin.

Exit codes: 0=OK 1=WARNING 2=CRITICAL 3=UNKNOWN

Prefers the HTTP endpoint so Nagios can run on another host.
Never writes sensor data to disk.

Examples:
  check_server_meter.py --url http://192.168.1.20:8080/api/nagios/check --user admin --password secret
  check_server_meter.py --url http://127.0.0.1:8080/api/nagios/check --no-auth
"""

from __future__ import annotations

import argparse
import base64
import sys
import urllib.error
import urllib.request

STATE = {"OK": 0, "WARNING": 1, "CRITICAL": 2, "UNKNOWN": 3}


def main() -> int:
    parser = argparse.ArgumentParser(description="Nagios plugin for server-meter")
    parser.add_argument("--url", default="http://127.0.0.1:8080/api/nagios/check")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--no-auth", action="store_true")
    args = parser.parse_args()

    request = urllib.request.Request(args.url, method="GET")
    if not args.no_auth and args.user:
        token = base64.b64encode(f"{args.user}:{args.password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            header_state = response.headers.get("X-Nagios-State", "")
    except urllib.error.HTTPError as exc:
        sys.stdout.write(f"CRITICAL - HTTP {exc.code} contacting server-meter\n")
        return 2
    except urllib.error.URLError as exc:
        sys.stdout.write(f"CRITICAL - cannot reach server-meter: {exc.reason}\n")
        return 2
    except TimeoutError:
        sys.stdout.write("CRITICAL - timeout contacting server-meter\n")
        return 2

    first = (header_state or body.split(" ", 1)[0]).strip().upper()
    code = STATE.get(first, 3)
    if first not in STATE:
        sys.stdout.write(f"UNKNOWN - unexpected plugin output: {body}\n")
        return 3
    sys.stdout.write(body + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
