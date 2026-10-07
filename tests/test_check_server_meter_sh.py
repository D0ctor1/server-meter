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
OBJECT_CFG = Path(__file__).resolve().parent.parent / "scripts" / "nagios" / "server-meter.cfg"


def _payload(overall: str = "OK", **overrides) -> dict:
    data = {
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
        "sensor": {"status": "ok", "temperature": 24.3, "iaq": 42.1, "iaq_accuracy": 3, "available": True},
        "system": {"cpu_temperature": 48.2, "ram_usage_percent": 32.0},
        "thresholds": {"iaq": {"warning_high": 150, "critical_high": 250}, "temperature": {"warning_high": 45}},
    }
    data.update(overrides)
    return data


class _Handler(BaseHTTPRequestHandler):
    payload = _payload("OK")
    require_auth = True
    expected_auth = "Basic YWRtaW46c2VjcmV0"
    raw_body: bytes | None = None

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
        body = self.raw_body if self.raw_body is not None else json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


def _serve(payload: dict | None = None, raw_body: bytes | None = None) -> tuple[HTTPServer, threading.Thread, int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    _Handler.payload = payload if payload is not None else _payload("OK")
    _Handler.raw_body = raw_body
    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def _prepared_plugin(tmp_path: Path, url: str, password: str = "secret") -> Path:
    text = PLUGIN.read_text(encoding="utf-8")
    text = text.replace('SERVER_METER_URL="http://192.168.1.50:8080"', f'SERVER_METER_URL="{url}"')
    text = text.replace('SERVER_METER_PASSWORD="CHANGE_ME"', f'SERVER_METER_PASSWORD="{password}"')
    dest = tmp_path / "check_server_meter.sh"
    dest.write_text(text, encoding="utf-8")
    dest.chmod(0o700)
    return dest


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(script), *args], check=False, capture_output=True, text=True)


def _check(tmp_path: Path, payload: dict | None = None, *args: str, raw_body: bytes | None = None) -> subprocess.CompletedProcess[str]:
    server, _thread, port = _serve(payload, raw_body=raw_body)
    try:
        script = _prepared_plugin(tmp_path, f"http://127.0.0.1:{port}")
        return _run(script, *args)
    finally:
        server.shutdown()
        _Handler.raw_body = None


def test_plugin_ok_warning_critical_unknown_and_perfdata(tmp_path):
    for overall, code in (("OK", 0), ("WARNING", 1), ("CRITICAL", 2), ("UNKNOWN", 3)):
        result = _check(tmp_path, _payload(overall))
        assert result.returncode == code, result.stdout + result.stderr
        assert result.stdout.startswith(f"{overall} - ")
        assert "|" in result.stdout
        assert "temperature=24.3;45;50" in result.stdout or "temperature=24.30;45;50" in result.stdout
        assert "secret" not in result.stdout
        assert "secret" not in result.stderr


def test_plugin_runs_with_no_arguments(tmp_path):
    result = _check(tmp_path, _payload("OK"))
    assert result.returncode == 0
    assert "server-meter reachable" in result.stdout


def test_plugin_health_argument_matches_no_arg(tmp_path):
    result = _check(tmp_path, _payload("OK"), "health")
    assert result.returncode == 0
    assert "server-meter reachable" in result.stdout


def test_temperature_ok_warning_critical(tmp_path):
    ok = _check(tmp_path, _payload(temperature_c=24.3), "temperature")
    assert ok.returncode == 0, ok.stdout
    assert ok.stdout.startswith("OK - BME690 temperature=24.3 C")
    assert "| temperature=24.3;45;50" in ok.stdout

    warn = _check(tmp_path, _payload(temperature_c=46), "temperature")
    assert warn.returncode == 1, warn.stdout
    assert warn.stdout.startswith("WARNING - BME690 temperature=")
    assert "warning >= 45" in warn.stdout
    assert "| temperature=" in warn.stdout

    crit = _check(tmp_path, _payload(temperature_c=51), "temperature")
    assert crit.returncode == 2, crit.stdout
    assert crit.stdout.startswith("CRITICAL - BME690 temperature=")
    assert "critical >= 50" in crit.stdout


