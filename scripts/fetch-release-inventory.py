#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path


class InventoryError(RuntimeError):
    pass


def gh_page(repo, page, per_page):
    endpoint=f"repos/{repo}/releases?per_page={per_page}&page={page}"
    p=subprocess.run(["gh","api",endpoint],text=True,capture_output=True)
    if p.returncode!=0:
        raise InventoryError(f"GitHub API failed on release page {page}")
    try:
        data=json.loads(p.stdout)
    except Exception as e:
        raise InventoryError(f"malformed JSON on release page {page}") from e
    return data


def fetch_all_releases(repo, *, per_page=100, max_pages=100, fetcher=None):
    if not isinstance(per_page,int) or not 1<=per_page<=100:
        raise InventoryError("per_page must be 1..100")
    if not isinstance(max_pages,int) or max_pages<1:
        raise InventoryError("max_pages must be >=1")
    if fetcher is None:
        fetcher=lambda page: gh_page(repo,page,per_page)

    out=[]
    seen_ids=set()
    seen_tags={}
    for page in range(1,max_pages+1):
        data=fetcher(page)
        if not isinstance(data,list):
            raise InventoryError(f"release page {page} is not a JSON list")
        if len(data)>per_page:
            raise InventoryError(f"release page {page} exceeds requested page size")

        for item in data:
            if not isinstance(item,dict):
                raise InventoryError(f"release page {page} contains non-object entry")
            rid=item.get("id")
            tag=item.get("tag_name")
            if not isinstance(rid,int) or rid<=0:
                raise InventoryError(f"release page {page} contains invalid release id")
            if not isinstance(tag,str) or not tag:
                raise InventoryError(f"release page {page} contains invalid tag_name")
            if rid in seen_ids:
                raise InventoryError(f"duplicate release id across pagination: {rid}")
            if tag in seen_tags and seen_tags[tag]!=rid:
                raise InventoryError(f"conflicting release tag across pagination: {tag}")
            seen_ids.add(rid)
            seen_tags[tag]=rid
            out.append(item)

        if len(data)<per_page:
            return out

    raise InventoryError(
        f"release inventory pagination hit hard limit of {max_pages} full pages"
    )


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--per-page",type=int,default=100)
    p.add_argument("--max-pages",type=int,default=100)
    a=p.parse_args()

    try:
        releases=fetch_all_releases(
            a.repo,
            per_page=a.per_page,
            max_pages=a.max_pages,
        )
    except InventoryError as e:
        raise SystemExit(f"FAIL: {e}")

    Path(a.output).write_text(
        json.dumps(releases,indent=2)+"\n",
        encoding="utf-8",
    )
    print(f"RELEASE_INVENTORY_COUNT={len(releases)}")
    print("RELEASE_INVENTORY_EXHAUSTIVE=PASS")
    print("RELEASE_INVENTORY_PAGINATION=PASS")


if __name__=="__main__":
    main()
