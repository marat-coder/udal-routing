#!/usr/bin/env python3
import argparse, json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument("--baseline",required=True)
p.add_argument("--provenance",required=True)
p.add_argument("--build-contract",required=True)
p.add_argument("--output",required=True)
a=p.parse_args()

baseline=json.loads(Path(a.baseline).read_text())
prov=json.loads(Path(a.provenance).read_text())
contract=json.loads(Path(a.build_contract).read_text())
legacy=contract["legacyProductionContract"]

reasons=[]
if prov["domainListCommunity"]["relevantHash"] != legacy["relevantHash"]:
    reasons.append("V2FLY_RELEVANT")
if prov["ruBlockedGeosite"]["sha256"] != baseline["sources"]["ruBlockedGeosite"]["sha256"]:
    reasons.append("RU_BLOCKED_CONTENT")
if prov["geoip"]["sha256"] != baseline["sources"]["geoip"]["sha256"]:
    reasons.append("GEOIP_CONTENT")
if prov["routingPolicySha256"] != baseline["routingPolicySha256"]:
    reasons.append("ROUTING_POLICY")
if contract["contractId"] != legacy["buildContractId"]:
    reasons.append("BUILD_CONTRACT")
if contract["urlModel"]["id"] != legacy["urlModelId"]:
    reasons.append("URL_MODEL")

eligible=set(contract["changePolicy"]["scheduledAutoPublishEligibleReasons"])
blocked=set(contract["changePolicy"]["scheduledAutoPublishBlockedReasons"])
unknown=set(reasons)-eligible-blocked
if unknown:
    raise SystemExit(f"FAIL: unclassified change reasons: {sorted(unknown)}")
scheduled=bool(reasons) and set(reasons).issubset(eligible)
out={"changeDetected":bool(reasons),"changeReasons":reasons,"scheduledAutoPublishEligible":scheduled,"upstreamContentOnly":scheduled}
Path(a.output).write_text(json.dumps(out,indent=2)+"\n")
print("CHANGE_DETECTED="+("YES" if reasons else "NO"))
print("CHANGE_REASONS="+(",".join(reasons) if reasons else "NONE"))
print("SCHEDULED_AUTO_PUBLISH_ELIGIBLE="+("YES" if scheduled else "NO"))
print("CLASSIFY_CHANGE=PASS")
