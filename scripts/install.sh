#!/usr/bin/env bash
# Backward-compatible wrapper. The unattended installer lives at the repository root.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "${ROOT}/install.sh" "$@"
