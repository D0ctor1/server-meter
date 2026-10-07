#!/usr/bin/env bash
# Upgrade path is the same idempotent installer (preserves /etc/server-meter/config.yaml).
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/install.sh" --skip-upgrade "$@"
