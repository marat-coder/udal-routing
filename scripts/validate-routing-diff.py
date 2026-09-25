#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--baseline", required=True)
p.add_argument("--candidate", required=True)
a = p.parse_args()

base = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
cand = json.loads(Path(a.candidate).read_text(encoding="utf-8"))

if base.get("ProxyIp") != ["geoip:telegram"]:
    raise SystemExit("FAIL: unexpected baseline ProxyIp")
if cand.get("ProxyIp") != ["geoip:telegram", "geoip:facebook"]:
    raise SystemExit("FAIL: candidate ProxyIp mismatch")
if "geoip:ru-blocked" in cand.get("ProxyIp", []):
    raise SystemExit("FAIL: broad geoip:ru-blocked is active")

keys = sorted(set(base) | set(cand))
changed = [k for k in keys if base.get(k) != cand.get(k)]
expected = {"ProxyIp", "Geoipurl", "Geositeurl", "LastUpdated"}

if set(changed) != expected:
    raise SystemExit(f"FAIL: unexpected routing semantic diff: {changed}")

print("ROUTING_SEMANTIC_DIFF_KEYS=" + ",".join(changed))
print("ROUTING_PROXYIP_DIFF=geoip:telegram,+geoip:facebook")
print("ROUTING_SEMANTIC_DIFF=PASS")
