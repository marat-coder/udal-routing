#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path


p = argparse.ArgumentParser()
p.add_argument("--dir", required=True)
p.add_argument("--exclude", action="append", default=[])
a = p.parse_args()

root = Path(a.dir)
excluded = set(a.exclude)
files = sorted(
    x for x in root.iterdir()
    if x.is_file() and x.name not in excluded
)

if not files:
    raise SystemExit("FAIL: no source files to hash")

h = hashlib.sha256()
for path in files:
    data = path.read_bytes()
    digest = hashlib.sha256(data).digest()
    name = path.name.encode("utf-8")
    h.update(len(name).to_bytes(4, "big"))
    h.update(name)
    h.update(len(data).to_bytes(8, "big"))
    h.update(digest)

print(f"SOURCE_FILE_COUNT={len(files)}")
print(f"RELEVANT_HASH={h.hexdigest()}")
