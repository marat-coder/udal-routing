#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from pathlib import Path

EXPECTED = {"UDAL-GEOSITE.dat", "UDAL-GEOIP.dat", "UDAL-ROUTING.json", "MANIFEST.json", "SHA256SUMS"}
ORDER = ["UDAL-GEOSITE.dat", "UDAL-GEOIP.dat", "UDAL-ROUTING.json", "MANIFEST.json"]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


p = argparse.ArgumentParser()
p.add_argument("--bundle", required=True)
p.add_argument("--policy", required=True)
p.add_argument("--repo", required=True)
p.add_argument("--tag", required=True)
a = p.parse_args()

bundle = Path(a.bundle)
policy = json.loads(Path(a.policy).read_text(encoding="utf-8"))
actual = {x.name for x in bundle.iterdir() if x.is_file()}
if actual != EXPECTED:
    raise SystemExit(f"FAIL: asset set mismatch {sorted(actual)}")

routing_path = bundle / "UDAL-ROUTING.json"
manifest_path = bundle / "MANIFEST.json"
sums_path = bundle / "SHA256SUMS"

for path in (routing_path, manifest_path, sums_path):
    if path.read_bytes().startswith(b"\xef\xbb\xbf"):
        raise SystemExit(f"FAIL: BOM {path.name}")

routing = json.loads(routing_path.read_text(encoding="utf-8"))
checks = {
    "Name": policy["name"],
    "GlobalProxy": False,
    "UseChunkFiles": True,
    "RouteOrder": "block-direct-proxy",
    "DirectSites": policy["directSites"],
    "DirectIp": policy["directIp"],
    "ProxySites": policy["proxySites"],
    "ProxyIp": policy["proxyIp"],
    "BlockSites": [],
    "BlockIp": [],
    "DomainStrategy": "IPIfNonMatch",
    "FakeDNS": False,
}
for key, value in checks.items():
    if routing.get(key) != value:
        raise SystemExit(f"FAIL: routing mismatch {key}")

if "geoip:ru-blocked" in routing["ProxyIp"]:
    raise SystemExit("FAIL: broad geoip:ru-blocked is active")

active = {x.removeprefix("geosite:") for x in policy["proxySites"]}
reserve = set(policy["geositeReserve"])
top = set(policy["geositeTopLevel"])
if len(top) != 31 or len(active) != 22 or len(reserve) != 9:
    raise SystemExit("FAIL: 31/22/9 contract mismatch")
if active | reserve != top or active & reserve:
    raise SystemExit("FAIL: active/reserve partition mismatch")

prefix = f"https://github.com/{a.repo}/releases/download/{a.tag}"
if routing.get("Geoipurl") != f"{prefix}/UDAL-GEOIP.dat":
    raise SystemExit("FAIL: Geoipurl")
if routing.get("Geositeurl") != f"{prefix}/UDAL-GEOSITE.dat":
    raise SystemExit("FAIL: Geositeurl")

text = routing_path.read_text(encoding="utf-8") + "\n" + manifest_path.read_text(encoding="utf-8")
for pattern, label in [
    (r"udal-routing\.invalid", "placeholder"),
    (r"https?://[^\s\"']+/latest(?:/|\b)", "latest"),
    (r"raw\.githubusercontent\.com/[^\s\"']+/main/", "raw-main"),
    (r"(?i)\b[A-Z]:\\", "local-path"),
]:
    if re.search(pattern, text):
        raise SystemExit(f"FAIL: forbidden reference {label}")

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("revision") != a.tag:
    raise SystemExit("FAIL: manifest revision")
if manifest.get("status") != "PRODUCTION" or manifest.get("importAllowed") is not True:
    raise SystemExit("FAIL: manifest production gate")
if manifest.get("safety", {}).get("offlinePlaceholderUrls") is not False:
    raise SystemExit("FAIL: manifest placeholder safety")

artifacts = manifest.get("artifacts", {})
for name in ("UDAL-GEOSITE.dat", "UDAL-GEOIP.dat", "UDAL-ROUTING.json"):
    path = bundle / name
    md = artifacts.get(name, {})
    if md.get("sha256") != sha256(path) or md.get("size") != path.stat().st_size:
        raise SystemExit(f"FAIL: manifest artifact metadata {name}")

lines = sums_path.read_text(encoding="utf-8").splitlines()
if len(lines) != 4:
    raise SystemExit("FAIL: SHA256SUMS count")
seen = []
for line in lines:
    m = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
    if not m:
        raise SystemExit("FAIL: malformed SHA256SUMS")
    digest, name = m.groups()
    seen.append(name)
    if name not in ORDER or digest != sha256(bundle / name):
        raise SystemExit(f"FAIL: SHA256SUMS {name}")
if seen != ORDER:
    raise SystemExit("FAIL: SHA256SUMS order")

print("EXACT_ASSET_SET=PASS")
print("ROUTING_VALIDATION=PASS")
print("MANIFEST_VALIDATION=PASS")
print("SHA256_VALIDATION=PASS")
print("VALIDATE_ARTIFACTS=PASS")
