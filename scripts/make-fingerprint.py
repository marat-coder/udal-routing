#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

from fingerprint_v2 import build_fingerprint_v2


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


p = argparse.ArgumentParser()
p.add_argument("--provenance", required=True)
p.add_argument("--relevant-hash", required=True)
g = p.add_mutually_exclusive_group(required=True)
g.add_argument("--policy")
g.add_argument("--policy-sha")
p.add_argument("--fingerprint-schema", choices=["legacy-v1", "v2"], default="legacy-v1")
p.add_argument("--build-contract")
p.add_argument("--output", required=True)
a = p.parse_args()

prov = json.loads(Path(a.provenance).read_text(encoding="utf-8"))

if a.policy:
    policy_sha = file_sha256(a.policy)
else:
    policy_sha = a.policy_sha.lower()
    if len(policy_sha) != 64 or any(c not in "0123456789abcdef" for c in policy_sha):
        raise SystemExit("FAIL: invalid policy SHA256")

prov["domainListCommunity"]["relevantHash"] = a.relevant_hash
prov["routingPolicySha256"] = policy_sha

identity = {
    "v2flyRelevantHash": a.relevant_hash,
    "ruBlockedSha256": prov["ruBlockedGeosite"]["sha256"],
    "geoipSha256": prov["geoip"]["sha256"],
    "routingPolicySha256": policy_sha,
}

if a.fingerprint_schema == "legacy-v1":
    prov["fingerprintSchema"] = 1
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fp = hashlib.sha256(canonical).hexdigest()
    prov["fingerprintComponents"] = identity
else:
    if not a.build_contract:
        raise SystemExit("FAIL: --build-contract is required for fingerprint schema v2")
    build_contract_path = Path(a.build_contract)
    build_contract = json.loads(build_contract_path.read_text(encoding="utf-8"))
    build_sha = file_sha256(build_contract_path)
    try:
        fp, identity = build_fingerprint_v2(
            v2fly_relevant_hash=a.relevant_hash,
            ru_blocked_sha256=prov["ruBlockedGeosite"]["sha256"],
            geoip_sha256=prov["geoip"]["sha256"],
            routing_policy_sha256=policy_sha,
            build_contract_sha256=build_sha,
        )
    except ValueError as e:
        raise SystemExit(f"FAIL: {e}")
    prov["fingerprintSchema"] = 2
    prov["buildContractSha256"] = build_sha
    prov["buildContractId"] = build_contract["contractId"]
    prov["urlModelId"] = build_contract["urlModel"]["id"]
    prov["fingerprintComponents"] = identity

prov["inputFingerprint"] = fp

Path(a.output).write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
print(f"FINGERPRINT_SCHEMA={prov['fingerprintSchema']}")
print(f"ROUTING_POLICY_SHA256={policy_sha}")
if a.fingerprint_schema == "v2":
    print(f"BUILD_CONTRACT_SHA256={prov['buildContractSha256']}")
    print(f"BUILD_CONTRACT_ID={prov['buildContractId']}")
    print(f"URL_MODEL_ID={prov['urlModelId']}")
print(f"INPUT_FINGERPRINT={fp}")
