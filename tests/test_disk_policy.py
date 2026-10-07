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
