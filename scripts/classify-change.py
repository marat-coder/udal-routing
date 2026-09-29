#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

HEX64=re.compile(r"^[0-9a-f]{64}$")

def require_hex64(value,label):
    if not isinstance(value,str) or not HEX64.fullmatch(value):
        raise SystemExit(f"FAIL: invalid {label}")
    return value

p=argparse.ArgumentParser()
p.add_argument("--current-production",required=True)
p.add_argument("--provenance",required=True)
p.add_argument("--build-contract",required=True)
p.add_argument("--output",required=True)
a=p.parse_args()

prod=json.loads(Path(a.current_production).read_text())
prov=json.loads(Path(a.provenance).read_text())
contract=json.loads(Path(a.build_contract).read_text())

required_prod=("fingerprintSchema","v2flyRelevantHash","ruBlockedSha256","geoipSha256","routingPolicySha256","buildContractId","urlModelId")
for k in required_prod:
    if k not in prod:
        raise SystemExit(f"FAIL: current production classification field missing: {k}")
for k in ("v2flyRelevantHash","ruBlockedSha256","geoipSha256","routingPolicySha256"):
    require_hex64(prod[k],f"production {k}")

if prov.get("fingerprintSchema")!=2:
    raise SystemExit("FAIL: candidate fingerprint schema must be 2")
candidate_build_sha=require_hex64(prov.get("buildContractSha256"),"candidate build contract hash")
candidate_policy=require_hex64(prov.get("routingPolicySha256"),"candidate routing policy hash")
candidate_relevant=require_hex64(prov.get("domainListCommunity",{}).get("relevantHash"),"candidate relevant hash")
candidate_ru=require_hex64(prov.get("ruBlockedGeosite",{}).get("sha256"),"candidate ru-blocked hash")
candidate_geoip=require_hex64(prov.get("geoip",{}).get("sha256"),"candidate geoip hash")
if prov.get("buildContractId")!=contract.get("contractId"):
    raise SystemExit("FAIL: candidate build-contract id does not match local contract")
if prov.get("urlModelId")!=contract.get("urlModel",{}).get("id"):
    raise SystemExit("FAIL: candidate URL-model id does not match local contract")

reasons=[]
if candidate_relevant!=prod["v2flyRelevantHash"]:
    reasons.append("V2FLY_RELEVANT")
if candidate_ru!=prod["ruBlockedSha256"]:
    reasons.append("RU_BLOCKED_CONTENT")
if candidate_geoip!=prod["geoipSha256"]:
    reasons.append("GEOIP_CONTENT")
if candidate_policy!=prod["routingPolicySha256"]:
    reasons.append("ROUTING_POLICY")

prod_build_sha=prod.get("buildContractSha256")
if prod_build_sha is not None:
    require_hex64(prod_build_sha,"production build contract hash")
if candidate_build_sha!=prod_build_sha or prov.get("buildContractId")!=prod.get("buildContractId"):
    reasons.append("BUILD_CONTRACT")
if prov.get("urlModelId")!=prod.get("urlModelId"):
    reasons.append("URL_MODEL")
if prov.get("fingerprintSchema")!=prod.get("fingerprintSchema"):
    reasons.append("FINGERPRINT_SCHEMA")

eligible=set(contract["changePolicy"]["scheduledAutoPublishEligibleReasons"])
blocked=set(contract["changePolicy"]["scheduledAutoPublishBlockedReasons"])
unknown=set(reasons)-eligible-blocked
if unknown:
    raise SystemExit(f"FAIL: unclassified change reasons: {sorted(unknown)}")
scheduled=bool(reasons) and set(reasons).issubset(eligible)
out={
    "currentProductionTag":prod.get("tag"),
    "changeDetected":bool(reasons),
    "changeReasons":reasons,
    "scheduledAutoPublishEligible":scheduled,
    "upstreamContentOnly":scheduled,
}
Path(a.output).write_text(json.dumps(out,indent=2)+"\n")
print("CHANGE_BASELINE=CURRENT_PUBLISHED_PRODUCTION")
print("CHANGE_DETECTED="+("YES" if reasons else "NO"))
print("CHANGE_REASONS="+(",".join(reasons) if reasons else "NONE"))
print("SCHEDULED_AUTO_PUBLISH_ELIGIBLE="+("YES" if scheduled else "NO"))
print("CLASSIFY_CHANGE=PASS")
