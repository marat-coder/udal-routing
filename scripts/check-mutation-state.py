#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

FP_RE=re.compile(r"(?m)^INPUT_FINGERPRINT=([0-9a-f]{64})$")
TAG_RE=re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d+$")

p=argparse.ArgumentParser()
p.add_argument("--releases-json",required=True)
p.add_argument("--planned-tag",required=True)
p.add_argument("--fingerprint",required=True)
p.add_argument("--output",required=True)
a=p.parse_args()

try:
    releases=json.loads(Path(a.releases_json).read_text())
except Exception:
    raise SystemExit("FAIL: malformed release inventory")
if not isinstance(releases,list):
    raise SystemExit("FAIL: release inventory must be a list")
if not TAG_RE.fullmatch(a.planned_tag):
    raise SystemExit("FAIL: planned tag invalid")
if not re.fullmatch(r"[0-9a-f]{64}",a.fingerprint):
    raise SystemExit("FAIL: fingerprint invalid")

matching=[]
for r in releases:
    tag=r.get("tag_name","")
    if tag==a.planned_tag:
        raise SystemExit(f"FAIL: planned tag already exists as release/draft: {tag}")
    if not TAG_RE.fullmatch(tag):
        continue
    if r.get("draft") is True:
        m=FP_RE.search(r.get("body") or "")
        if not m:
            raise SystemExit(f"FAIL: versioned draft lacks fingerprint marker: {tag}")
        if m.group(1)==a.fingerprint:
            matching.append(tag)

if len(matching)>1:
    raise SystemExit("FAIL: multiple stale drafts match current fingerprint")
if matching:
    raise SystemExit(f"FAIL: STALE_DRAFT_REVALIDATION_REQUIRED:{matching[0]}")

out={"staleDraftMatch":False,"plannedTagCollision":False,"result":"PASS"}
Path(a.output).write_text(json.dumps(out,indent=2)+"\n")
print("STALE_DRAFT_MATCH=false")
print("PLANNED_TAG_COLLISION=false")
print("MUTATION_STATE=PASS")
