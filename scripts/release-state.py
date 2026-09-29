#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HEX64=re.compile(r"^[0-9a-f]{64}$")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--current-production",required=True)
    p.add_argument("--current-fingerprint",required=True)
    p.add_argument("--run-number",required=True,type=int)
    p.add_argument("--output",required=True)
    a=p.parse_args()

    prod=json.loads(Path(a.current_production).read_text(encoding="utf-8"))
    current_fp=a.current_fingerprint.lower()
    if not HEX64.fullmatch(current_fp):
        raise SystemExit("FAIL: invalid current fingerprint")
    prod_fp=prod.get("inputFingerprint")
    if not isinstance(prod_fp,str) or not HEX64.fullmatch(prod_fp):
        raise SystemExit("FAIL: current production fingerprint missing")
    tag=prod.get("tag")
    if not isinstance(tag,str) or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+",tag):
        raise SystemExit("FAIL: current production tag invalid")
    last=prod.get("lastUpdated")
    if not isinstance(last,int):
        raise SystemExit("FAIL: current production LastUpdated invalid")
    if a.run_number < 1:
        raise SystemExit("FAIL: run number invalid")

    prefix=datetime.now(timezone.utc).strftime("%Y.%m.%d.")
    new_tag=f"{prefix}{a.run_number}"
    state={
        "previousProductionRelease":tag,
        "maxLastUpdated":last,
        "nextLastUpdatedFloor":last+1,
        "noChanges":current_fp==prod_fp,
        "publishedFingerprintMatch":current_fp==prod_fp,
        "newTag":new_tag,
    }
    Path(a.output).write_text(json.dumps(state,indent=2)+"\n",encoding="utf-8")
    print(f"PREVIOUS_PRODUCTION={tag}")
    print(f"MAX_LAST_UPDATED={last}")
    print(f"NEW_TAG={new_tag}")
    print(f"NO_CHANGES={str(state['noChanges']).lower()}")
    print("RELEASE_STATE=PASS")

if __name__=="__main__":
    main()
