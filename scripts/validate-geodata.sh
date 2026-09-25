#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 7 ]]; then
  echo "usage: $0 <dlc-repo> <UDAL-GEOSITE.dat> <UDAL-GEOIP.dat> <xray-bin> <policy.json> <validation-contract.json> <work-dir>" >&2
  exit 2
fi

DLC_REPO="$(realpath "$1")"
GEOSITE="$(realpath "$2")"
GEOIP="$(realpath "$3")"
XRAY="$(realpath "$4")"
POLICY="$(realpath "$5")"
CONTRACT="$(realpath "$6")"
WORK="$(realpath -m "$7")"

if [[ -e "$WORK" ]]; then
  echo "FAIL: validation work directory already exists: $WORK" >&2
  exit 1
fi

mkdir -p "$WORK/dump" "$WORK/assets"
cp "$GEOSITE" "$WORK/assets/geosite.dat"
cp "$GEOIP" "$WORK/assets/geoip.dat"

(
  cd "$DLC_REPO"
  go run ./cmd/datdump --inputdata "$GEOSITE" --outputdir "$WORK/dump"
)

DUMP="$WORK/dump/$(basename "$GEOSITE")_plain.yml"
[[ -f "$DUMP" ]] || { echo "FAIL: datdump output missing" >&2; exit 1; }

python3 - "$DUMP" "$POLICY" <<'PY'
import json, re, sys
from pathlib import Path
dump = Path(sys.argv[1]).read_text(encoding="utf-8")
policy = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
actual = re.findall(r'^  - name: "([^"]+)"$', dump, flags=re.MULTILINE)
expected = policy["geositeTopLevel"]
if len(actual) != 31 or len(set(actual)) != 31:
    raise SystemExit(f"FAIL: geosite count {len(actual)}")
if set(actual) != set(expected):
    raise SystemExit("FAIL: geosite category set mismatch")
print("GEOSITE_CATEGORY_COUNT=31")
print("GEOSITE_CATEGORY_SET=PASS")
PY

python3 - "$POLICY" "$CONTRACT" "$WORK/xray-config.json" <<'PY'
import json, sys
from pathlib import Path
policy = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
contract = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

if policy["proxyIp"] != contract["proxyIpExact"]:
    raise SystemExit(f"FAIL: ProxyIp exact contract mismatch: {policy['proxyIp']}")

required_geoip = [x.removeprefix("geoip:") for x in policy["proxyIp"]]
missing = sorted(set(required_geoip) - set(contract["geoipValidationCategories"]))
if missing:
    raise SystemExit(f"FAIL: routing ProxyIp categories are not covered by Xray validation contract: {missing}")
if contract["broadRuBlockedGeoipActive"] is not False or "ru-blocked" in required_geoip:
    raise SystemExit("FAIL: broad geoip:ru-blocked is active")

cfg = {
    "log": {"loglevel": "warning"},
    "inbounds": [],
    "outbounds": [
        {"protocol": "freedom", "tag": "direct"},
        {"protocol": "blackhole", "tag": "proxy"}
    ],
    "routing": {
        "domainStrategy": "AsIs",
        "rules": [
            {
                "type": "field",
                "domain": [f"geosite:{x}" for x in policy["geositeTopLevel"]],
                "outboundTag": "proxy"
            },
            {
                "type": "field",
                "ip": [f"geoip:{x}" for x in contract["geoipValidationCategories"]],
                "outboundTag": "proxy"
            }
        ]
    }
}
Path(sys.argv[3]).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

XRAY_LOCATION_ASSET="$WORK/assets" "$XRAY" run -test -config "$WORK/xray-config.json"

python3 - "$POLICY" <<'PY'
import json, sys
from pathlib import Path
policy = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for item in policy["proxyIp"]:
    name = item.removeprefix("geoip:").upper().replace("-", "_")
    print(f"XRAY_GEOIP_{name}=PASS")
PY

echo "XRAY_VALIDATION=PASS"
echo "VALIDATE_GEODATA=PASS"
