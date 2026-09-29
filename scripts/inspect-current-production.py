#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from pathlib import Path

HEX64=re.compile(r"^[0-9a-f]{64}$")

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def require_hex64(value,label):
    if not isinstance(value,str) or not HEX64.fullmatch(value):
        raise SystemExit(f"FAIL: invalid {label}")
    return value

def load_json(path,label):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        raise SystemExit(f"FAIL: malformed {label}")

def asset_map(release):
    assets=release.get("assets")
    if not isinstance(assets,list):
        raise SystemExit("FAIL: release assets missing")
    names=[x.get("name") for x in assets]
    if len(names)!=len(set(names)):
        raise SystemExit("FAIL: duplicate release asset names")
    return {x.get("name"):x for x in assets}

def require_release_state(release):
    if release.get("draft") is not False:
        raise SystemExit("FAIL: current production is draft")
    if release.get("prerelease") is not False:
        raise SystemExit("FAIL: current production is prerelease")
    if not release.get("published_at"):
        raise SystemExit("FAIL: current production published_at missing")
    if release.get("immutable") is not True:
        raise SystemExit("FAIL: current production immutable contract missing")
    if not isinstance(release.get("id"),int):
        raise SystemExit("FAIL: current production release id missing")
    tag=release.get("tag_name")
    if not isinstance(tag,str) or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+",tag):
        raise SystemExit("FAIL: current production tag invalid")
    return tag

def inspect_legacy(release,manifest_path,routing_path,baseline,contract):
    tag=require_release_state(release)
    legacy=contract["legacyProductionContract"]
    if tag!=legacy["release"] or tag!=baseline["baselineRelease"]:
        raise SystemExit("FAIL: unsupported legacy current production")
    assets=asset_map(release)
    expected=set(contract["legacyAssetSetTags"].get(tag,[]))
    if set(assets)!=expected:
        raise SystemExit("FAIL: legacy current production asset set")
    for name,md in baseline["artifacts"].items():
        a=assets.get(name)
        if not a or a.get("digest")!="sha256:"+md["sha256"] or a.get("size")!=md["size"]:
            raise SystemExit(f"FAIL: legacy production asset metadata mismatch {name}")
    if sha256(manifest_path)!=baseline["artifacts"]["MANIFEST.json"]["sha256"]:
        raise SystemExit("FAIL: legacy MANIFEST bytes mismatch")
    if sha256(routing_path)!=baseline["artifacts"]["UDAL-ROUTING.json"]["sha256"]:
        raise SystemExit("FAIL: legacy routing bytes mismatch")
    routing=load_json(routing_path,"legacy routing")
    if routing.get("LastUpdated")!=baseline["routingLastUpdated"]:
        raise SystemExit("FAIL: legacy routing LastUpdated mismatch")
    fp=require_hex64(baseline["fingerprintContract"]["baselineInputFingerprint"],"legacy fingerprint")
    return {
        "releaseId":release["id"],
        "tag":tag,
        "manifestSchema":1,
        "fingerprintSchema":int(legacy["fingerprintSchema"]),
        "inputFingerprint":fp,
        "lastUpdated":routing["LastUpdated"],
        "v2flyRelevantHash":require_hex64(legacy["relevantHash"],"legacy relevant hash"),
        "ruBlockedSha256":require_hex64(baseline["sources"]["ruBlockedGeosite"]["sha256"],"legacy ru-blocked hash"),
        "geoipSha256":require_hex64(baseline["sources"]["geoip"]["sha256"],"legacy geoip hash"),
        "routingPolicySha256":require_hex64(baseline["routingPolicySha256"],"legacy routing policy hash"),
        "buildContractSha256":None,
        "buildContractId":legacy["buildContractId"],
        "urlModelId":legacy["urlModelId"],
        "assetSetVersion":1,
        "mode":"legacy-v1",
    }