def test_cpu_temperature_and_ram_thresholds(tmp_path):
    cpu = _check(tmp_path, _payload(cpu_temperature_c=48.1), "cpu_temperature")
    assert cpu.returncode == 0, cpu.stdout
    assert "CPU temperature=48.1 C" in cpu.stdout
    assert "| cpu_temperature=48.1;70;80" in cpu.stdout

    ram = _check(tmp_path, _payload(ram_used_percent=31.7), "ram")
    assert ram.returncode == 0, ram.stdout
    assert "RAM usage=31.7 %" in ram.stdout
    assert "| ram=31.7;85;95" in ram.stdout

    ram_warn = _check(tmp_path, _payload(ram_used_percent=90), "ram")
    assert ram_warn.returncode == 1, ram_warn.stdout
    ram_crit = _check(tmp_path, _payload(ram_used_percent=96), "ram")
    assert ram_crit.returncode == 2, ram_crit.stdout


def test_iaq_accuracy_is_not_confused_with_iaq(tmp_path):
    payload = _payload(iaq=99.9, iaq_accuracy=1, static_iaq=88.8, static_iaq_accuracy=3)
    iaq = _check(tmp_path, payload, "iaq")
    acc = _check(tmp_path, payload, "iaq_accuracy")
    static_acc = _check(tmp_path, payload, "static_iaq_accuracy")
    assert iaq.returncode == 0, iaq.stdout
    assert "IAQ=99.9" in iaq.stdout
    assert "| iaq=99.9" in iaq.stdout
    assert "iaq_accuracy" not in iaq.stdout.split("|", 1)[0]
    assert acc.returncode == 1, acc.stdout
    assert "IAQ accuracy=1" in acc.stdout
    assert "99.9" not in acc.stdout
    assert "| iaq_accuracy=1" in acc.stdout
    assert static_acc.returncode == 0, static_acc.stdout
    assert "static IAQ accuracy=3" in static_acc.stdout
    assert "99.9" not in static_acc.stdout


def test_missing_metric_is_unknown(tmp_path):
    payload = _payload()
    payload["temperature_c"] = None
    result = _check(tmp_path, payload, "temperature")
    assert result.returncode == 3
    assert "not available" in result.stdout


def test_unknown_metric_is_unknown(tmp_path):
    result = _check(tmp_path, _payload(), "not_a_metric")
    assert result.returncode == 3
    assert "unknown metric" in result.stdout


def test_sensor_too_old_is_critical(tmp_path):
    result = _check(tmp_path, _payload(sensor_available=True, sensor_age_seconds=37), "sensor")
    assert result.returncode == 2, result.stdout
    assert "data too old: 37 seconds" in result.stdout


def test_sensor_unavailable_is_critical(tmp_path):
    result = _check(tmp_path, _payload(sensor_available=False), "sensor")
    assert result.returncode == 2
    assert "sensor unavailable" in result.stdout


def test_plugin_connection_failure_is_critical(tmp_path):
    script = _prepared_plugin(tmp_path, "http://127.0.0.1:1")
    result = _run(script, "temperature")
    assert result.returncode == 2
    assert result.stdout.startswith("CRITICAL")
    assert "unreachable" in result.stdout
    assert "secret" not in result.stdout


def test_plugin_invalid_json_is_unknown(tmp_path):
    result = _check(tmp_path, raw_body=b"not-json")
    assert result.returncode == 3
    assert "invalid response from server-meter" in result.stdout


