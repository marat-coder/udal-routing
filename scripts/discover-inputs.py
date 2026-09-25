#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path

DLC_REPO = "v2fly/domain-list-community"
GEO_REPO = "runetfreedom/russia-blocked-geosite"
IP_REPO = "runetfreedom/russia-blocked-geoip"


def gh(path):
    raw = subprocess.check_output(["gh", "api", path], text=True)
    return json.loads(raw)


def asset_info(release, name):
    matches = [a for a in release.get("assets", []) if a.get("name") == name]
    if len(matches) != 1:
        raise SystemExit(f"FAIL: expected exactly one asset {name} in release {release.get('tag_name')}")
    a = matches[0]
    digest = a.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise SystemExit(f"FAIL: missing SHA256 digest for {name}")
    return {
        "asset": name,
        "assetId": a["id"],
        "size": a["size"],
        "sha256": digest.split(":", 1)[1],
    }


def release_by_tag(repo, tag):
    return gh(f"repos/{repo}/releases/tags/{tag}")


def latest_release(repo):
    return gh(f"repos/{repo}/releases/latest")


def commit_info(sha):
    c = gh(f"repos/{DLC_REPO}/commits/{sha}")
    return {
        "repository": DLC_REPO,
        "commit": c["sha"],
        "timestamp": c["commit"]["committer"]["date"],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["baseline", "current"], required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    baseline = json.loads(Path(a.baseline).read_text(encoding="utf-8"))

    if a.mode == "baseline":
        bsrc = baseline["sources"]
        dlc = commit_info(bsrc["domainListCommunity"]["commit"])

        gr = release_by_tag(GEO_REPO, bsrc["ruBlockedGeosite"]["release"])
        ga = asset_info(gr, bsrc["ruBlockedGeosite"]["asset"])
        if ga["sha256"] != bsrc["ruBlockedGeosite"]["sha256"] or ga["size"] != bsrc["ruBlockedGeosite"]["size"]:
            raise SystemExit("FAIL: baseline ru-blocked upstream asset changed unexpectedly")

        ir = release_by_tag(IP_REPO, bsrc["geoip"]["release"])
        ia = asset_info(ir, bsrc["geoip"]["asset"])
        if ia["sha256"] != bsrc["geoip"]["sha256"] or ia["size"] != bsrc["geoip"]["size"]:
            raise SystemExit("FAIL: baseline geoip upstream asset changed unexpectedly")
    else:
        head = gh(f"repos/{DLC_REPO}/commits/master")
        dlc = {
            "repository": DLC_REPO,
            "commit": head["sha"],
            "timestamp": head["commit"]["committer"]["date"],
        }
        gr = latest_release(GEO_REPO)
        ga = asset_info(gr, "ru-blocked.txt")
        ir = latest_release(IP_REPO)
        ia = asset_info(ir, "geoip.dat")

    geo = {
        "repository": GEO_REPO,
        "release": gr["tag_name"],
        "publishedAt": gr["published_at"],
        **ga,
    }
    ip = {
        "repository": IP_REPO,
        "release": ir["tag_name"],
        "publishedAt": ir["published_at"],
        **ia,
        "model": "FULL_PINNED_RUNETFREEDOM_BYTE_FOR_BYTE",
    }

    out = {
        "domainListCommunity": dlc,
        "ruBlockedGeosite": geo,
        "geoip": ip,
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    print(f"DISCOVERY_MODE={a.mode}")
    print(f"V2FLY_COMMIT={dlc['commit']}")
    print(f"RU_BLOCKED_RELEASE={geo['release']}")
    print(f"RU_BLOCKED_SHA256={geo['sha256']}")
    print(f"GEOIP_RELEASE={ip['release']}")
    print(f"GEOIP_SHA256={ip['sha256']}")
    print("DISCOVER_INPUTS=PASS")


if __name__ == "__main__":
    main()
