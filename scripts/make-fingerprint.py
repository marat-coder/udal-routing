#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


p = argparse.ArgumentParser()
p.add_argument("--provenance", required=True)
p.add_argument("--relevant-hash", required=True)
g = p.add_mutually_exclusive_group(required=True)
g.add_argument("--policy")
g.add_argument("--policy-sha")
p.add_argument("--output", required=True)
a = p.parse_args()

prov = json.loads(Path(a.provenance).read_text(encoding="utf-8"))

if a.policy:
    policy_sha = hashlib.sha256(Path(a.policy).read_bytes()).hexdigest()
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
canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
fp = hashlib.sha256(canonical).hexdigest()
prov["inputFingerprint"] = fp

Path(a.output).write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
print(f"ROUTING_POLICY_SHA256={policy_sha}")
print(f"INPUT_FINGERPRINT={fp}")
