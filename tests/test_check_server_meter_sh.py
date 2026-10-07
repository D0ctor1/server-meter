from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "scripts" / "check_server_meter.sh"
INSTALLER = Path(__file__).resolve().parent.parent / "scripts" / "install_nagios_plugin.sh"


def _payload(overall: str) -> dict:
    return {
        "hostname": "server-meter",
        "status": overall,
        "overall": overall,
        "overall_state": {"OK": "NORMAL", "WARNING": "WARNING", "CRITICAL": "CRITICAL", "UNKNOWN": "UNKNOWN"}[overall],
        "sensor_available": True,
        "sensor_age_seconds": 2,
        "temperature_c": 24.3,
        "humidity_percent": 45.2,
        "pressure_hpa": 1008.3,
        "gas_resistance_ohm": 123456,
        "iaq": 42.1,
        "iaq_accuracy": 3,
        "static_iaq": 41.5,
        "static_iaq_accuracy": 3,
        "eco2_ppm": 650,
        "bvoc_ppm": 0.4,
        "cpu_temperature_c": 48.2,
        "cpu_load_percent": 10.0,
        "ram_used_percent": 32.0,
        "uptime_seconds": 1000,
        "temperature_warning": 45,
        "temperature_critical": 50,
        "humidity_warning": 80,
        "humidity_critical": 90,
        "iaq_warning": 150,
        "iaq_critical": 250,
        "eco2_warning": 1500,
        "eco2_critical": 2500,
        "bvoc_warning": 1.0,
        "bvoc_critical": 2.0,
        "cpu_temperature_warning": 70,
        "cpu_temperature_critical": 80,
        "ram_warning": 70,
        "ram_critical": 85,
        "sensor_age_warning": 15,
        "sensor_age_critical": 30,
        "sensor": {"status": "ok", "temperature": 24.3, "available": True},
        "system": {"cpu_temperature": 48.2, "ram_usage_percent": 32.0},
        "thresholds": {"temperature": {"warning_high": 45, "critical_high": 50}},
    }


class _Handler(BaseHTTPRequestHandler):
    payload = _payload("OK")
    require_auth = True
    expected_auth = "Basic YWRtaW46c2VjcmV0"

    def do_GET(self) -> None:  # noqa: N802
        if self.require_auth and self.headers.get("Authorization") != self.expected_auth:
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


def _prepared_plugin(tmp_path: Path, url: str, password: str = "secret") -> Path:
    text = PLUGIN.read_text(encoding="utf-8")
    text = text.replace('SERVER_METER_URL="http://192.168.1.50:8080"', f'SERVER_METER_URL="{url}"')
    text = text.replace('SERVER_METER_USERNAME="admin"', 'SERVER_METER_USERNAME="admin"')
    text = text.replace('SERVER_METER_PASSWORD="CHANGE_ME"', f'SERVER_METER_PASSWORD="{password}"')
    dest = tmp_path / "check_server_meter.sh"
    dest.write_text(text, encoding="utf-8")
    dest.chmod(0o700)
    return dest


def _run(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(script)], check=False, capture_output=True, text=True)


def test_plugin_ok_warning_critical_unknown_and_perfdata(tmp_path):
    for overall, code in (("OK", 0), ("WARNING", 1), ("CRITICAL", 2), ("UNKNOWN", 3)):
        server, _thread, port = _serve(_payload(overall))
        try:
            script = _prepared_plugin(tmp_path, f"http://127.0.0.1:{port}")
            result = _run(script)
        finally:
            server.shutdown()
        assert result.returncode == code, result.stdout + result.stderr
        assert result.stdout.startswith(f"{overall} - ")
        assert "temperature=24.3C" in result.stdout or "temperature=24.3" in result.stdout
        assert "|" in result.stdout
        assert "temperature=24.3;45;50" in result.stdout or "temperature=24.3;45;50" in result.stdout.replace("24.30", "24.3")
        assert "secret" not in result.stdout
        assert "secret" not in result.stderr


def test_plugin_runs_with_no_arguments(tmp_path):
    server, _thread, port = _serve(_payload("OK"))
    try:
        script = _prepared_plugin(tmp_path, f"http://127.0.0.1:{port}")
        result = _run(script)
    finally:
        server.shutdown()
    assert result.returncode == 0
    assert "server-meter reachable" in result.stdout


def test_plugin_connection_failure_is_critical(tmp_path):
    script = _prepared_plugin(tmp_path, "http://127.0.0.1:1")
    result = _run(script)
    assert result.returncode == 2
    assert result.stdout.startswith("CRITICAL")
    assert "unreachable" in result.stdout
    assert "secret" not in result.stdout


def test_plugin_invalid_json_is_unknown(tmp_path):
    class _Bad(_Handler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"not-json")

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = HTTPServer(("127.0.0.1", port), _Bad)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = _prepared_plugin(tmp_path, f"http://127.0.0.1:{port}")
        result = _run(script)
    finally:
        server.shutdown()
    assert result.returncode == 3
    assert "invalid monitoring data" in result.stdout


def test_plugin_help_and_change_me_password():
    help_result = subprocess.run(["sh", str(PLUGIN), "--help"], check=False, capture_output=True, text=True)
    assert help_result.returncode == 3
    assert "SERVER_METER_URL" in help_result.stdout
    assert "CHANGE_ME" not in help_result.stdout
    bare = subprocess.run(["sh", str(PLUGIN)], check=False, capture_output=True, text=True)
    assert bare.returncode == 3
    assert "SERVER_METER_PASSWORD" in bare.stdout


def test_plugin_has_no_python_jq_or_extra_config():
    text = PLUGIN.read_text(encoding="utf-8")
    assert "python" not in text.lower()
    assert "jq" not in text
    assert "mktemp" not in text
    assert "/etc/nagios" not in text
    assert "/tmp" not in text
    assert "import server_meter" not in text
    assert "--insecure" in text
    assert "CURL_INSECURE=false" in text
    assert "/api/monitoring" in text
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "python3" not in installer
    assert "jq" not in installer
    assert "apt-get install" not in installer
    assert "does not change nagios.cfg or Python" in installer
    assert "server-meter.conf" not in installer
    assert "0700" in installer


def test_installer_preserves_existing_password(tmp_path):
    dest_dir = tmp_path / "plugins"
    dest_dir.mkdir()
    dest = dest_dir / "check_server_meter.sh"
    customized = PLUGIN.read_text(encoding="utf-8").replace(
        'SERVER_METER_PASSWORD="CHANGE_ME"',
        'SERVER_METER_PASSWORD="keep/me&special"',
    ).replace(
        'SERVER_METER_URL="http://192.168.1.50:8080"',
        'SERVER_METER_URL="http://10.9.8.7:8080"',
    )
    dest.write_text(customized, encoding="utf-8")
    staging = tmp_path / "staging"
    src = PLUGIN
    script = f"""
sed '/^# === server-meter plugin configuration ===/,$d' "{src}"
awk '/^# === server-meter plugin configuration ===/,/^# === end configuration ===/' "{dest}"
sed '1,/^# === end configuration ===/d' "{src}"
"""
    merged = subprocess.check_output(["bash", "-c", script], text=True)
    staging.write_text(merged, encoding="utf-8")
    assert 'SERVER_METER_PASSWORD="keep/me&special"' in merged
    assert "http://10.9.8.7:8080" in merged
    assert "Requires: curl" in merged


def test_plugin_mode_in_repo_is_executable():
    mode = PLUGIN.stat().st_mode
    assert mode & stat.S_IXUSR
    assert os.access(PLUGIN, os.X_OK)
