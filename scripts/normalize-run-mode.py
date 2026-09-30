#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

def parse_bool(value, default, label):
    if value is None or value == "":
        return default
    v=value.strip().lower()
    if v=="true":
        return True
    if v=="false":
        return False
    raise SystemExit(f"FAIL: invalid {label}: {value}")

def normalize(event, baseline=None, dry_run=None, manifest_test=None):
    if event=="pull_request":
        return {
            "run_mode":"ci",
            "baseline_reproduction":False,
            "dry_run":True,
            "manifest_test":False,
            "auto_publish":False,
            "run_build":False,
        }
    if event=="schedule":
        return {
            "run_mode":"scheduled",
            "baseline_reproduction":False,
            "dry_run":False,
            "manifest_test":False,
            "auto_publish":True,
            "run_build":True,
        }
    if event=="workflow_dispatch":
        base=parse_bool(baseline,False,"baseline_reproduction")
        dry=parse_bool(dry_run,True,"dry_run")
        mtest=parse_bool(manifest_test,False,"manifest_v2_determinism_test")
        if mtest:
            mode="manifest-test"
            build=False
        elif base:
            mode="baseline"
            build=True
        else:
            mode="manual"
            build=True
        return {
            "run_mode":mode,
            "baseline_reproduction":base,
            "dry_run":dry,
            "manifest_test":mtest,
            "auto_publish":False,
            "run_build":build,
        }
    raise SystemExit(f"FAIL: unsupported event {event}")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--event",required=True)
    p.add_argument("--baseline")
    p.add_argument("--dry-run")
    p.add_argument("--manifest-test")
    p.add_argument("--github-output")
    p.add_argument("--json-output")
    a=p.parse_args()
    out=normalize(a.event,a.baseline,a.dry_run,a.manifest_test)
    if a.github_output:
        with Path(a.github_output).open("a",encoding="utf-8") as f:
            for k,v in out.items():
                if isinstance(v,bool):
                    v=str(v).lower()
                f.write(f"{k}={v}\n")
    if a.json_output:
        Path(a.json_output).write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print("RUN_MODE="+out["run_mode"])
    print("NORMALIZE_RUN_MODE=PASS")

if __name__=="__main__":
    main()
