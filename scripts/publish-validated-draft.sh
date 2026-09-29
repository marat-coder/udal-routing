#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: $0 <repo> <tag> <release-id> <bundle-dir> <build-contract> <work-dir>" >&2
  exit 2
fi

REPO="$1"
TAG="$2"
RID="$3"
BUNDLE="$(realpath "$4")"
CONTRACT="$(realpath "$5")"
WORK="$(realpath -m "$6")"

mkdir -p "$WORK/latest-download"

gh api --method PATCH "repos/$REPO/releases/$RID" -F draft=false > "$WORK/published-release.json"
gh api "repos/$REPO/releases/latest" > "$WORK/latest-release.json"

curl -fL --retry 3 -o "$WORK/latest-download/UDAL-GEOIP.dat"   "https://github.com/$REPO/releases/latest/download/UDAL-GEOIP.dat"
curl -fL --retry 3 -o "$WORK/latest-download/UDAL-GEOSITE.dat"   "https://github.com/$REPO/releases/latest/download/UDAL-GEOSITE.dat"

python3 scripts/verify-published-release.py   --release-json "$WORK/published-release.json"   --latest-json "$WORK/latest-release.json"   --bundle "$BUNDLE"   --latest-dir "$WORK/latest-download"   --build-contract "$CONTRACT"   --tag "$TAG"

echo "AUTO_PUBLISH=PASS"
