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
POLL_ATTEMPTS="${IMMUTABLE_POLL_ATTEMPTS:-6}"
POLL_SECONDS="${IMMUTABLE_POLL_SECONDS:-2}"

[[ "$RID" =~ ^[0-9]+$ ]] || { echo "FAIL: invalid RID" >&2; exit 1; }
[[ "$POLL_ATTEMPTS" =~ ^[1-9][0-9]*$ ]] || { echo "FAIL: invalid IMMUTABLE_POLL_ATTEMPTS" >&2; exit 1; }
[[ "$POLL_SECONDS" =~ ^[0-9]+$ ]] || { echo "FAIL: invalid IMMUTABLE_POLL_SECONDS" >&2; exit 1; }

mkdir -p "$WORK/latest-download"

# JIT binding: fetch the exact RID immediately before the only publish mutation.
gh api "repos/$REPO/releases/$RID" > "$WORK/prepublish-release.json"
python3 scripts/verify-draft-release.py   --release-json "$WORK/prepublish-release.json"   --bundle "$BUNDLE"   --build-contract "$CONTRACT"   --expected-rid "$RID"   --expected-tag "$TAG"

# Exactly one publish mutation, only after JIT identity/digest verification.
gh api --method PATCH "repos/$REPO/releases/$RID" -F draft=false > "$WORK/publish-response.json"

immutable_ok=0
for ((attempt=1; attempt<=POLL_ATTEMPTS; attempt++)); do
  gh api "repos/$REPO/releases/$RID" > "$WORK/published-release.json"
  if python3 - "$WORK/published-release.json" "$RID" "$TAG" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
rid=int(sys.argv[2])
tag=sys.argv[3]
try:
    r=json.loads(p.read_text())
except Exception:
    raise SystemExit(1)
ok=(
    r.get("id")==rid
    and r.get("tag_name")==tag
    and r.get("draft") is False
    and r.get("prerelease") is False
    and bool(r.get("published_at"))
    and r.get("immutable") is True
)
raise SystemExit(0 if ok else 1)
PY
  then
    immutable_ok=1
    echo "IMMUTABLE_POLL_ATTEMPT=$attempt"
    break
  fi
  if (( attempt < POLL_ATTEMPTS )); then
    sleep "$POLL_SECONDS"
  fi
done

if [[ "$immutable_ok" != "1" ]]; then
  echo "FAIL: immutable=true not observed after bounded polling" >&2
  exit 1
fi

gh api "repos/$REPO/releases/latest" > "$WORK/latest-release.json"

curl -fL --retry 3 -o "$WORK/latest-download/UDAL-GEOIP.dat"   "https://github.com/$REPO/releases/latest/download/UDAL-GEOIP.dat"
curl -fL --retry 3 -o "$WORK/latest-download/UDAL-GEOSITE.dat"   "https://github.com/$REPO/releases/latest/download/UDAL-GEOSITE.dat"

python3 scripts/verify-published-release.py   --release-json "$WORK/published-release.json"   --latest-json "$WORK/latest-release.json"   --bundle "$BUNDLE"   --latest-dir "$WORK/latest-download"   --build-contract "$CONTRACT"   --tag "$TAG"   --release-id "$RID"

echo "PREPUBLISH_JIT_BINDING=PASS"
echo "IMMUTABLE_BOUNDED_POLLING=PASS"
echo "AUTO_PUBLISH=PASS"
