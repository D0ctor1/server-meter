from __future__ import annotations

from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.config import DEFAULT_PASSWORD_PLACEHOLDER
from server_meter.service import MeterService
from server_meter.users import UserStore
from tests.conftest import make_config


def _app(tmp_path, password="secret123"):
    cfg = make_config()
    cfg.web.auth.password = password
    cfg.web.users_db = str(tmp_path / "users.db")
    service = MeterService(cfg)
    return create_app(cfg, service=service), cfg


def test_admin_and_user_login_and_bad_password(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/me", auth=("admin", "secret123")).status_code == 200
        assert client.get("/api/me", auth=("admin", "secret123")).json() == {
            "username": "admin",
            "role": "admin",
        }
        created = client.post(
            "/api/admin/users",
            auth=("admin", "secret123"),
            json={"username": "jan", "password": "userpass1", "role": "user", "enabled": True},
        )
        assert created.status_code == 200, created.text
        me = client.get("/api/me", auth=("jan", "userpass1"))
        assert me.status_code == 200
        assert me.json() == {"username": "jan", "role": "user"}
        assert client.get("/api/current", auth=("jan", "userpass1")).status_code == 200
        assert client.get("/api/status", auth=("jan", "wrongpass1")).status_code == 401
        assert client.get("/api/me").status_code == 401


def test_user_cannot_call_admin_endpoints(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/api/admin/users",
            auth=("admin", "secret123"),
            json={"username": "jan", "password": "userpass1", "role": "user"},
        )
        auth = ("jan", "userpass1")
        assert client.get("/api/admin/users", auth=auth).status_code == 403
        assert client.get("/api/admin/export", auth=auth).status_code == 403
        assert client.get("/api/admin/system", auth=auth).status_code == 403
        assert client.post("/api/admin/monitoring-token", auth=auth).status_code == 403
        assert client.get("/api/settings", auth=auth).status_code == 403
        assert client.put("/api/settings", auth=auth, json={"enabled": True}).status_code == 403
        assert client.post("/api/settings/test-email", auth=auth).status_code == 403
        assert client.post(
            "/api/admin/restart-service",
            auth=auth,
            json={"confirm": "restart-service"},
        ).status_code == 403
        assert client.post(
            "/api/admin/reboot-host",
            auth=auth,
            json={"confirm": "reboot-host"},
        ).status_code == 403
        assert client.post(
            "/api/admin/users",
            auth=auth,
            json={"username": "x", "password": "abcdefgh", "role": "admin"},
        ).status_code == 403


def test_admin_user_lifecycle(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        admin = ("admin", "secret123")
        user = client.post(
            "/api/admin/users",
            auth=admin,
            json={"username": "jan", "password": "userpass1", "role": "user", "enabled": True},
        ).json()
        other_admin = client.post(
            "/api/admin/users",
            auth=admin,
            json={"username": "petr", "password": "adminpass", "role": "admin", "enabled": True},
        ).json()
        listed = client.get("/api/admin/users", auth=admin).json()["users"]
        names = {item["username"] for item in listed}
        assert names == {"admin", "jan", "petr"}
        updated = client.put(
            f"/api/admin/users/{user['id']}",
            auth=admin,
            json={"username": "janek", "role": "admin"},
        )
        assert updated.status_code == 200
        assert updated.json()["username"] == "janek"
        assert updated.json()["role"] == "admin"
        disabled = client.put(
            f"/api/admin/users/{other_admin['id']}",
            auth=admin,
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False
        deleted = client.delete(f"/api/admin/users/{other_admin['id']}", auth=admin)
        assert deleted.status_code == 200


def test_last_admin_cannot_be_removed(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        admin = ("admin", "secret123")
        users = client.get("/api/admin/users", auth=admin).json()["users"]
        admin_id = users[0]["id"]
        assert client.delete(f"/api/admin/users/{admin_id}", auth=admin).status_code == 409
        disable = client.put(
            f"/api/admin/users/{admin_id}",
            auth=admin,
            json={"enabled": False},
        )
        assert disable.status_code == 409
        assert disable.json()["error"] == "last_admin"
        demote = client.put(
            f"/api/admin/users/{admin_id}",
            auth=admin,
            json={"role": "user"},
        )
        assert demote.status_code == 409
        assert "last active administrator" in demote.json()["message"]


def test_password_is_hashed_and_old_password_stops_working(tmp_path, caplog):
    db = tmp_path / "users.db"
    app, cfg = _app(tmp_path)
    with TestClient(app) as client:
        admin = ("admin", "secret123")
        changed = client.put(
            "/api/admin/users/1",
            auth=admin,
            json={"password": "newsecret1"},
        )
        assert changed.status_code == 200
        assert client.get("/api/me", auth=("admin", "secret123")).status_code == 401
        assert client.get("/api/me", auth=("admin", "newsecret1")).status_code == 200
    raw = db.read_text(encoding="utf-8", errors="ignore")
    assert "secret123" not in raw
    assert "newsecret1" not in raw
    assert cfg.web.auth.password == "secret123"
    store = UserStore(str(db), test=True)
    record = store.get_by_username("admin")
    assert record is not None
    assert record.password_hash.startswith("$argon2")
    assert "secret123" not in caplog.text
    assert "newsecret1" not in caplog.text
    store.close()


def test_disabled_user_cannot_keep_using_api(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        admin = ("admin", "secret123")
        user = client.post(
            "/api/admin/users",
            auth=admin,
            json={"username": "jan", "password": "userpass1", "role": "user"},
        ).json()
        jan = ("jan", "userpass1")
        assert client.get("/api/status", auth=jan).status_code == 200
        client.put(f"/api/admin/users/{user['id']}", auth=admin, json={"enabled": False})
        assert client.get("/api/status", auth=jan).status_code == 401
        assert client.get("/api/current", auth=jan).status_code == 401


def test_yaml_admin_is_migrated_once(tmp_path):
    db = tmp_path / "users.db"
    app, cfg = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/me", auth=("admin", "secret123")).json()["role"] == "admin"
    store = UserStore(str(db), test=True)
    assert store.count() == 1
    store.close()
    app2 = create_app(cfg, service=MeterService(cfg))
    with TestClient(app2) as client:
        names = [u["username"] for u in client.get("/api/admin/users", auth=("admin", "secret123")).json()["users"]]
        assert names == ["admin"]


def test_factory_password_flag_follows_hash(tmp_path):
    cfg = make_config()
    cfg.web.auth.password = DEFAULT_PASSWORD_PLACEHOLDER
    cfg.web.users_db = str(tmp_path / "users.db")
    app = create_app(cfg, service=MeterService(cfg))
    with TestClient(app) as client:
        status = client.get("/api/status", auth=("admin", DEFAULT_PASSWORD_PLACEHOLDER)).json()
        assert status["application"]["default_password_active"] is True
        admin_id = client.get("/api/admin/users", auth=("admin", DEFAULT_PASSWORD_PLACEHOLDER)).json()["users"][0]["id"]
        client.put(
            f"/api/admin/users/{admin_id}",
            auth=("admin", DEFAULT_PASSWORD_PLACEHOLDER),
            json={"password": "changed99"},
        )
        status = client.get("/api/status", auth=("admin", "changed99")).json()
        assert status["application"]["default_password_active"] is False


def test_status_exposes_role_not_secrets(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        payload = client.get("/api/status", auth=("admin", "secret123")).json()
        assert payload["current_user"] == {"username": "admin", "role": "admin"}
        blob = str(payload)
        assert "secret123" not in blob
        assert "password_hash" not in blob
