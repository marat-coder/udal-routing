#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--template", required=True)
    p.add_argument("--policy", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--last-updated", type=int, required=True)
    p.add_argument("--output", required=True)
    return p.parse_args()


def desired(policy, repo, tag, last_updated):
    prefix = f"https://github.com/{repo}/releases/download/{tag}"
    return {
        "Name": policy["name"],
        "GlobalProxy": policy["globalProxy"],
        "UseChunkFiles": policy["useChunkFiles"],
        "RemoteDns": policy["remoteDns"],
        "DomesticDns": policy["domesticDns"],
        "RemoteDNSType": policy["remoteDnsType"],
        "RemoteDNSDomain": policy["remoteDnsDomain"],
        "RemoteDNSIP": policy["remoteDnsIp"],
        "DomesticDNSType": policy["domesticDnsType"],
        "DomesticDNSDomain": policy["domesticDnsDomain"],
        "DomesticDNSIP": policy["domesticDnsIp"],
        "Geoipurl": f"{prefix}/UDAL-GEOIP.dat",
        "Geositeurl": f"{prefix}/UDAL-GEOSITE.dat",
        "LastUpdated": last_updated,
        "DnsHosts": {},
        "RouteOrder": policy["routeOrder"],
        "DirectSites": policy["directSites"],
        "DirectIp": policy["directIp"],
        "ProxySites": policy["proxySites"],
        "ProxyIp": policy["proxyIp"],
        "BlockSites": policy["blockSites"],
        "BlockIp": policy["blockIp"],
        "DomainStrategy": policy["domainStrategy"],
        "FakeDNS": policy["fakeDns"],
    }


def patch_scalar(raw, key, old_value, new_value):
    old = json.dumps(old_value, ensure_ascii=False, separators=(",", ":"))
    new = json.dumps(new_value, ensure_ascii=False, separators=(",", ":"))
    pat = re.compile(rf'(^[ \t]*"{re.escape(key)}"[ \t]*:[ \t]*){re.escape(old)}', re.MULTILINE)
    raw2, count = pat.subn(lambda m: m.group(1) + new, raw, count=1)
    if count != 1:
        raise SystemExit(f"FAIL: cannot patch field {key}")
    return raw2


def main():
    a = args()
    raw_bytes = Path(a.template).read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raise SystemExit("FAIL: routing template BOM")
    raw = raw_bytes.decode("utf-8")
    base = json.loads(raw)
    policy = json.loads(Path(a.policy).read_text(encoding="utf-8"))
    want = desired(policy, a.repo, a.tag, a.last_updated)

    for key in want:
        if key not in base:
            raise SystemExit(f"FAIL: routing template missing {key}")

    stable_keys = [k for k in want if k not in ("Geoipurl", "Geositeurl", "LastUpdated")]
    semantic_changes = any(base[k] != want[k] for k in stable_keys)

    if not semantic_changes:
        out = raw
        for key in ("Geoipurl", "Geositeurl", "LastUpdated"):
            if base[key] != want[key]:
                out = patch_scalar(out, key, base[key], want[key])
        mode = "BYTE_PRESERVING_PATCH"
    else:
        obj = dict(base)
        obj.update(want)
        newline = "\r\n" if "\r\n" in raw else "\n"
        m = re.search(r'\n([ \t]+)"', raw)
        indent = m.group(1) if m else "  "
        trailing = raw.endswith("\n")
        out = json.dumps(obj, ensure_ascii=False, indent=indent)
        if newline != "\n":
            out = out.replace("\n", newline)
        if trailing:
            out += newline
        mode = "STRUCTURAL_REWRITE"

    check = json.loads(out)
    for key, value in want.items():
        if check.get(key) != value:
            raise SystemExit(f"FAIL: output mismatch {key}")

    target = Path(a.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out.encode("utf-8"))

    print(f"ROUTING_BUILD_MODE={mode}")
    print(f"ROUTING_TAG={a.tag}")
    print(f"ROUTING_LAST_UPDATED={a.last_updated}")
    print("BUILD_ROUTING=PASS")


if __name__ == "__main__":
    main()
