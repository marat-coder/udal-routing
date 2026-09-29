#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def verify_assets(release,bundle,expected):
    assets=release.get("assets",[])
    if {a.get("name") for a in assets}!=expected: raise SystemExit("FAIL: published release asset set mismatch")
    by={a["name"]:a for a in assets}
    for name in expected:
        path=bundle/name
        if not path.is_file(): raise SystemExit(f"FAIL: local bundle missing {name}")
        if by[name].get("digest")!="sha256:"+sha256(path): raise SystemExit(f"FAIL: published digest mismatch {name}")

p=argparse.ArgumentParser()
for n in ("release-json","latest-json","bundle","latest-dir","build-contract","tag"): p.add_argument("--"+n,required=True)
a=p.parse_args()
release=json.loads(Path(a.release_json).read_text()); latest=json.loads(Path(a.latest_json).read_text())
bc=json.loads(Path(a.build_contract).read_text()); bundle=Path(a.bundle); latest_dir=Path(a.latest_dir); expected=set(bc["artifactSet"])
if release.get("tag_name")!=a.tag: raise SystemExit("FAIL: published tag mismatch")
if release.get("draft") is not False or not release.get("published_at"): raise SystemExit("FAIL: release is not published")
if release.get("prerelease") is not False: raise SystemExit("FAIL: release is prerelease")
if "immutable" in release and release.get("immutable") is not True: raise SystemExit("FAIL: published release not immutable")
verify_assets(release,bundle,expected)
if latest.get("tag_name")!=a.tag or latest.get("draft") is not False: raise SystemExit("FAIL: releases/latest tag mismatch")
if {x.get("name") for x in latest.get("assets",[])}!=expected: raise SystemExit("FAIL: latest asset set mismatch")
for name in ("UDAL-GEOIP.dat","UDAL-GEOSITE.dat"):
    if sha256(latest_dir/name)!=sha256(bundle/name): raise SystemExit(f"FAIL: latest stable asset bytes mismatch {name}")
print("POST_PUBLISH_STATE=PASS")
print("POST_PUBLISH_ASSET_DIGESTS=PASS")
print("LATEST_RELEASE_TAG=PASS")
print("LATEST_GEO_ASSET_BYTES=PASS")
print("VERIFY_PUBLISHED_RELEASE=PASS")
