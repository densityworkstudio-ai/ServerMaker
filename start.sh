#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
bash "$ROOT/install.sh"
source "$ROOT/.java-env.sh"
exec python3 servermaker.py
