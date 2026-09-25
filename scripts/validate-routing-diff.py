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

expected_proxy_ip = ["geoip:telegram", "geoip:facebook"]
if base.get("ProxyIp") != expected_proxy_ip:
    raise SystemExit("FAIL: unexpected baseline ProxyIp")
if cand.get("ProxyIp") != expected_proxy_ip:
    raise SystemExit("FAIL: candidate ProxyIp mismatch")
if "geoip:ru-blocked" in cand.get("ProxyIp", []):
    raise SystemExit("FAIL: broad geoip:ru-blocked is active")

keys = sorted(set(base) | set(cand))
changed = [k for k in keys if base.get(k) != cand.get(k)]
expected = {"Geoipurl", "Geositeurl", "LastUpdated"}

if set(changed) != expected:
    raise SystemExit(f"FAIL: unexpected routing semantic diff: {changed}")

print("ROUTING_SEMANTIC_DIFF_KEYS=" + ",".join(changed))
print("ROUTING_PROXYIP=geoip:telegram,geoip:facebook")
print("ROUTING_SEMANTIC_DIFF=PASS")
