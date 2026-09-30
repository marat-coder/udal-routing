#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

p=argparse.ArgumentParser()
for n in ("release-json","bundle","build-contract","expected-rid","expected-tag"):
    p.add_argument("--"+n,required=True)
p.add_argument("--remote-dir")
a=p.parse_args()

try:
    r=json.loads(Path(a.release_json).read_text())
except Exception:
    raise SystemExit("FAIL: malformed draft release JSON")
bundle=Path(a.bundle)
bc=json.loads(Path(a.build_contract).read_text())
expected=set(bc["artifactSet"])

try:
    expected_rid=int(a.expected_rid)
except ValueError:
    raise SystemExit("FAIL: expected RID invalid")
if r.get("id")!=expected_rid:
    raise SystemExit("FAIL: draft RID mismatch")
if r.get("tag_name")!=a.expected_tag:
    raise SystemExit("FAIL: draft tag mismatch")
if r.get("draft") is not True or r.get("published_at") is not None:
    raise SystemExit("FAIL: release is not draft")
if r.get("prerelease") is not False:
    raise SystemExit("FAIL: draft is prerelease")

assets=r.get("assets",[])
if {x.get("name") for x in assets}!=expected or len(assets)!=len(expected):
    raise SystemExit("FAIL: remote draft asset set")
by={x["name"]:x for x in assets}
for name in expected:
    local=bundle/name
    if not local.is_file():
        raise SystemExit(f"FAIL: local bundle missing {name}")
    local_sha=sha(local)
    if by[name].get("digest")!="sha256:"+local_sha:
        raise SystemExit(f"FAIL: remote digest mismatch {name}")
    if by[name].get("size")!=local.stat().st_size:
        raise SystemExit(f"FAIL: remote size mismatch {name}")

if a.remote_dir:
    remote=Path(a.remote_dir)
    if {x.name for x in remote.iterdir() if x.is_file()}!=expected:
        raise SystemExit("FAIL: downloaded draft asset set")
    for name in expected:
        if sha(remote/name)!=sha(bundle/name):
            raise SystemExit(f"FAIL: downloaded draft mismatch {name}")
    print("REMOTE_DRAFT_DOWNLOAD=PASS")

print("DRAFT_RID_BINDING=PASS")
print("DRAFT_TAG_BINDING=PASS")
print("REMOTE_DRAFT_DIGESTS=PASS")
print("VERIFY_DRAFT_RELEASE=PASS")
