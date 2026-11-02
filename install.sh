#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$ROOT/data/servers/DensitySMP"
VERSION="1.21.11"
BUILD="132"
EXPECTED_SHA256="5ffef465eeeb5f2a3c23a24419d97c51afd7dbb4923ff42df9a3f58bba1ccfba"
METADATA_URL="https://fill.papermc.io/v3/projects/paper/versions/$VERSION/builds/$BUILD"
JAVA_URL="https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse"

mkdir -p "$SERVER_DIR" "$ROOT/data/logs" "$ROOT/data/backups"

source "$ROOT/.java-env.sh"
if [[ -z "${JAVA_HOME:-}" ]]; then
  echo "Installing a Java 21 runtime into $ROOT/data/java ..."
  java_archive="$(mktemp "$ROOT/data/.java21.XXXXXX.tar.gz")"
  curl --fail --silent --show-error --location "$JAVA_URL" --output "$java_archive"
  rm -rf "$ROOT/data/java"
  mkdir -p "$ROOT/data/java"
  tar -xzf "$java_archive" -C "$ROOT/data/java" --strip-components=1
  rm -f -- "$java_archive"
  source "$ROOT/.java-env.sh"
fi
if [[ -z "${JAVA_HOME:-}" ]]; then
  echo "Java 21 could not be installed or found." >&2
  exit 1
fi
echo "Java runtime: $("$JAVA_HOME/bin/java" -version 2>&1 | head -1)"

if ! python3 -c "import psutil" >/dev/null 2>&1; then
  echo "Installing Python dependencies ..."
  python3 -m pip install --user --quiet -r "$ROOT/requirements.txt" \
    || python3 -m pip install --user --quiet --break-system-packages -r "$ROOT/requirements.txt" \
    || { echo "Could not install psutil. Install pip, or run: apt-get install python3-psutil" >&2; exit 1; }
fi

if [[ -e "$SERVER_DIR/paper.jar" ]]; then
  actual="$(sha256sum "$SERVER_DIR/paper.jar" | awk '{print $1}')"
  if [[ "$actual" != "$EXPECTED_SHA256" ]]; then
    echo "Existing paper.jar has a different checksum; delete it and run install.sh again." >&2
    exit 1
  fi
  echo "Verified existing Paper $VERSION build $BUILD jar."
else
  echo "Downloading Paper $VERSION build $BUILD ..."
  metadata="$(curl --fail --silent --show-error --location "$METADATA_URL")"
  download_url="$(python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d.get("id") == int(sys.argv[2])
artifact = d["downloads"]["server:default"]
assert artifact["checksums"]["sha256"] == sys.argv[1]
print(artifact["url"])
' "$EXPECTED_SHA256" "$BUILD" <<<"$metadata")"
  temp="$(mktemp "$SERVER_DIR/.paper-$VERSION-$BUILD.XXXXXX")"
  trap 'rm -f -- "$temp"' EXIT
  curl --fail --silent --show-error --location "$download_url" --output "$temp"
  actual="$(sha256sum "$temp" | awk '{print $1}')"
  if [[ "$actual" != "$EXPECTED_SHA256" ]]; then
    echo "Paper download checksum mismatch; refusing to install." >&2
    exit 1
  fi
  mv -- "$temp" "$SERVER_DIR/paper.jar"
  trap - EXIT
  echo "Installed and SHA-256 verified Paper $VERSION build $BUILD."
fi

python3 "$ROOT/servermaker.py" --initialize
echo "Install complete."
