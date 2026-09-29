#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

p=argparse.ArgumentParser()
for n in ("release-json","bundle","remote-dir","build-contract"): p.add_argument("--"+n,required=True)
a=p.parse_args()
r=json.loads(Path(a.release_json).read_text())
bundle=Path(a.bundle); remote=Path(a.remote_dir); bc=json.loads(Path(a.build_contract).read_text())
expected=set(bc["artifactSet"])
if r.get("draft") is not True or r.get("published_at") is not None: raise SystemExit("FAIL: release is not draft")
assets=r.get("assets",[])
if {x.get("name") for x in assets}!=expected: raise SystemExit("FAIL: remote draft asset set")
by={x["name"]:x for x in assets}
if {x.name for x in remote.iterdir() if x.is_file()}!=expected: raise SystemExit("FAIL: downloaded draft asset set")
for name in expected:
    local=sha(bundle/name)
    if by[name].get("digest")!="sha256:"+local: raise SystemExit(f"FAIL: remote digest mismatch {name}")
    if sha(remote/name)!=local: raise SystemExit(f"FAIL: downloaded draft mismatch {name}")
print("REMOTE_DRAFT_DIGESTS=PASS")
print("REMOTE_DRAFT_DOWNLOAD=PASS")
print("VERIFY_DRAFT_RELEASE=PASS")
