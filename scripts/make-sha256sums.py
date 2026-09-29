#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

p=argparse.ArgumentParser()
p.add_argument("--bundle",required=True)
p.add_argument("--build-contract",required=True)
a=p.parse_args()
bundle=Path(a.bundle)
contract=json.loads(Path(a.build_contract).read_text())
order=contract["sha256SumsOrder"]
lines=[]
for name in order:
    path=bundle/name
    if not path.is_file(): raise SystemExit(f"FAIL: missing {name}")
    lines.append(f"{sha256(path)}  {name}\n")
(bundle/"SHA256SUMS").write_text("".join(lines),encoding="utf-8",newline="\n")
print(f"SHA256SUMS_ENTRY_COUNT={len(order)}")
print("MAKE_SHA256SUMS=PASS")
