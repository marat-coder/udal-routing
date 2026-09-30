#!/usr/bin/env python3
import argparse, hashlib, json, re
from pathlib import Path

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def no_runtime_fields(v, forbidden, path=""):
    if isinstance(v,dict):
        for k,x in v.items():
            if k in forbidden: raise SystemExit(f"FAIL: volatile runtime field in manifest: {path+k}")
            no_runtime_fields(x,forbidden,path+k+".")
    elif isinstance(v,list):
        for i,x in enumerate(v): no_runtime_fields(x,forbidden,f"{path}{i}.")

def strip_urls(obj):
    return {k:v for k,v in obj.items() if k not in ("Geoipurl","Geositeurl")}

p=argparse.ArgumentParser()
for n in ("bundle","policy","contract","manifest-config","build-contract","toolchain-lock","provenance","repo","tag","previous-production","input-fingerprint"):
    p.add_argument("--"+n,required=True)
p.add_argument("--last-updated",type=int,required=True)
a=p.parse_args()

bundle=Path(a.bundle); policy_path=Path(a.policy); vc_path=Path(a.contract); mc_path=Path(a.manifest_config)
bc_path=Path(a.build_contract); tc_path=Path(a.toolchain_lock); prov_path=Path(a.provenance)
policy=json.loads(policy_path.read_text()); vc=json.loads(vc_path.read_text()); mc=json.loads(mc_path.read_text())
bc=json.loads(bc_path.read_text()); tc=json.loads(tc_path.read_text()); prov=json.loads(prov_path.read_text())
if a.repo!=bc["repository"]: raise SystemExit("FAIL: repository does not match build contract")
if policy["proxyIp"]!=vc["proxyIpExact"]: raise SystemExit("FAIL: ProxyIp exact contract mismatch")
if vc["broadRuBlockedGeoipActive"] is not False: raise SystemExit("FAIL: broad geoip:ru-blocked contract must remain false")
if {x.name for x in bundle.iterdir() if x.is_file()} != set(bc["artifactSet"]): raise SystemExit("FAIL: asset set mismatch")

snap_path=bundle/bc["urlModel"]["snapshot"]["artifact"]; live_path=bundle/bc["urlModel"]["live"]["artifact"]
manifest_path=bundle/"MANIFEST.json"; sums_path=bundle/"SHA256SUMS"
for path in (snap_path,live_path,manifest_path,sums_path):
    if path.read_bytes().startswith(b"\xef\xbb\xbf"): raise SystemExit(f"FAIL: BOM {path.name}")
snap=json.loads(snap_path.read_text()); live=json.loads(live_path.read_text())
checks={"Name":policy["name"],"GlobalProxy":False,"UseChunkFiles":True,"RouteOrder":"block-direct-proxy",
"DirectSites":policy["directSites"],"DirectIp":policy["directIp"],"ProxySites":policy["proxySites"],"ProxyIp":policy["proxyIp"],
"BlockSites":[],"BlockIp":[],"DomainStrategy":"IPIfNonMatch","FakeDNS":False}
for label,routing in (("snapshot",snap),("live",live)):
    for k,v in checks.items():
        if routing.get(k)!=v: raise SystemExit(f"FAIL: {label} routing mismatch {k}")
    if "geoip:ru-blocked" in routing["ProxyIp"]: raise SystemExit(f"FAIL: broad geoip:ru-blocked active in {label}")
if strip_urls(snap)!=strip_urls(live): raise SystemExit("FAIL: snapshot/live routing semantics differ outside GEO URLs")
print("ROUTING_SEMANTIC_EQUIVALENCE=PASS")

active={x.removeprefix("geosite:") for x in policy["proxySites"]}; reserve=set(policy["geositeReserve"]); top=set(policy["geositeTopLevel"])
if (len(top),len(active),len(reserve))!=(31,22,9) or active|reserve!=top or active&reserve: raise SystemExit("FAIL: 31/22/9 contract mismatch")

prefix=f"https://github.com/{a.repo}/releases/download/{a.tag}"
if snap.get("Geoipurl")!=f"{prefix}/UDAL-GEOIP.dat": raise SystemExit("FAIL: snapshot Geoipurl")
if snap.get("Geositeurl")!=f"{prefix}/UDAL-GEOSITE.dat": raise SystemExit("FAIL: snapshot Geositeurl")
if "/releases/latest/" in snap_path.read_text(): raise SystemExit("FAIL: snapshot must not use latest")
lc=bc["urlModel"]["live"]
if live.get("Geoipurl")!=lc["geoipUrl"]: raise SystemExit("FAIL: live Geoipurl")
if live.get("Geositeurl")!=lc["geositeUrl"]: raise SystemExit("FAIL: live Geositeurl")
latest=set(re.findall(r'https://github\.com/[^\s"\']+/releases/latest/download/[^\s"\']+',live_path.read_text()))
if latest!={lc["geoipUrl"],lc["geositeUrl"]}: raise SystemExit("FAIL: live contains unapproved latest URL")

