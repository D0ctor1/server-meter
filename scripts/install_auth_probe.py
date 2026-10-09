#!/usr/bin/env python3
"""Tell the installer whether YAML web.auth still matches SQLite.

Login after the first start is SQLite (Argon2), not YAML. YAML is only the
one-time seed for the first administrator. This probe never prints passwords,
hashes, tokens, or Authorization material.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any], *, ok: bool) -> int:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config_path = Path(args.config)

    result: dict[str, Any] = {
        "config_readable": False,
        "yaml_auth_enabled": False,
        "users_db": "",
        "users_db_exists": False,
        "user_count": 0,
        "enabled_admin_count": 0,
        "yaml_credentials_match": False,
        "factory_password_active": False,
        "reason": "uninitialized",
    }

    try:
        from server_meter.config import load_config
        from server_meter.users import UserStore, resolve_users_db_path
    except Exception:
        result["reason"] = "cannot_import_server_meter"
        return _emit(result, ok=False)

    if not config_path.is_file():
        result["reason"] = "config_missing"
        return _emit(result, ok=False)

    try:
        config = load_config(str(config_path))
    except Exception:
        result["reason"] = "config_invalid"
        return _emit(result, ok=False)

    result["config_readable"] = True
    result["yaml_auth_enabled"] = bool(config.web.auth.enabled)
    db_path = resolve_users_db_path(config)
    result["users_db"] = db_path
    if db_path == ":memory:" or not Path(db_path).is_file():
        result["reason"] = "users_db_missing"
        return _emit(result, ok=False)

    result["users_db_exists"] = True
    store = None
    try:
        # test=True: do not change journal_mode; Argon2 verify still reads the hash.
        store = UserStore(db_path, test=True)
        users = store.list_users()
        result["user_count"] = len(users)
        result["enabled_admin_count"] = sum(1 for user in users if user.role == "admin" and user.enabled)
        result["factory_password_active"] = bool(store.has_factory_password())
        if result["enabled_admin_count"] < 1:
            result["reason"] = "no_enabled_admin"
            return _emit(result, ok=False)
        username = (config.web.auth.username or "").strip()
        password = config.web.auth.password or ""
        matched = store.authenticate(username, password) is not None
        result["yaml_credentials_match"] = bool(matched)
        result["reason"] = "yaml_match" if matched else "yaml_mismatch"
        return _emit(result, ok=True)
    except Exception:
        result["reason"] = "users_db_unreadable"
        return _emit(result, ok=False)
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
