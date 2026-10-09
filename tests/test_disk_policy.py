"""Static guard: the application must not persist sensor history."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "server_meter"


def _read_tree(path: Path) -> str:
    chunks: list[str] = []
    for file in path.rglob("*.py"):
        chunks.append(file.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_no_database_or_history_libraries():
    text = _read_tree(SRC)
    forbidden = [
        "sqlalchemy",
        "psycopg",
        "influxdb",
        "prometheus_client",
        "redis",
        "shelve",
        "pickle.dump",
        "csv.writer",
    ]
    for token in forbidden:
        assert token not in text, f"forbidden persistence token {token}"
    users_py = (SRC / "users.py").read_text(encoding="utf-8")
    assert "sqlite3" in users_py
    allowed_sqlite = {"users.py", "sqlite_state.py"}
    for file in SRC.rglob("*.py"):
        if file.name in allowed_sqlite:
            continue
        text = file.read_text(encoding="utf-8")
        assert "sqlite3" not in text, f"sqlite3 must not appear in {file.relative_to(SRC)}"
    for folder in ("sensor", "storage", "monitoring"):
        other = _read_tree(SRC / folder)
        assert "sqlite3" not in other
    assert "sqlite3" not in (SRC / "storage" / "ram_buffer.py").read_text(encoding="utf-8")


def test_no_measurement_file_logging():
    text = _read_tree(SRC)
    assert "FileHandler" not in text
    assert "TimedRotatingFileHandler" not in text
    assert "WatchedFileHandler" not in text


def test_bsec_state_not_written():
    text = (SRC / "sensor" / "bsec.py").read_text(encoding="utf-8")
    assert "bsec_get_state(" not in text
    assert "persist_state" in (SRC / "config.py").read_text(encoding="utf-8")


def test_history_api_declares_ram(client, auth):
    payload = client.get("/api/history", auth=auth).json()
    assert payload["source"] == "ram"
    assert payload["persistent"] is False


def test_ram_buffer_never_opens_files():
    text = (SRC / "storage" / "ram_buffer.py").read_text(encoding="utf-8")
    for token in ("open(", "Path(", "write_text", "json.dump", "sqlite", "csv"):
        assert token not in text


def test_last_activity_never_opens_files():
    text = (SRC / "activity.py").read_text(encoding="utf-8")
    for token in ("open(", "Path(", "write_text", "json.dump", "sqlite", "csv", "yaml"):
        assert token not in text
    assert "dict[int, float]" in text or "_last" in text


def test_frontend_never_requests_full_two_million_points():
    app_js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert "const MAX_POINTS = 720;" in app_js
    assert "max_points=${MAX_POINTS}" in app_js
    assert "downsampleEven" in app_js
    assert "/api/history`" not in app_js
    assert "limit=${MAX_POINTS}" not in app_js
