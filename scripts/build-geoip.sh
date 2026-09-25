#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <upstream-geoip.dat> <output-dir> <expected-sha256-or-dash>" >&2
  exit 2
fi

SOURCE="$(realpath "$1")"
OUT_DIR="$(realpath -m "$2")"
EXPECTED_SHA="$3"

if [[ ! -f "$SOURCE" ]]; then
  echo "FAIL: upstream geoip.dat not found" >&2
  exit 1
fi

SOURCE_SHA="$(sha256sum "$SOURCE" | awk '{print $1}')"
if [[ "$EXPECTED_SHA" != "-" && "$SOURCE_SHA" != "$EXPECTED_SHA" ]]; then
  echo "FAIL: upstream geoip.dat SHA256 mismatch" >&2
  echo "EXPECTED=$EXPECTED_SHA" >&2
  echo "ACTUAL=$SOURCE_SHA" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
TARGET="$OUT_DIR/UDAL-GEOIP.dat"

if [[ -e "$TARGET" ]]; then
  echo "FAIL: target already exists: $TARGET" >&2
  exit 1
fi

cp "$SOURCE" "$TARGET"

TARGET_SHA="$(sha256sum "$TARGET" | awk '{print $1}')"
SOURCE_SIZE="$(stat -c '%s' "$SOURCE")"
TARGET_SIZE="$(stat -c '%s' "$TARGET")"

if [[ "$TARGET_SHA" != "$SOURCE_SHA" || "$TARGET_SIZE" != "$SOURCE_SIZE" ]]; then
  echo "FAIL: UDAL-GEOIP.dat is not a byte-for-byte copy" >&2
  exit 1
fi

echo "UDAL_GEOIP_SIZE=$TARGET_SIZE"
echo "UDAL_GEOIP_SHA256=$TARGET_SHA"
echo "BUILD_GEOIP=PASS"
