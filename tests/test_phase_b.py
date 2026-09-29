#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from common import (
    BUILD_CONTRACT,
    REPO,
    TAG,
    make_bundle,
    validate_bundle,
)


class PhaseBContractTests(unittest.TestCase):
    def test_dual_routing_snapshot_live_six_assets(self):
        with tempfile.TemporaryDirectory() as td:
            bundle,prov=make_bundle(td)
            out=validate_bundle(bundle,prov).stdout
            self.assertIn("ROUTING_SEMANTIC_EQUIVALENCE=PASS",out)
            self.assertIn("SNAPSHOT_ROLLBACK_URLS=PASS",out)
            self.assertIn("LIVE_STABLE_LATEST_URLS=PASS",out)
            snap=json.loads((bundle/"UDAL-ROUTING.json").read_text())
            live=json.loads((bundle/"UDAL-ROUTING-LIVE.json").read_text())
            self.assertEqual(
                snap["Geoipurl"],
                f"https://github.com/{REPO}/releases/download/{TAG}/UDAL-GEOIP.dat",
            )
            self.assertEqual(
                snap["Geositeurl"],
                f"https://github.com/{REPO}/releases/download/{TAG}/UDAL-GEOSITE.dat",
            )
            self.assertNotIn("/releases/latest/",snap["Geoipurl"])
            contract=json.loads(BUILD_CONTRACT.read_text())
            self.assertEqual(live["Geoipurl"],contract["urlModel"]["live"]["geoipUrl"])
            self.assertEqual(live["Geositeurl"],contract["urlModel"]["live"]["geositeUrl"])
            self.assertEqual(
                {k:v for k,v in snap.items() if k not in ("Geoipurl","Geositeurl")},
                {k:v for k,v in live.items() if k not in ("Geoipurl","Geositeurl")},
            )
            self.assertEqual({p.name for p in bundle.iterdir()},set(contract["artifactSet"]))
            self.assertEqual(len((bundle/"SHA256SUMS").read_text().splitlines()),5)

    def test_unapproved_latest_urls_fail_closed(self):
        cases=(
            ("Geoipurl","https://github.com/other/repo/releases/latest/download/UDAL-GEOIP.dat"),
            ("Geositeurl","https://github.com/marat-coder/udal-routing/releases/latest/download/WRONG.dat"),
        )
        for key,bad in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as td:
                bundle,prov=make_bundle(td)
                p=bundle/"UDAL-ROUTING-LIVE.json"
                obj=json.loads(p.read_text())
                obj[key]=bad
                p.write_text(json.dumps(obj,indent=2)+"\n")
                res=validate_bundle(bundle,prov,check=False)
                self.assertNotEqual(res.returncode,0)

    def test_deterministic_manifest_and_sums(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            bundle_a,prov_a=make_bundle(a)
            bundle_b,prov_b=make_bundle(b)
            validate_bundle(bundle_a,prov_a)
            validate_bundle(bundle_b,prov_b)
            self.assertEqual(
                (bundle_a/"MANIFEST.json").read_bytes(),
                (bundle_b/"MANIFEST.json").read_bytes(),
            )
            self.assertEqual(
                (bundle_a/"SHA256SUMS").read_bytes(),
                (bundle_b/"SHA256SUMS").read_bytes(),
            )


if __name__=="__main__":
    unittest.main()