combined=snap_path.read_text()+"\n"+live_path.read_text()+"\n"+manifest_path.read_text()
for pattern,label in [(r"udal-routing\.invalid","placeholder"),(r"raw\.githubusercontent\.com/[^\s\"']+/main/","raw-main"),(r"(?i)\b[A-Z]:\\","local-path")]:
    if re.search(pattern,combined): raise SystemExit(f"FAIL: forbidden reference {label}")

m=json.loads(manifest_path.read_text())
if m.get("manifestSchema")!=2 or mc["productionManifestSchema"]!=2: raise SystemExit("FAIL: manifest schema")
if m.get("revision")!=a.tag or m.get("status")!="PRODUCTION" or m.get("importAllowed") is not True: raise SystemExit("FAIL: manifest production gate")
if "automation" in m: raise SystemExit("FAIL: legacy automation block forbidden")
no_runtime_fields(m,set(mc["forbiddenRuntimeFields"]))
if m.get("buildPlan")!={"targetRelease":a.tag,"previousProductionRelease":a.previous_production,"routingLastUpdated":a.last_updated,"inputFingerprint":a.input_fingerprint}: raise SystemExit("FAIL: manifest build plan")
if m.get("source")!=prov: raise SystemExit("FAIL: manifest source")
expected_bc={"sha256":sha256(bc_path),"contractId":bc["contractId"],"artifactSetVersion":bc["artifactSetVersion"],"urlModelId":bc["urlModel"]["id"]}
if m.get("buildContract")!=expected_bc: raise SystemExit("FAIL: manifest build contract")
expected_routing_artifacts={
    "snapshot":{"file":bc["urlModel"]["snapshot"]["artifact"],"urlMode":bc["urlModel"]["snapshot"]["mode"]},
    "live":{"file":bc["urlModel"]["live"]["artifact"],"urlMode":bc["urlModel"]["live"]["mode"]}
}
if m.get("routingArtifacts")!=expected_routing_artifacts: raise SystemExit("FAIL: manifest routing artifacts")
expected_toolchain={"sha256":sha256(tc_path),"lock":tc}
if m.get("toolchain")!=expected_toolchain: raise SystemExit("FAIL: manifest toolchain lock")
expected_policy={
    "sha256":sha256(policy_path),"geositeTotal":len(policy["geositeTopLevel"]),
    "proxySites":policy["proxySites"],"geositeReserve":policy["geositeReserve"],"proxyIp":policy["proxyIp"],
    "directIp":policy["directIp"],"blockSites":policy["blockSites"],"blockIp":policy["blockIp"],
    "globalProxy":policy["globalProxy"],"routeOrder":policy["routeOrder"],"useChunkFiles":policy["useChunkFiles"],
    "domainStrategy":policy["domainStrategy"],"fakeDns":policy["fakeDns"]
}
if m.get("routingPolicy")!=expected_policy: raise SystemExit("FAIL: manifest routing policy")
expected_validation_contract={
    "sha256":sha256(vc_path),"geositeTotal":vc["geositeTotal"],"proxySitesActive":vc["proxySitesActive"],
    "geositeReserve":vc["geositeReserve"],"proxyIpExact":vc["proxyIpExact"],
    "broadRuBlockedGeoipActive":vc["broadRuBlockedGeoipActive"]
}
if m.get("validationContract")!=expected_validation_contract: raise SystemExit("FAIL: manifest validation contract")
if m.get("releasePolicy")!=bc["releasePolicy"]: raise SystemExit("FAIL: manifest release policy")
if m.get("safety",{}).get("offlinePlaceholderUrls") is not False: raise SystemExit("FAIL: manifest placeholder safety")
if m.get("validation",{}).get("routingSemanticEquivalence")!="PASS": raise SystemExit("FAIL: manifest routing equivalence marker")
for name in bc["preManifestArtifacts"]:
    md=m.get("artifacts",{}).get(name,{})
    if md.get("sha256")!=sha256(bundle/name) or md.get("size")!=(bundle/name).stat().st_size: raise SystemExit(f"FAIL: manifest artifact metadata {name}")
order=bc["sha256SumsOrder"]; lines=sums_path.read_text().splitlines()
if len(lines)!=len(order): raise SystemExit("FAIL: SHA256SUMS count")
seen=[]
for line in lines:
    mm=re.fullmatch(r"([0-9a-f]{64})  (.+)",line)
    if not mm: raise SystemExit("FAIL: malformed SHA256SUMS")
    digest,name=mm.groups(); seen.append(name)
    if name not in order or digest!=sha256(bundle/name): raise SystemExit(f"FAIL: SHA256SUMS {name}")
if seen!=order: raise SystemExit("FAIL: SHA256SUMS order")
print("EXACT_ASSET_SET=PASS")
print("SNAPSHOT_ROLLBACK_URLS=PASS")
print("LIVE_STABLE_LATEST_URLS=PASS")
print("MANIFEST_VALIDATION=PASS")
print("SHA256_VALIDATION=PASS")
print("VALIDATE_ARTIFACTS=PASS")
