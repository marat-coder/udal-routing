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


def assert_no_forbidden_keys(value, forbidden, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden:
                raise SystemExit(f"FAIL: volatile runtime field in manifest: {path + key}")
            assert_no_forbidden_keys(child, forbidden, path + key + ".")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_forbidden_keys(child, forbidden, f"{path}{index}.")


p = argparse.ArgumentParser()
p.add_argument("--bundle", required=True)
p.add_argument("--policy", required=True)
p.add_argument("--contract", required=True)
p.add_argument("--manifest-config", required=True)
p.add_argument("--toolchain-lock", required=True)
p.add_argument("--provenance", required=True)
p.add_argument("--repo", required=True)
p.add_argument("--tag", required=True)
p.add_argument("--previous-production", required=True)
p.add_argument("--last-updated", type=int, required=True)
p.add_argument("--input-fingerprint", required=True)
a = p.parse_args()

bundle = Path(a.bundle)
policy_path = Path(a.policy)
contract_path = Path(a.contract)
manifest_config_path = Path(a.manifest_config)
toolchain_path = Path(a.toolchain_lock)
provenance_path = Path(a.provenance)

policy = json.loads(policy_path.read_text(encoding="utf-8"))
contract = json.loads(contract_path.read_text(encoding="utf-8"))
manifest_config = json.loads(manifest_config_path.read_text(encoding="utf-8"))
toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

if policy["proxyIp"] != contract["proxyIpExact"]:
    raise SystemExit("FAIL: ProxyIp exact contract mismatch")
if contract["broadRuBlockedGeoipActive"] is not False:
    raise SystemExit("FAIL: broad geoip:ru-blocked contract must remain false")

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
if manifest.get("manifestSchema") != manifest_config["productionManifestSchema"] or manifest["manifestSchema"] != 2:
    raise SystemExit("FAIL: manifest schema")
if manifest.get("revision") != a.tag:
    raise SystemExit("FAIL: manifest revision")
if manifest.get("status") != "PRODUCTION" or manifest.get("importAllowed") is not True:
    raise SystemExit("FAIL: manifest production gate")
if "automation" in manifest:
    raise SystemExit("FAIL: legacy automation block is forbidden in manifest v2")

assert_no_forbidden_keys(manifest, set(manifest_config["forbiddenRuntimeFields"]))

expected_plan = {
    "targetRelease": a.tag,
    "previousProductionRelease": a.previous_production,
    "routingLastUpdated": a.last_updated,
    "inputFingerprint": a.input_fingerprint,
}
if manifest.get("buildPlan") != expected_plan:
    raise SystemExit("FAIL: manifest deterministic build plan")

if manifest.get("source") != provenance:
    raise SystemExit("FAIL: manifest source provenance")

expected_toolchain = {"sha256": sha256(toolchain_path), "lock": toolchain}
if manifest.get("toolchain") != expected_toolchain:
    raise SystemExit("FAIL: manifest toolchain lock")

expected_policy = {
    "sha256": sha256(policy_path),
    "geositeTotal": len(policy["geositeTopLevel"]),
    "proxySites": policy["proxySites"],
    "geositeReserve": policy["geositeReserve"],
    "proxyIp": policy["proxyIp"],
    "directIp": policy["directIp"],
    "blockSites": policy["blockSites"],
    "blockIp": policy["blockIp"],
    "globalProxy": policy["globalProxy"],
    "routeOrder": policy["routeOrder"],
    "useChunkFiles": policy["useChunkFiles"],
    "domainStrategy": policy["domainStrategy"],
    "fakeDns": policy["fakeDns"],
}
if manifest.get("routingPolicy") != expected_policy:
    raise SystemExit("FAIL: manifest routing policy")

expected_contract = {
    "sha256": sha256(contract_path),
    "geositeTotal": contract["geositeTotal"],
    "proxySitesActive": contract["proxySitesActive"],
    "geositeReserve": contract["geositeReserve"],
    "proxyIpExact": contract["proxyIpExact"],
    "broadRuBlockedGeoipActive": contract["broadRuBlockedGeoipActive"],
}
if manifest.get("validationContract") != expected_contract:
    raise SystemExit("FAIL: manifest validation contract")

if manifest.get("safety", {}).get("offlinePlaceholderUrls") is not False:
    raise SystemExit("FAIL: manifest placeholder safety")
if manifest.get("safety", {}).get("autoPublish") is not False:
    raise SystemExit("FAIL: manifest auto publish safety")

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
print("MANIFEST_SCHEMA_V2=PASS")
print("MANIFEST_RUNTIME_FIELDS_ABSENT=PASS")
print("MANIFEST_VALIDATION=PASS")
print("SHA256_VALIDATION=PASS")
print("VALIDATE_ARTIFACTS=PASS")
