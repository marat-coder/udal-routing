import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PY=sys.executable
REPO="marat-coder/udal-routing"
TAG="2099.01.01.1"
LAST=1790327433
FP="1"*64
REL="b"*64
RU="c"*64
GEO="d"*64

POLICY=ROOT/"config/routing-policy.json"
BUILD_CONTRACT=ROOT/"config/build-contract.json"
MANIFEST_CONFIG=ROOT/"config/manifest-schema-v2.json"
TOOLCHAIN=ROOT/"config/toolchain-lock.json"
VALIDATION=ROOT/"config/validation-contract.json"
BASELINE=ROOT/"config/baseline-2026.09.25.3.json"

def load_script(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

build_routing=load_script("build_routing_common","build-routing.py")

def run(*args,check=True,env=None):
    p=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,env=env)
    if check and p.returncode!=0:
        raise AssertionError(f"command failed: {args}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def base_provenance(build_contract_path=BUILD_CONTRACT):
    contract=json.loads(Path(build_contract_path).read_text())
    policy_sha=sha(POLICY)
    build_sha=sha(build_contract_path)
    return {
        "domainListCommunity":{
            "repository":"v2fly/domain-list-community",
            "commit":"a"*40,
            "timestamp":"2099-01-01T00:00:00Z",
            "relevantHash":REL,
        },
        "ruBlockedGeosite":{
            "repository":"runetfreedom/russia-blocked-geosite",
            "release":"209901010000",
            "asset":"ru-blocked.txt",
            "size":1,
            "sha256":RU,
            "publishedAt":"2099-01-01T00:00:00Z",
        },
        "geoip":{
            "repository":"runetfreedom/russia-blocked-geoip",
            "release":"209901010001",
            "asset":"geoip.dat",
            "size":1,
            "sha256":GEO,
            "publishedAt":"2099-01-01T00:00:01Z",
            "model":"FULL_PINNED_RUNETFREEDOM_BYTE_FOR_BYTE",
        },
        "routingPolicySha256":policy_sha,
        "fingerprintSchema":2,
        "buildContractSha256":build_sha,
        "buildContractId":contract["contractId"],
        "urlModelId":contract["urlModel"]["id"],
        "inputFingerprint":FP,
        "fingerprintComponents":{
            "v2flyRelevantHash":REL,
            "ruBlockedSha256":RU,
            "geoipSha256":GEO,
            "routingPolicySha256":policy_sha,
            "buildContractSha256":build_sha,
        },
    }

def make_bundle(root,tag=TAG,last=LAST,fp=FP,provenance=None,build_contract_path=BUILD_CONTRACT):
    root=Path(root)
    bundle=root/"bundle"
    bundle.mkdir(parents=True,exist_ok=True)
    (bundle/"UDAL-GEOSITE.dat").write_bytes(b"synthetic-geosite-v2\n")
    (bundle/"UDAL-GEOIP.dat").write_bytes(b"synthetic-geoip-v2\n")
    policy=json.loads(POLICY.read_text())
    template=build_routing.desired(policy,REPO,"2026.09.25.3",1790327432,"snapshot")
    template_path=root/"template.json"
    template_path.write_text(json.dumps(template,indent=2)+"\n")
    for mode,name in (("snapshot","UDAL-ROUTING.json"),("live","UDAL-ROUTING-LIVE.json")):
        run(PY,"scripts/build-routing.py",
            "--template",str(template_path),"--policy",str(POLICY),"--repo",REPO,
            "--tag",tag,"--url-mode",mode,"--last-updated",str(last),
            "--output",str(bundle/name))
    prov=dict(base_provenance(build_contract_path) if provenance is None else provenance)
    prov["inputFingerprint"]=fp
    prov_path=root/"provenance.json"
    prov_path.write_text(json.dumps(prov,indent=2)+"\n")
    run(PY,"scripts/make-manifest.py",
        "--manifest-config",str(MANIFEST_CONFIG),
        "--build-contract",str(build_contract_path),
        "--toolchain-lock",str(TOOLCHAIN),
        "--validation-contract",str(VALIDATION),
        "--policy",str(POLICY),
        "--provenance",str(prov_path),
        "--bundle",str(bundle),
        "--tag",tag,
        "--previous-production","2026.09.25.3",
        "--last-updated",str(last),
        "--input-fingerprint",fp,
        "--output",str(bundle/"MANIFEST.json"))
    run(PY,"scripts/make-sha256sums.py",
        "--bundle",str(bundle),"--build-contract",str(build_contract_path))
    return bundle,prov_path

def validate_bundle(bundle,prov_path,tag=TAG,last=LAST,fp=FP,build_contract_path=BUILD_CONTRACT,check=True):
    return run(PY,"scripts/validate-artifacts.py",
        "--bundle",str(bundle),
        "--policy",str(POLICY),
        "--contract",str(VALIDATION),
        "--manifest-config",str(MANIFEST_CONFIG),
        "--build-contract",str(build_contract_path),
        "--toolchain-lock",str(TOOLCHAIN),
        "--provenance",str(prov_path),
        "--repo",REPO,
        "--tag",tag,
        "--previous-production","2026.09.25.3",
        "--last-updated",str(last),
        "--input-fingerprint",fp,
        check=check)

def release_for_bundle(bundle,tag=TAG,rid=123,draft=False,immutable=True):
    assets=[]
    for i,name in enumerate(json.loads(BUILD_CONTRACT.read_text())["artifactSet"],1):
        p=Path(bundle)/name
        assets.append({
            "id":1000+i,
            "name":name,
            "size":p.stat().st_size,
            "digest":"sha256:"+sha(p),
        })
    r={
        "id":rid,
        "tag_name":tag,
        "draft":draft,
        "prerelease":False,
        "published_at":None if draft else "2099-01-01T00:00:00Z",
        "assets":assets,
    }
    if immutable is not None:
        r["immutable"]=immutable
    return r

def inspect_v2(root,bundle,release,check=True):
    root=Path(root)
    release_path=root/"release.json"
    release_path.write_text(json.dumps(release))
    out=root/"current-production.json"
    p=run(PY,"scripts/inspect-current-production.py",
        "--release-json",str(release_path),
        "--manifest",str(Path(bundle)/"MANIFEST.json"),
        "--routing",str(Path(bundle)/"UDAL-ROUTING.json"),
        "--baseline",str(BASELINE),
        "--build-contract",str(BUILD_CONTRACT),
        "--output",str(out),
        check=check)
    return p,out
