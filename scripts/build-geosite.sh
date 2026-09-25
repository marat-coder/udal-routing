#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 <domain-list-community-repo> <data-minimal> <datprofile.json> <output-dir> <expected-commit>" >&2
  exit 2
fi

DLC_REPO="$(realpath "$1")"
DATA_MINIMAL="$(realpath "$2")"
DATPROFILE="$(realpath "$3")"
OUT_DIR="$(realpath -m "$4")"
EXPECTED_COMMIT="$5"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_GO="$(
  python3 - "$ROOT/config/toolchain-lock.json" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    print(json.load(f)["go"]["version"])
PY
)"

ACTUAL_COMMIT="$(git -C "$DLC_REPO" rev-parse HEAD)"
if [[ "$ACTUAL_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  echo "FAIL: domain-list-community commit mismatch" >&2
  echo "EXPECTED=$EXPECTED_COMMIT" >&2
  echo "ACTUAL=$ACTUAL_COMMIT" >&2
  exit 1
fi

GO_VERSION="$(go version | awk '{print $3}')"
if [[ "$GO_VERSION" != "go$EXPECTED_GO" ]]; then
  echo "FAIL: Go version mismatch" >&2
  echo "EXPECTED=go$EXPECTED_GO" >&2
  echo "ACTUAL=$GO_VERSION" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
if find "$OUT_DIR" -mindepth 1 -maxdepth 1 -type f -print -quit | grep -q .; then
  echo "FAIL: output directory already contains files: $OUT_DIR" >&2
  exit 1
fi

export GOTOOLCHAIN=local

(
  cd "$DLC_REPO"
  go run .     --datapath "$DATA_MINIMAL"     --datprofile "$DATPROFILE"     --outputdir "$OUT_DIR"
)

if [[ ! -f "$OUT_DIR/geosite.dat" ]]; then
  echo "FAIL: generator did not produce geosite.dat" >&2
  exit 1
fi

mv "$OUT_DIR/geosite.dat" "$OUT_DIR/UDAL-GEOSITE.dat"

SHA="$(sha256sum "$OUT_DIR/UDAL-GEOSITE.dat" | awk '{print $1}')"
SIZE="$(stat -c '%s' "$OUT_DIR/UDAL-GEOSITE.dat")"

echo "UDAL_GEOSITE_SIZE=$SIZE"
echo "UDAL_GEOSITE_SHA256=$SHA"
echo "BUILD_GEOSITE=PASS"
