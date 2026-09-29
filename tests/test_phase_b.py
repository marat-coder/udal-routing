#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
REPO = "marat-coder/udal-routing"
TAG = "2099.01.01.1"
LAST = 1790327433
FP = "1" * 64


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_routing = load_script("build_routing", "build-routing.py")
release_state = load_script("release_state", "release-state.py")


def run(*args, check=True):
    p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if check and p.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PhaseBTests(unittest.TestCase):
    def setUp(self):
        self.policy_path = ROOT / "config/routing-policy.json"
        self.build_contract_path = ROOT / "config/build-contract.json"
        self.manifest_cfg = ROOT / "config/manifest-schema-v2.json"
        self.toolchain = ROOT / "config/toolchain-lock.json"
        self.validation = ROOT / "config/validation-contract.json"
        self.baseline_path = ROOT / "config/baseline-2026.09.25.3.json"
        self.policy = json.loads(self.policy_path.read_text())
        self.contract = json.loads(self.build_contract_path.read_text())

    def make_bundle(self, td):
        root = Path(td)
        bundle = root / "bundle"
        bundle.mkdir()
        (bundle / "UDAL-GEOSITE.dat").write_bytes(b"synthetic-geosite-v1\n")
        (bundle / "UDAL-GEOIP.dat").write_bytes(b"synthetic-geoip-v1\n")
        template = build_routing.desired(self.policy, REPO, "2026.09.25.3", 1790327432, "snapshot")
        template_path = root / "template.json"
        template_path.write_text(json.dumps(template, indent=2) + "\n")
        for mode, name in (("snapshot", "UDAL-ROUTING.json"), ("live", "UDAL-ROUTING-LIVE.json")):
            run(PY, "scripts/build-routing.py", "--template", str(template_path), "--policy", str(self.policy_path),
                "--repo", REPO, "--tag", TAG, "--url-mode", mode, "--last-updated", str(LAST),
                "--output", str(bundle / name))
        prov = {
            "domainListCommunity": {"commit": "a"*40, "relevantHash": "b"*64},
            "ruBlockedGeosite": {"sha256": "c"*64},
            "geoip": {"sha256": "d"*64},
            "routingPolicySha256": sha(self.policy_path),
            "buildContractSha256": sha(self.build_contract_path),
            "buildContractId": self.contract["contractId"],
            "urlModelId": self.contract["urlModel"]["id"],
            "inputFingerprint": FP,
        }
        prov_path = root / "provenance.json"
        prov_path.write_text(json.dumps(prov, indent=2) + "\n")
        run(PY, "scripts/make-manifest.py", "--manifest-config", str(self.manifest_cfg),
            "--build-contract", str(self.build_contract_path), "--toolchain-lock", str(self.toolchain),
            "--validation-contract", str(self.validation), "--policy", str(self.policy_path),
            "--provenance", str(prov_path), "--bundle", str(bundle), "--tag", TAG,
            "--previous-production", "2026.09.25.3", "--last-updated", str(LAST),
            "--input-fingerprint", FP, "--output", str(bundle / "MANIFEST.json"))
        run(PY, "scripts/make-sha256sums.py", "--bundle", str(bundle), "--build-contract", str(self.build_contract_path))
        return bundle, prov_path

    def validate(self, bundle, prov, check=True):
        return run(PY, "scripts/validate-artifacts.py", "--bundle", str(bundle), "--policy", str(self.policy_path),
            "--contract", str(self.validation), "--manifest-config", str(self.manifest_cfg),
            "--build-contract", str(self.build_contract_path), "--toolchain-lock", str(self.toolchain),
            "--provenance", str(prov), "--repo", REPO, "--tag", TAG,
            "--previous-production", "2026.09.25.3", "--last-updated", str(LAST),
            "--input-fingerprint", FP, check=check)

    def test_dual_routing_snapshot_live_and_six_assets(self):
        with tempfile.TemporaryDirectory() as td:
            bundle, prov = self.make_bundle(td)
            out = self.validate(bundle, prov).stdout
            self.assertIn("ROUTING_SEMANTIC_EQUIVALENCE=PASS", out)
            snap = json.loads((bundle/"UDAL-ROUTING.json").read_text())
            live = json.loads((bundle/"UDAL-ROUTING-LIVE.json").read_text())
            self.assertEqual(snap["Geoipurl"], f"https://github.com/{REPO}/releases/download/{TAG}/UDAL-GEOIP.dat")
            self.assertNotIn("/latest/", snap["Geoipurl"])
            self.assertEqual(live["Geoipurl"], self.contract["urlModel"]["live"]["geoipUrl"])
            self.assertEqual(live["Geositeurl"], self.contract["urlModel"]["live"]["geositeUrl"])
            self.assertEqual({k:v for k,v in snap.items() if k not in ("Geoipurl","Geositeurl")},
                             {k:v for k,v in live.items() if k not in ("Geoipurl","Geositeurl")})
            self.assertEqual({p.name for p in bundle.iterdir()}, set(self.contract["artifactSet"]))
            self.assertEqual(len((bundle/"SHA256SUMS").read_text().splitlines()), 5)

    def test_arbitrary_or_wrong_latest_url_rejected(self):
        for key, bad in (
            ("Geoipurl", "https://github.com/other/repo/releases/latest/download/UDAL-GEOIP.dat"),
            ("Geositeurl", "https://github.com/marat-coder/udal-routing/releases/latest/download/WRONG.dat"),
        ):
            with tempfile.TemporaryDirectory() as td:
                bundle, prov = self.make_bundle(td)
                p = bundle/"UDAL-ROUTING-LIVE.json"
                obj = json.loads(p.read_text()); obj[key] = bad
                p.write_text(json.dumps(obj, indent=2)+"\n")
                res = self.validate(bundle, prov, check=False)
                self.assertNotEqual(res.returncode, 0)

    def classify(self, baseline, prov):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td)/"b.json"; p=Path(td)/"p.json"; o=Path(td)/"o.json"
            b.write_text(json.dumps(baseline)); p.write_text(json.dumps(prov))
            run(PY, "scripts/classify-change.py", "--baseline", str(b), "--provenance", str(p),
                "--build-contract", str(self.build_contract_path), "--output", str(o))
            return json.loads(o.read_text())

    def test_change_reason_gates(self):
        c=self.contract
        baseline={
          "sources":{"ruBlockedGeosite":{"sha256":"2"*64},"geoip":{"sha256":"3"*64}},
          "routingPolicySha256":"4"*64
        }
        prov={"domainListCommunity":{"relevantHash":c["legacyProductionContract"]["relevantHash"]},
              "ruBlockedGeosite":{"sha256":"2"*64},"geoip":{"sha256":"3"*64},"routingPolicySha256":"4"*64}
        # Current Phase B contract is intentionally a build/URL model change from legacy production.
        out=self.classify(baseline,prov)
        self.assertIn("BUILD_CONTRACT",out["changeReasons"]); self.assertIn("URL_MODEL",out["changeReasons"])
        self.assertFalse(out["scheduledAutoPublishEligible"])

        # Synthetic post-migration baseline: only upstream content changes are eligible.
        cpath=Path(self.build_contract_path)
        original=json.loads(cpath.read_text())
        legacy=original["legacyProductionContract"]
        old=(legacy["buildContractId"],legacy["urlModelId"])
        try:
            legacy["buildContractId"]=original["contractId"]; legacy["urlModelId"]=original["urlModel"]["id"]
            with tempfile.TemporaryDirectory() as td:
                cp=Path(td)/"contract.json"; cp.write_text(json.dumps(original))
                b=Path(td)/"b.json"; p=Path(td)/"p.json"; o=Path(td)/"o.json"
                b.write_text(json.dumps(baseline)); p.write_text(json.dumps(prov))
                run(PY,"scripts/classify-change.py","--baseline",str(b),"--provenance",str(p),"--build-contract",str(cp),"--output",str(o))
                self.assertFalse(json.loads(o.read_text())["changeDetected"])
                prov2=json.loads(json.dumps(prov)); prov2["geoip"]["sha256"]="9"*64; p.write_text(json.dumps(prov2))
                run(PY,"scripts/classify-change.py","--baseline",str(b),"--provenance",str(p),"--build-contract",str(cp),"--output",str(o))
                r=json.loads(o.read_text()); self.assertEqual(r["changeReasons"],["GEOIP_CONTENT"]); self.assertTrue(r["scheduledAutoPublishEligible"])
                prov3=json.loads(json.dumps(prov)); prov3["routingPolicySha256"]="8"*64; p.write_text(json.dumps(prov3))
                run(PY,"scripts/classify-change.py","--baseline",str(b),"--provenance",str(p),"--build-contract",str(cp),"--output",str(o))
                self.assertFalse(json.loads(o.read_text())["scheduledAutoPublishEligible"])
        finally:
            legacy["buildContractId"],legacy["urlModelId"]=old

    def test_stale_draft_is_recoverable_not_no_changes(self):
        baseline=json.loads(self.baseline_path.read_text()); basefp=baseline["fingerprintContract"]["baselineInputFingerprint"]
        five=[{"name":n,"id":i} for i,n in enumerate(self.contract["legacyAssetSetTags"]["2026.09.25.3"],1)]
        six=[{"name":n,"id":i+20} for i,n in enumerate(self.contract["artifactSet"],1)]
        releases=[
          {"tag_name":"2026.09.25.3","draft":False,"published_at":"2026-09-25T14:42:21Z","immutable":True,
           "body":f"INPUT_FINGERPRINT={basefp}","assets":five},
          {"tag_name":"2099.01.01.1","draft":True,"published_at":None,"immutable":False,
           "body":f"INPUT_FINGERPRINT={FP}","assets":six},
        ]
        state=release_state.analyze_releases(releases,baseline,self.contract,basefp,FP,lambda r:basefp)
        self.assertFalse(state["noChanges"]); self.assertTrue(state["staleDraftMatch"])
        releases[1]["body"]=""
        with self.assertRaises(SystemExit):
            release_state.analyze_releases(releases,baseline,self.contract,basefp,FP,lambda r:basefp)

    def test_post_publish_and_latest_verifier(self):
        with tempfile.TemporaryDirectory() as td:
            bundle,_=self.make_bundle(td); latest=Path(td)/"latest"; latest.mkdir()
            for n in ("UDAL-GEOIP.dat","UDAL-GEOSITE.dat"): (latest/n).write_bytes((bundle/n).read_bytes())
            assets=[{"name":n,"digest":"sha256:"+sha(bundle/n)} for n in self.contract["artifactSet"]]
            obj={"tag_name":TAG,"draft":False,"published_at":"2099-01-01T00:00:00Z","prerelease":False,"immutable":True,"assets":assets}
            rj=Path(td)/"r.json"; lj=Path(td)/"l.json"; rj.write_text(json.dumps(obj)); lj.write_text(json.dumps(obj))
            res=run(PY,"scripts/verify-published-release.py","--release-json",str(rj),"--latest-json",str(lj),
                "--bundle",str(bundle),"--latest-dir",str(latest),"--build-contract",str(self.build_contract_path),"--tag",TAG)
            self.assertIn("VERIFY_PUBLISHED_RELEASE=PASS",res.stdout)
            (latest/"UDAL-GEOIP.dat").write_bytes(b"wrong")
            res=run(PY,"scripts/verify-published-release.py","--release-json",str(rj),"--latest-json",str(lj),
                "--bundle",str(bundle),"--latest-dir",str(latest),"--build-contract",str(self.build_contract_path),"--tag",TAG,check=False)
            self.assertNotEqual(res.returncode,0)


if __name__=="__main__":
    unittest.main()
