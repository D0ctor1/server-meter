from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "scripts" / "check_server_meter.sh"


def _payload(overall: str) -> dict:
    return {
        "hostname": "server-meter",
        "overall": overall,
        "overall_state": {"OK": "NORMAL", "WARNING": "WARNING", "CRITICAL": "CRITICAL", "UNKNOWN": "UNKNOWN"}[overall],
        "sensor": {
            "status": "ok",
            "age_seconds": 2,
            "temperature": 24.3,
            "humidity": 45.2,
            "pressure": 1008.3,
            "gas_resistance": 123456,
            "iaq": 42.1,
            "eco2": 650,
            "bvoc": 0.4,
            "available": True,
        },
        "system": {"cpu_temperature": 48.2, "cpu_usage_percent": 10.0, "ram_usage_percent": 32.0},
        "thresholds": {
            "temperature": {"warning_high": 45, "critical_high": 50},
            "humidity": {"warning_high": 80, "critical_high": 90},
            "iaq": {"warning_high": 150, "critical_high": 250},
            "eco2": {"warning_high": 1500, "critical_high": 2500},
            "bvoc": {"warning_high": 1.0, "critical_high": 2.0},
            "cpu_temperature": {"warning_high": 70, "critical_high": 80},
            "ram_usage": {"warning_high": 70, "critical_high": 85},
            "sensor_unavailable": {"warning_high": 15, "critical_high": 30},
        },
    }


class _Handler(BaseHTTPRequestHandler):
    payload = _payload("OK")
    require_auth = True

    def do_GET(self) -> None:  # noqa: N802
        if self.require_auth and self.headers.get("Authorization") != "Basic YWRtaW46c2VjcmV0":
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="server-meter"')
            self.end_headers()
            return
        if self.path.split("?", 1)[0] != "/api/monitoring":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


def _serve(payload: dict) -> tuple[HTTPServer, threading.Thread, int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    _Handler.payload = payload
    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def _run(port: int, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SERVER_METER_PASSWORD", None)
    return subprocess.run(
        [
            "bash",
            str(PLUGIN),
            "-H",
            "127.0.0.1",
            "-p",
            str(port),
            "-u",
            "admin",
            "-P",
            "secret",
            "-t",
            "2",
            *(extra or []),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_plugin_ok_warning_critical_unknown_and_perfdata():
    for overall, code in (("OK", 0), ("WARNING", 1), ("CRITICAL", 2), ("UNKNOWN", 3)):
        server, _thread, port = _serve(_payload(overall))
        try:
            result = _run(port)
        finally:
            server.shutdown()
        assert result.returncode == code, result.stdout + result.stderr
        assert result.stdout.startswith(f"{overall} - ")
        assert "temperature=24.3C" in result.stdout or "temperature=24.3" in result.stdout
        assert "|" in result.stdout
        assert "temperature=" in result.stdout
        assert ";45;50" in result.stdout
        assert "secret" not in result.stdout
        assert "import server_meter" not in PLUGIN.read_text(encoding="utf-8")
        assert "from server_meter" not in PLUGIN.read_text(encoding="utf-8")


def test_plugin_connection_failure_is_critical():
    result = subprocess.run(
        ["bash", str(PLUGIN), "-H", "127.0.0.1", "-p", "1", "-t", "1"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout.startswith("CRITICAL")


def test_plugin_does_not_use_python3_only():
    text = PLUGIN.read_text(encoding="utf-8")
    assert "python2" in text
    assert "jq" in text
    assert "import server_meter" not in text
    assert "from server_meter" not in text
    assert "/api/monitoring" in text
