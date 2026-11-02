#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if python3 servermaker.py --shutdown; then
  echo "Shutdown requested. The Minecraft server saves the world before it stops."
else
  echo "ServerMaker is not running."
fi
