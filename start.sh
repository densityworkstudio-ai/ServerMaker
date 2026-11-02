#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$ROOT/.java-env.sh"
cd "$ROOT"
if [[ ! -f "$ROOT/data/servers/DensitySMP/paper.jar" ]]; then
  echo "Paper is not installed. Run $ROOT/install.sh first." >&2
  exit 1
fi
exec python3 servermaker.py