def inspect_v2(release,manifest_path,routing_path,contract):
    tag=require_release_state(release)
    assets=asset_map(release)
    expected=set(contract["artifactSet"])
    if set(assets)!=expected:
        raise SystemExit("FAIL: v2 current production asset set")
    if assets["MANIFEST.json"].get("digest")!="sha256:"+sha256(manifest_path):
        raise SystemExit("FAIL: v2 MANIFEST digest mismatch")
    if assets["UDAL-ROUTING.json"].get("digest")!="sha256:"+sha256(routing_path):
        raise SystemExit("FAIL: v2 routing digest mismatch")

    m=load_json(manifest_path,"v2 manifest")
    routing=load_json(routing_path,"v2 routing")
    if m.get("manifestSchema")!=2:
        raise SystemExit("FAIL: current production manifest schema unsupported")
    if m.get("revision")!=tag or m.get("status")!="PRODUCTION" or m.get("importAllowed") is not True:
        raise SystemExit("FAIL: current production manifest release gate")
    bp=m.get("buildPlan")
    bc=m.get("buildContract")
    src=m.get("source")
    rp=m.get("routingPolicy")
    if not all(isinstance(x,dict) for x in (bp,bc,src,rp)):
        raise SystemExit("FAIL: current production manifest control-plane metadata missing")
    fp=require_hex64(bp.get("inputFingerprint"),"current production fingerprint")
    if bp.get("targetRelease")!=tag:
        raise SystemExit("FAIL: current production targetRelease mismatch")
    if bp.get("routingLastUpdated")!=routing.get("LastUpdated"):
        raise SystemExit("FAIL: current production LastUpdated mismatch")
    if src.get("fingerprintSchema")!=2:
        raise SystemExit("FAIL: current production fingerprint schema")
    relevant=require_hex64(src.get("domainListCommunity",{}).get("relevantHash"),"current production relevant hash")
    ru=require_hex64(src.get("ruBlockedGeosite",{}).get("sha256"),"current production ru-blocked hash")
    geoip=require_hex64(src.get("geoip",{}).get("sha256"),"current production geoip hash")
    policy_sha=require_hex64(rp.get("sha256"),"current production routing policy hash")
    build_sha=require_hex64(bc.get("sha256"),"current production build contract hash")
    if src.get("routingPolicySha256")!=policy_sha:
        raise SystemExit("FAIL: current production routing-policy provenance mismatch")
    if src.get("buildContractSha256")!=build_sha:
        raise SystemExit("FAIL: current production build-contract provenance mismatch")
    if src.get("buildContractId")!=bc.get("contractId"):
        raise SystemExit("FAIL: current production build-contract id mismatch")
    if src.get("urlModelId")!=bc.get("urlModelId"):
        raise SystemExit("FAIL: current production URL-model mismatch")
    artifacts=m.get("artifacts")
    if not isinstance(artifacts,dict):
        raise SystemExit("FAIL: current production manifest artifacts missing")
    for name in contract["preManifestArtifacts"]:
        md=artifacts.get(name)
        a=assets.get(name)
        if not isinstance(md,dict) or not a:
            raise SystemExit(f"FAIL: current production artifact metadata missing {name}")
        if a.get("digest")!="sha256:"+require_hex64(md.get("sha256"),f"{name} manifest hash"):
            raise SystemExit(f"FAIL: current production artifact digest mismatch {name}")
        if a.get("size")!=md.get("size"):
            raise SystemExit(f"FAIL: current production artifact size mismatch {name}")
    return {
        "releaseId":release["id"],
        "tag":tag,
        "manifestSchema":2,
        "fingerprintSchema":2,
        "inputFingerprint":fp,
        "lastUpdated":routing["LastUpdated"],
        "v2flyRelevantHash":relevant,
        "ruBlockedSha256":ru,
        "geoipSha256":geoip,
        "routingPolicySha256":policy_sha,
        "buildContractSha256":build_sha,
        "buildContractId":bc.get("contractId"),
        "urlModelId":bc.get("urlModelId"),
        "assetSetVersion":bc.get("artifactSetVersion"),
        "mode":"v2",
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--release-json",required=True)
    p.add_argument("--manifest",required=True)
    p.add_argument("--routing",required=True)
    p.add_argument("--baseline",required=True)
    p.add_argument("--build-contract",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    release=load_json(a.release_json,"current production release")
    baseline=load_json(a.baseline,"baseline")
    contract=load_json(a.build_contract,"build contract")
    tag=require_release_state(release)
    if tag==baseline["baselineRelease"]:
        out=inspect_legacy(release,a.manifest,a.routing,baseline,contract)
    else:
        out=inspect_v2(release,a.manifest,a.routing,contract)
    Path(a.output).write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(f"CURRENT_PRODUCTION_TAG={out['tag']}")
    print(f"CURRENT_PRODUCTION_MODE={out['mode']}")
    print(f"CURRENT_PRODUCTION_FINGERPRINT_SCHEMA={out['fingerprintSchema']}")
    print("CURRENT_PRODUCTION_INSPECTION=PASS")

if __name__=="__main__":
    main()
