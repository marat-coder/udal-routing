#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


p = argparse.ArgumentParser()
p.add_argument("--provenance", required=True)
p.add_argument("--relevant-hash", required=True)
p.add_argument("--policy", required=True)
p.add_argument("--output", required=True)
a = p.parse_args()

prov_path = Path(a.provenance)
prov = json.loads(prov_path.read_text(encoding="utf-8"))
policy_bytes = Path(a.policy).read_bytes()
policy_sha = hashlib.sha256(policy_bytes).hexdigest()

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
