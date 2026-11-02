#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$ROOT/data/servers/DensitySMP"
VERSION="1.21.11"
BUILD="132"
EXPECTED_SHA256="5ffef465eeeb5f2a3c23a24419d97c51afd7dbb4923ff42df9a3f58bba1ccfba"
METADATA_URL="https://fill.papermc.io/v3/projects/paper/versions/$VERSION/builds/$BUILD"

source "$ROOT/.java-env.sh"
mkdir -p "$SERVER_DIR" "$ROOT/data/logs" "$ROOT/data/backups"

python3 -m pip install --user -r "$ROOT/requirements.txt"

JAVA_MAJOR="$("$JAVA_HOME/bin/java" -version 2>&1 | sed -n '1s/.*version "\(.*\)".*/\1/p' | cut -d. -f1)"
JAVAC_MAJOR="$("$JAVA_HOME/bin/javac" -version 2>&1 | sed -n '1s/.* \([0-9][0-9]*\).*/\1/p')"
if [[ "$JAVA_MAJOR" != 21 || "$JAVAC_MAJOR" != 21 ]]; then
  echo "Java 21 JDK is required; found java=$JAVA_MAJOR javac=$JAVAC_MAJOR at $JAVA_HOME" >&2
  exit 1
fi

if [[ -e "$SERVER_DIR/paper.jar" ]]; then
  actual="$(sha256sum "$SERVER_DIR/paper.jar" | awk '{print $1}')"
  if [[ "$actual" != "$EXPECTED_SHA256" ]]; then
    echo "Existing paper.jar has a different checksum; leaving it untouched." >&2
    exit 1
  fi
  echo "Verified existing Paper $VERSION build $BUILD jar."
else
  metadata="$(curl --fail --silent --show-error --location "$METADATA_URL")"
  download_url="$(python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d.get("id") == 132
artifact = d["downloads"]["server:default"]
assert artifact["name"] == "paper-1.21.11-132.jar"
assert artifact["checksums"]["sha256"] == sys.argv[1]
print(artifact["url"])
' "$EXPECTED_SHA256" <<<"$metadata")"
  temp="$(mktemp "$SERVER_DIR/.paper-1.21.11-132.XXXXXX")"
  trap 'rm -f -- "$temp"' EXIT
  curl --fail --silent --show-error --location "$download_url" --output "$temp"
  actual="$(sha256sum "$temp" | awk '{print $1}')"
  if [[ "$actual" != "$EXPECTED_SHA256" ]]; then
    echo "Paper download checksum mismatch; refusing to install." >&2
    exit 1
  fi
  if [[ -e "$SERVER_DIR/paper.jar" ]]; then
    echo "paper.jar appeared during installation; leaving the existing file untouched." >&2
    exit 1
  fi
  mv -- "$temp" "$SERVER_DIR/paper.jar"
  trap - EXIT
  echo "Installed and SHA-256 verified Paper $VERSION build $BUILD."
fi

python3 "$ROOT/servermaker.py" --initialize
echo "Java runtime: $("$JAVA_HOME/bin/java" -version 2>&1 | head -1)"
echo "Java compiler: $("$JAVA_HOME/bin/javac" -version 2>&1)"
echo "Install complete. Run $ROOT/start.sh to start the dashboard and supervised server."
