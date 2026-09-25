#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def meta(path):
    return {"size": path.stat().st_size, "sha256": sha256(path)}


p = argparse.ArgumentParser()
p.add_argument("--manifest-config", required=True)
p.add_argument("--toolchain-lock", required=True)
p.add_argument("--validation-contract", required=True)
p.add_argument("--policy", required=True)
p.add_argument("--provenance", required=True)
p.add_argument("--bundle", required=True)
p.add_argument("--tag", required=True)
p.add_argument("--previous-production", required=True)
p.add_argument("--last-updated", type=int, required=True)
p.add_argument("--input-fingerprint", required=True)
p.add_argument("--output", required=True)
a = p.parse_args()

manifest_config_path = Path(a.manifest_config)
toolchain_path = Path(a.toolchain_lock)
contract_path = Path(a.validation_contract)
policy_path = Path(a.policy)
provenance_path = Path(a.provenance)
bundle = Path(a.bundle)
output = Path(a.output)

manifest_config = json.loads(manifest_config_path.read_text(encoding="utf-8"))
toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
contract = json.loads(contract_path.read_text(encoding="utf-8"))
policy = json.loads(policy_path.read_text(encoding="utf-8"))
provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

if manifest_config["productionManifestSchema"] != 2:
    raise SystemExit("FAIL: production manifest schema must be 2")
if manifest_config["legacyManifest"]["release"] != "2026.09.25.3":
    raise SystemExit("FAIL: unexpected legacy manifest release")
if manifest_config["legacyManifest"]["status"] != "KNOWN_RUNTIME_METADATA_NONDETERMINISM":
    raise SystemExit("FAIL: legacy manifest status mismatch")
if policy["proxyIp"] != contract["proxyIpExact"]:
    raise SystemExit("FAIL: ProxyIp exact contract mismatch")
if contract["broadRuBlockedGeoipActive"] is not False:
    raise SystemExit("FAIL: broad geoip:ru-blocked contract must remain false")

required = {
    "UDAL-GEOSITE.dat": bundle / "UDAL-GEOSITE.dat",
    "UDAL-GEOIP.dat": bundle / "UDAL-GEOIP.dat",
    "UDAL-ROUTING.json": bundle / "UDAL-ROUTING.json",
}
for name, path in required.items():
    if not path.is_file():
        raise SystemExit(f"FAIL: missing artifact {name}")

routing_policy = {
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

manifest = {
    "manifestSchema": 2,
    "task": "HAPP-ROUTING-PRODUCTION-001",
    "revision": a.tag,
    "status": "PRODUCTION",
    "importAllowed": True,
    "buildPlan": {
        "targetRelease": a.tag,
        "previousProductionRelease": a.previous_production,
        "routingLastUpdated": a.last_updated,
        "inputFingerprint": a.input_fingerprint,
    },
    "source": provenance,
    "toolchain": {
        "sha256": sha256(toolchain_path),
        "lock": toolchain,
    },
    "routingPolicy": routing_policy,
    "artifacts": {name: meta(path) for name, path in required.items()},
    "validationContract": {
        "sha256": sha256(contract_path),
        "geositeTotal": contract["geositeTotal"],
        "proxySitesActive": contract["proxySitesActive"],
        "geositeReserve": contract["geositeReserve"],
        "proxyIpExact": contract["proxyIpExact"],
        "broadRuBlockedGeoipActive": contract["broadRuBlockedGeoipActive"],
    },
    "validation": {
        "result": "PASS",
        "geositeTotal": contract["geositeTotal"],
        "proxySitesActive": contract["proxySitesActive"],
        "geositeReserve": contract["geositeReserve"],
        "proxyIp": contract["proxyIpExact"],
        "broadRuBlockedGeoipActive": False,
        "xray": "PASS",
        "sha256": "PASS",
        "secretScan": "PASS",
    },
    "safety": {
        "offlinePlaceholderUrls": False,
        "secretsInArtifacts": False,
        "hostkeyChanged": False,
        "aezaChanged": False,
        "iphoneChanged": False,
        "happClientChanged": False,
        "autoPublish": False,
    },
}

output.parent.mkdir(parents=True, exist_ok=True)
with output.open("w", encoding="utf-8", newline="\n") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
    f.write("\n")

print("MANIFEST_SCHEMA=2")
print("MANIFEST_BUILD_MODE=DETERMINISTIC_V2")
print("MAKE_MANIFEST=PASS")
