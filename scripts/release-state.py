#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_ASSETS = {
    "UDAL-GEOSITE.dat",
    "UDAL-GEOIP.dat",
    "UDAL-ROUTING.json",
    "MANIFEST.json",
    "SHA256SUMS",
}


def gh(path, allow_404=False):
    p = subprocess.run(["gh", "api", path], text=True, capture_output=True)
    if p.returncode != 0:
        if allow_404 and "404" in p.stderr:
            return None
        raise SystemExit(f"FAIL: gh api failed for {path}")
    return json.loads(p.stdout)


def download_asset(repo, asset_id):
    p = subprocess.run(
        [
            "gh", "api",
            f"repos/{repo}/releases/assets/{asset_id}",
            "-H", "Accept: application/octet-stream",
        ],
        capture_output=True,
    )
    if p.returncode != 0:
        raise SystemExit("FAIL: unable to read release asset")
    return p.stdout


def body_fingerprint(body):
    m = re.search(r"(?m)^INPUT_FINGERPRINT=([0-9a-f]{64})$", body or "")
    return m.group(1) if m else None


def manifest_fingerprint(data):
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        raise SystemExit("FAIL: cannot parse MANIFEST.json for fingerprint contract")

    if obj.get("manifestSchema") == 2:
        fp = obj.get("buildPlan", {}).get("inputFingerprint")
    else:
        fp = obj.get("automation", {}).get("inputFingerprint")

    if not isinstance(fp, str) or not re.fullmatch(r"[0-9a-f]{64}", fp):
        raise SystemExit("FAIL: MANIFEST.json lacks valid input fingerprint")
    return fp


def release_manifest_fingerprint(repo, assets):
    manifest_assets = [x for x in assets if x["name"] == "MANIFEST.json"]
    if len(manifest_assets) != 1:
        raise SystemExit("FAIL: baseline release must contain exactly one MANIFEST.json")
    return manifest_fingerprint(download_asset(repo, manifest_assets[0]["id"]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--baseline-fingerprint", required=True)
    p.add_argument("--current-fingerprint", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    baseline = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
    baseline_tag = baseline["baselineRelease"]
    max_last = int(baseline["routingLastUpdated"])

    fp_contract = baseline.get("fingerprintContract", {})
    locked_baseline_fp = fp_contract.get("baselineInputFingerprint")
    legacy_optional = fp_contract.get("legacyFingerprintOptionalTags", [])

    if locked_baseline_fp != a.baseline_fingerprint:
        raise SystemExit("FAIL: computed baseline fingerprint does not match baseline lock")
    if not isinstance(legacy_optional, list) or len(legacy_optional) != len(set(legacy_optional)):
        raise SystemExit("FAIL: invalid legacy fingerprint allowlist")
    if baseline_tag in legacy_optional:
        raise SystemExit("FAIL: current baseline cannot be fingerprint-exempt")
    for tag in legacy_optional:
        if not isinstance(tag, str) or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+", tag):
            raise SystemExit("FAIL: invalid tag in legacy fingerprint allowlist")

    legacy_optional = set(legacy_optional)

    releases = gh(f"repos/{a.repo}/releases?per_page=100")
    published = [r for r in releases if not r.get("draft") and r.get("published_at")]
    published.sort(key=lambda r: r["published_at"], reverse=True)
    previous_production = published[0]["tag_name"] if published else baseline_tag

    existing_fingerprints = set()
    version_re = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d+$")

    for r in releases:
        tag = r.get("tag_name", "")
        if not version_re.fullmatch(tag):
            continue

        assets = r.get("assets", [])
        names = {x["name"] for x in assets}
        if tag != baseline_tag and names != EXPECTED_ASSETS:
            raise SystemExit(f"FAIL: incomplete versioned release/draft exists: {tag}")

        body_fp = body_fingerprint(r.get("body") or "")

        if tag == baseline_tag:
            baseline_release_fp = body_fp or release_manifest_fingerprint(a.repo, assets)
            if baseline_release_fp != a.baseline_fingerprint:
                raise SystemExit("FAIL: current production fingerprint contract mismatch")
            existing_fingerprints.add(baseline_release_fp)
            print(f"CURRENT_PRODUCTION_FINGERPRINT_CONTRACT=ENFORCED:{tag}")
        elif body_fp:
            existing_fingerprints.add(body_fp)
        elif tag in legacy_optional:
            if r.get("draft") or not r.get("published_at") or r.get("immutable") is not True:
                raise SystemExit(f"FAIL: legacy fingerprint exemption requires published immutable release: {tag}")
            print(f"LEGACY_FINGERPRINT_ALLOWLIST_ACCEPTED={tag}")
        elif names == EXPECTED_ASSETS:
            raise SystemExit(f"FAIL: versioned candidate lacks fingerprint marker: {tag}")

        route_assets = [x for x in assets if x["name"] == "UDAL-ROUTING.json"]
        if len(route_assets) == 1:
            try:
                obj = json.loads(download_asset(a.repo, route_assets[0]["id"]).decode("utf-8"))
            except Exception:
                raise SystemExit(f"FAIL: cannot parse routing asset in release {tag}")
            lu = obj.get("LastUpdated")
            if not isinstance(lu, int):
                raise SystemExit(f"FAIL: invalid LastUpdated in release {tag}")
            max_last = max(max_last, lu)

    no_changes = (
        a.current_fingerprint == a.baseline_fingerprint
        or a.current_fingerprint in existing_fingerprints
    )

    prefix = datetime.now(timezone.utc).strftime("%Y.%m.%d.")
    used = {r.get("tag_name", "") for r in releases}
    refs = gh(f"repos/{a.repo}/git/matching-refs/tags/{prefix}", allow_404=True) or []
    for ref in refs:
        name = ref.get("ref", "")
        if name.startswith("refs/tags/"):
            used.add(name[len("refs/tags/"):])

    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    new_tag = f"{prefix}{n}"

    out = {
        "previousProductionRelease": previous_production,
        "maxLastUpdated": max_last,
        "nextLastUpdatedFloor": max_last + 1,
        "newTag": new_tag,
        "noChanges": no_changes,
        "existingFingerprintMatch": a.current_fingerprint in existing_fingerprints,
        "baselineFingerprintMatch": a.current_fingerprint == a.baseline_fingerprint,
    }
    Path(a.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    print(f"PREVIOUS_PRODUCTION={previous_production}")
    print(f"MAX_LAST_UPDATED={max_last}")
    print(f"NEW_TAG={new_tag}")
    print(f"NO_CHANGES={str(no_changes).lower()}")
    print("RELEASE_STATE=PASS")


if __name__ == "__main__":
    main()
