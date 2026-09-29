#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def gh(path, allow_404=False):
    p = subprocess.run(["gh", "api", path], text=True, capture_output=True)
    if p.returncode != 0:
        if allow_404 and "404" in p.stderr:
            return None
        raise SystemExit(f"FAIL: gh api failed for {path}")
    return json.loads(p.stdout)


def download_asset(repo, asset_id):
    p = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/assets/{asset_id}", "-H", "Accept: application/octet-stream"],
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
    hits = [x for x in assets if x["name"] == "MANIFEST.json"]
    if len(hits) != 1:
        raise SystemExit("FAIL: release must contain exactly one MANIFEST.json")
    return manifest_fingerprint(download_asset(repo, hits[0]["id"]))


def expected_assets(tag, contract):
    legacy = contract.get("legacyAssetSetTags", {})
    return set(legacy[tag] if tag in legacy else contract["artifactSet"])


def analyze_releases(releases, baseline, contract, baseline_fp, current_fp, manifest_resolver, routing_resolver=None):
    baseline_tag = baseline["baselineRelease"]
    max_last = int(baseline["routingLastUpdated"])
    fp_contract = baseline.get("fingerprintContract", {})
    if fp_contract.get("baselineInputFingerprint") != baseline_fp:
        raise SystemExit("FAIL: computed baseline fingerprint does not match baseline lock")
    legacy_optional = fp_contract.get("legacyFingerprintOptionalTags", [])
    if not isinstance(legacy_optional, list) or len(legacy_optional) != len(set(legacy_optional)):
        raise SystemExit("FAIL: invalid legacy fingerprint allowlist")
    if baseline_tag in legacy_optional:
        raise SystemExit("FAIL: current baseline cannot be fingerprint-exempt")
    legacy_optional = set(legacy_optional)

    published = [r for r in releases if not r.get("draft") and r.get("published_at")]
    published.sort(key=lambda r: r["published_at"], reverse=True)
    previous_production = published[0]["tag_name"] if published else baseline_tag

    published_fps = set()
    draft_fp_tags = {}
    version_re = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d+$")

    for r in releases:
        tag = r.get("tag_name", "")
        if not version_re.fullmatch(tag):
            continue
        assets = r.get("assets", [])
        names = {x["name"] for x in assets}
        if names != expected_assets(tag, contract):
            raise SystemExit(f"FAIL: versioned release/draft asset set mismatch: {tag}")

        fp = body_fingerprint(r.get("body") or "")
        is_published = not r.get("draft") and bool(r.get("published_at"))

        if tag == baseline_tag:
            fp = fp or manifest_resolver(r)
            if fp != baseline_fp or not is_published:
                raise SystemExit("FAIL: current production fingerprint contract mismatch")
            published_fps.add(fp)
            print(f"CURRENT_PRODUCTION_FINGERPRINT_CONTRACT=ENFORCED:{tag}")
        elif fp:
            if r.get("draft"):
                draft_fp_tags.setdefault(fp, []).append(tag)
            elif is_published:
                published_fps.add(fp)
            else:
                raise SystemExit(f"FAIL: invalid versioned release state: {tag}")
        elif tag in legacy_optional:
            if r.get("draft") or not r.get("published_at") or r.get("immutable") is not True:
                raise SystemExit(f"FAIL: legacy fingerprint exemption requires published immutable release: {tag}")
            print(f"LEGACY_FINGERPRINT_ALLOWLIST_ACCEPTED={tag}")
        else:
            raise SystemExit(f"FAIL: versioned release lacks fingerprint marker: {tag}")

        if routing_resolver:
            data = routing_resolver(r)
            if data is not None:
                obj = json.loads(data.decode("utf-8"))
                lu = obj.get("LastUpdated")
                if not isinstance(lu, int):
                    raise SystemExit(f"FAIL: invalid LastUpdated in release {tag}")
                max_last = max(max_last, lu)

    draft_tags = sorted(draft_fp_tags.get(current_fp, []))
    if len(draft_tags) > 1:
        raise SystemExit("FAIL: multiple matching drafts exist for current fingerprint")

    baseline_match = current_fp == baseline_fp
    published_match = baseline_match or current_fp in published_fps
    stale_draft = bool(draft_tags) and not published_match

    return {
        "previousProductionRelease": previous_production,
        "maxLastUpdated": max_last,
        "nextLastUpdatedFloor": max_last + 1,
        "noChanges": published_match,
        "publishedFingerprintMatch": published_match,
        "draftFingerprintMatch": bool(draft_tags),
        "staleDraftMatch": stale_draft,
        "matchingDraftTag": draft_tags[0] if draft_tags else None,
        "baselineFingerprintMatch": baseline_match,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--build-contract", required=True)
    p.add_argument("--baseline-fingerprint", required=True)
    p.add_argument("--current-fingerprint", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    baseline = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
    contract = json.loads(Path(a.build_contract).read_text(encoding="utf-8"))
    releases = gh(f"repos/{a.repo}/releases?per_page=100")

    def routing_resolver(r):
        hits = [x for x in r.get("assets", []) if x["name"] == "UDAL-ROUTING.json"]
        return download_asset(a.repo, hits[0]["id"]) if len(hits) == 1 else None

    state = analyze_releases(
        releases, baseline, contract, a.baseline_fingerprint, a.current_fingerprint,
        lambda r: release_manifest_fingerprint(a.repo, r.get("assets", [])),
        routing_resolver,
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
    state["newTag"] = f"{prefix}{n}"

    Path(a.output).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    for k in ("previousProductionRelease","maxLastUpdated","newTag"):
        print(f"{k.upper()}={state[k]}")
    print(f"NO_CHANGES={str(state['noChanges']).lower()}")
    print(f"PUBLISHED_FINGERPRINT_MATCH={str(state['publishedFingerprintMatch']).lower()}")
    print(f"DRAFT_FINGERPRINT_MATCH={str(state['draftFingerprintMatch']).lower()}")
    print(f"STALE_DRAFT_MATCH={str(state['staleDraftMatch']).lower()}")
    if state["matchingDraftTag"]:
        print(f"MATCHING_DRAFT_TAG={state['matchingDraftTag']}")
    print("RELEASE_STATE=PASS")


if __name__ == "__main__":
    main()
