#!/usr/bin/env python3
import argparse
import re
import subprocess
from pathlib import Path

SELF = "scripts/scan-secrets.py"

BYTE_RULES = [
    ("HY2_URI", ("hysteria2" + "://").encode("ascii")),
    ("PEM_PRIVATE_KEY", ("-----BEGIN " + "PRIVATE KEY" + "-----").encode("ascii")),
    ("PEM_ENCRYPTED_PRIVATE_KEY", ("-----BEGIN ENCRYPTED " + "PRIVATE KEY" + "-----").encode("ascii")),
]

ASSIGNMENT = re.compile(
    r"""(?ix)
    (?:["']?(?:password|auth|private[_-]?key|psk|token|api[_-]?token)["']?)
    \s*[:=]\s*
    ["']?([A-Za-z0-9_./+=:@-]{8,})
    """
)


def tracked_files(root: Path):
    raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
    for item in raw.split(b"\0"):
        if not item:
            continue
        rel = item.decode("utf-8")
        if rel == SELF:
            continue
        yield root / rel


def scan(path: Path):
    data = path.read_bytes()
    hits = []
    for rule, needle in BYTE_RULES:
        if needle in data:
            hits.append(rule)

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return hits

    if ASSIGNMENT.search(text):
        hits.append("SECRET_LIKE_ASSIGNMENT")
    return hits


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", required=True)
    p.add_argument("--bundle", required=True)
    a = p.parse_args()

    root = Path(a.repo_root).resolve()
    bundle = Path(a.bundle).resolve()

    candidates = list(tracked_files(root))
    candidates.extend(x for x in bundle.iterdir() if x.is_file())

    findings = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        for rule in scan(path):
            findings.append((rule, path))

    if findings:
        for rule, path in findings:
            try:
                display = path.relative_to(root)
            except ValueError:
                display = Path(path.name)
            print(f"SECRET_SCAN_FINDING rule={rule} file={display}")
        raise SystemExit("FAIL: secret scan detected suspicious content")

    print("SECRET_SCAN_FINDINGS=0")
    print("SECRET_SCAN=PASS")


if __name__ == "__main__":
    main()
