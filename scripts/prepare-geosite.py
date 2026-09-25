#!/usr/bin/env python3
import argparse
import json
import re
import shutil
from pathlib import Path

SAFE_LIST = re.compile(r"^[A-Za-z0-9!_-]+$")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", required=True)
    p.add_argument("--dlc-data", required=True)
    p.add_argument("--ru-blocked", required=True)
    p.add_argument("--output-data", required=True)
    p.add_argument("--datprofile", required=True)
    return p.parse_args()


def load_policy(path: Path):
    with path.open("r", encoding="utf-8") as f:
        policy = json.load(f)

    top = policy["geositeTopLevel"]
    active = [x.removeprefix("geosite:") for x in policy["proxySites"]]
    reserve = policy["geositeReserve"]

    if len(top) != 31 or len(set(top)) != 31:
        raise SystemExit("FAIL: geositeTopLevel must contain exactly 31 unique categories")
    if len(active) != 22 or len(set(active)) != 22:
        raise SystemExit("FAIL: proxySites must contain exactly 22 unique geosite categories")
    if len(reserve) != 9 or len(set(reserve)) != 9:
        raise SystemExit("FAIL: geositeReserve must contain exactly 9 unique categories")
    if set(active) | set(reserve) != set(top):
        raise SystemExit("FAIL: active + reserve must equal geositeTopLevel")
    if set(active) & set(reserve):
        raise SystemExit("FAIL: active and reserve category sets overlap")
    if "ru-blocked" not in top:
        raise SystemExit("FAIL: ru-blocked missing from geositeTopLevel")

    return top


def source_path(data_dir: Path, name: str) -> Path:
    if not SAFE_LIST.fullmatch(name):
        raise SystemExit(f"FAIL: unsafe list name: {name!r}")
    path = data_dir / name.lower()
    if not path.is_file():
        raise SystemExit(f"FAIL: required v2fly source list not found: {name}")
    return path


def includes_from(path: Path):
    includes = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            kind, sep, rest = line.partition(":")
            if not sep or kind.lower() != "include":
                continue
            fields = rest.split()
            if not fields:
                raise SystemExit(f"FAIL: malformed include in {path}")
            name = fields[0]
            if not SAFE_LIST.fullmatch(name):
                raise SystemExit(f"FAIL: unsafe include name {name!r} in {path}")
            includes.append(name.lower())
    return includes


def dependency_closure(data_dir: Path, roots):
    seen = set()
    stack = [x.lower() for x in roots]

    while stack:
        name = stack.pop()
        if name in seen:
            continue
        path = source_path(data_dir, name)
        seen.add(name)
        for child in includes_from(path):
            if child not in seen:
                stack.append(child)

    return sorted(seen)


def main():
    args = parse_args()
    policy_path = Path(args.policy).resolve()
    data_dir = Path(args.dlc_data).resolve()
    ru_blocked = Path(args.ru_blocked).resolve()
    out_data = Path(args.output_data).resolve()
    datprofile = Path(args.datprofile).resolve()

    if not data_dir.is_dir():
        raise SystemExit("FAIL: v2fly data directory not found")
    if not ru_blocked.is_file():
        raise SystemExit("FAIL: ru-blocked source file not found")

    top = load_policy(policy_path)
    v2fly_roots = [x for x in top if x != "ru-blocked"]
    closure = dependency_closure(data_dir, v2fly_roots)

    if out_data.exists():
        if any(out_data.iterdir()):
            raise SystemExit(f"FAIL: output-data directory is not empty: {out_data}")
    else:
        out_data.mkdir(parents=True)

    for name in closure:
        shutil.copyfile(source_path(data_dir, name), out_data / name)

    shutil.copyfile(ru_blocked, out_data / "ru-blocked")

    profile = [{
        "name": "geosite.dat",
        "mode": "allowlist",
        "lists": top,
    }]
    datprofile.parent.mkdir(parents=True, exist_ok=True)
    with datprofile.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
        f.write("\n")

    actual_files = sorted(p.name for p in out_data.iterdir() if p.is_file())
    expected_files = sorted(closure + ["ru-blocked"])
    if actual_files != expected_files:
        raise SystemExit("FAIL: prepared source file set mismatch")

    print(f"GEOSITE_TOP_LEVEL={len(top)}")
    print(f"V2FLY_TOP_LEVEL={len(v2fly_roots)}")
    print(f"V2FLY_DEPENDENCY_CLOSURE={len(closure)}")
    print(f"PREPARED_SOURCE_FILE_COUNT={len(actual_files)}")
    print("PREPARE_GEOSITE=PASS")


if __name__ == "__main__":
    main()
