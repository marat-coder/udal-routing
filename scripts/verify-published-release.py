#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def verify_assets(release,bundle,expected):
    assets=release.get("assets",[])
    if {a.get("name") for a in assets}!=expected or len(assets)!=len(expected):
        raise SystemExit("FAIL: published release asset set mismatch")
    by={a["name"]:a for a in assets}
    for name in expected:
        path=bundle/name
        if not path.is_file():
            raise SystemExit(f"FAIL: local bundle missing {name}")
        if by[name].get("digest")!="sha256:"+sha256(path):
            raise SystemExit(f"FAIL: published digest mismatch {name}")
        if by[name].get("size")!=path.stat().st_size:
            raise SystemExit(f"FAIL: published size mismatch {name}")

p=argparse.ArgumentParser()
for n in ("release-json","latest-json","bundle","latest-dir","build-contract","tag","release-id"):
    p.add_argument("--"+n,required=True)
a=p.parse_args()

release=json.loads(Path(a.release_json).read_text())
latest=json.loads(Path(a.latest_json).read_text())
bc=json.loads(Path(a.build_contract).read_text())
bundle=Path(a.bundle)
latest_dir=Path(a.latest_dir)
expected=set(bc["artifactSet"])
try:
    rid=int(a.release_id)
except ValueError:
    raise SystemExit("FAIL: release id invalid")

if release.get("id")!=rid:
    raise SystemExit("FAIL: published RID mismatch")
if release.get("tag_name")!=a.tag:
    raise SystemExit("FAIL: published tag mismatch")
if release.get("draft") is not False or not release.get("published_at"):
    raise SystemExit("FAIL: release is not published")
if release.get("prerelease") is not False:
    raise SystemExit("FAIL: release is prerelease")
if release.get("immutable") is not True:
    raise SystemExit("FAIL: published release immutable=true not proven")
verify_assets(release,bundle,expected)

if latest.get("id")!=rid or latest.get("tag_name")!=a.tag or latest.get("draft") is not False:
    raise SystemExit("FAIL: releases/latest identity mismatch")
if latest.get("prerelease") is not False:
    raise SystemExit("FAIL: latest release is prerelease")
if {x.get("name") for x in latest.get("assets",[])}!=expected:
    raise SystemExit("FAIL: latest release asset set mismatch")

for name in ("UDAL-GEOIP.dat","UDAL-GEOSITE.dat"):
    if sha256(latest_dir/name)!=sha256(bundle/name):
        raise SystemExit(f"FAIL: latest stable asset bytes mismatch {name}")

print("POST_PUBLISH_RID_BINDING=PASS")
print("POST_PUBLISH_IMMUTABLE=PASS")
print("POST_PUBLISH_ASSET_DIGESTS=PASS")
print("LATEST_RELEASE_TAG=PASS")
print("LATEST_GEO_ASSET_BYTES=PASS")
print("VERIFY_PUBLISHED_RELEASE=PASS")
