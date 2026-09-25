#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path

ORDER = ["UDAL-GEOSITE.dat", "UDAL-GEOIP.dat", "UDAL-ROUTING.json", "MANIFEST.json"]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


p = argparse.ArgumentParser()
p.add_argument("--bundle", required=True)
a = p.parse_args()
bundle = Path(a.bundle)

lines = []
for name in ORDER:
    path = bundle / name
    if not path.is_file():
        raise SystemExit(f"FAIL: missing {name}")
    lines.append(f"{sha256(path)}  {name}\n")

(bundle / "SHA256SUMS").write_text("".join(lines), encoding="utf-8", newline="\n")
print("SHA256SUMS_ENTRY_COUNT=4")
print("MAKE_SHA256SUMS=PASS")