def test_plugin_help_and_change_me_password():
    help_result = subprocess.run(["sh", str(PLUGIN), "--help"], check=False, capture_output=True, text=True)
    assert help_result.returncode == 3
    assert "SERVER_METER_URL" in help_result.stdout
    assert "CHANGE_ME" not in help_result.stdout
    for metric in (
        "temperature",
        "humidity",
        "pressure",
        "gas_resistance",
        "iaq",
        "iaq_accuracy",
        "static_iaq",
        "static_iaq_accuracy",
        "eco2",
        "bvoc",
        "cpu_temperature",
        "cpu_load",
        "ram",
        "sensor",
        "health",
    ):
        assert metric in help_result.stdout
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
    assert "TEMP_WARNING=45" in text
    assert "CPU_TEMP_WARNING=70" in text
    assert "RAM_WARNING=85" in text
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "python3" not in installer
    assert "jq" not in installer
    assert "apt-get install" not in installer
    assert "does not install Python" in installer
    assert "server-meter.conf" not in installer
    assert "0700" in installer
    assert "$ARG1$" in installer or r"\$ARG1\$" in installer
    assert "nagios -v" in installer or "NAGIOS_BIN" in installer


def test_object_cfg_has_one_command_and_per_metric_services():
    text = OBJECT_CFG.read_text(encoding="utf-8")
    assert text.count("define command") == 1
    assert text.count("command_name") == 1
    assert "$ARG1$" in text
    assert "check_server_meter!temperature" in text
    assert "check_server_meter!iaq_accuracy" in text
    assert "check_server_meter!health" in text
    assert "Server Meter Health" in text
    assert "BME690 Temperature" in text
    assert "RAM Usage" in text
    assert "Sensor Availability" in text
    assert "service_description     Server Meter\n" not in text
    assert text.count("define service") == 15
    assert "check_server_meter_2" not in text


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
    src = PLUGIN
    script = f"""
sed '/^# === server-meter plugin configuration ===/,$d' "{src}"
awk '/^# === server-meter plugin configuration ===/,/^# === end configuration ===/' "{dest}"
sed '1,/^# === end configuration ===/d' "{src}"
"""
    merged = subprocess.check_output(["bash", "-c", script], text=True)
    assert 'SERVER_METER_PASSWORD="keep/me&special"' in merged
    assert "http://10.9.8.7:8080" in merged
    assert "Requires: curl" in merged
    assert "TEMP_WARNING=45" in merged


def test_installer_writes_objects_once(tmp_path):
    nagios_etc = tmp_path / "nagios" / "etc"
    objects = nagios_etc / "objects"
    objects.mkdir(parents=True)
    nagios_cfg = nagios_etc / "nagios.cfg"
    nagios_cfg.write_text("log_file=/tmp/nagios.log\n", encoding="utf-8")
    plugin_dir = tmp_path / "libexec"
    fake_bin = tmp_path / "nagios-bin"
    fake_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "SKIP_ROOT_CHECK": "1",
            "PLUGIN_DIR": str(plugin_dir),
            "NAGIOS_OBJECTS_DIR": str(objects),
            "NAGIOS_CFG": str(nagios_cfg),
            "NAGIOS_BIN": str(fake_bin),
            "NAGIOS_RELOAD": "0",
            "NAGIOS_HOST_NAME": "server-meter",
            "NAGIOS_HOST_ADDRESS": "10.1.2.3",
            "INCLUDE_HOST": "1",
        }
    )
    first = subprocess.run(["bash", str(INSTALLER)], check=False, capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stdout + first.stderr
    second = subprocess.run(["bash", str(INSTALLER)], check=False, capture_output=True, text=True, env=env)
    assert second.returncode == 0, second.stdout + second.stderr
    files = list(objects.glob("server-meter*.cfg"))
    assert [p.name for p in files] == ["server-meter.cfg"]
    text = (objects / "server-meter.cfg").read_text(encoding="utf-8")
    assert text.count("define command") == 1
    assert text.count("define service") == 15
    assert "10.1.2.3" in text
    assert str(plugin_dir / "check_server_meter.sh") in text
    assert "$ARG1$" in text
    cfg_text = nagios_cfg.read_text(encoding="utf-8")
    assert cfg_text.count("cfg_file=") == 1
    plugin = plugin_dir / "check_server_meter.sh"
    assert plugin.exists()
    assert plugin.stat().st_mode & 0o777 == 0o700


def test_plugin_mode_in_repo_is_executable():
    mode = PLUGIN.stat().st_mode
    assert mode & stat.S_IXUSR
    assert os.access(PLUGIN, os.X_OK)
