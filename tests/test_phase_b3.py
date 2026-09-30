#!/usr/bin/env python3
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from common import (
    BASELINE,
    BUILD_CONTRACT,
    FP,
    GEO,
    POLICY,
    PY,
    REL,
    REPO,
    ROOT,
    RU,
    TAG,
    base_provenance,
    inspect_v2,
    make_bundle,
    release_for_bundle,
    run,
    sha,
)

SCRIPTS=ROOT/"scripts"


def load_script(name,filename):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fingerprint_v2=load_script("fingerprint_v2_test","fingerprint_v2.py")
inventory=load_script("fetch_release_inventory_test","fetch-release-inventory.py")


class PhaseB3FingerprintTests(unittest.TestCase):
    def update_manifest_release(self,bundle,release,mutator):
        manifest_path=Path(bundle)/"MANIFEST.json"
        manifest=json.loads(manifest_path.read_text())
        mutator(manifest)
        manifest_path.write_text(
            json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
            encoding="utf-8",
        )
        for asset in release["assets"]:
            if asset["name"]=="MANIFEST.json":
                asset["digest"]="sha256:"+sha(manifest_path)
                asset["size"]=manifest_path.stat().st_size
                break
        return manifest

    def assert_inspection_fails_after_mutation(self,mutator):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            bundle,_=make_bundle(root)
            release=release_for_bundle(bundle)
            self.update_manifest_release(bundle,release,mutator)
            p,_=inspect_v2(root,bundle,release,check=False)
            self.assertNotEqual(p.returncode,0,p.stdout)
            return p

    def classify(self,root,current_prod,prov,check=True):
        root=Path(root)
        cp=root/"current-production.json"
        pp=root/"candidate-provenance.json"
        out=root/"change.json"
        cp.write_text(json.dumps(current_prod))
        pp.write_text(json.dumps(prov))
        p=run(
            PY,"scripts/classify-change.py",
            "--current-production",str(cp),
            "--provenance",str(pp),
            "--build-contract",str(BUILD_CONTRACT),
            "--output",str(out),
            check=check,
        )
        return p,(json.loads(out.read_text()) if out.exists() else None)

    def test_candidate_fingerprint_cli_matches_shared_helper(self):
        raw={
            "domainListCommunity":{
                "repository":"v2fly/domain-list-community",
                "commit":"a"*40,
                "timestamp":"2099-01-01T00:00:00Z",
            },
            "ruBlockedGeosite":{"sha256":RU},
            "geoip":{"sha256":GEO},
        }
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            src=root/"raw.json"
            out=root/"out.json"
            src.write_text(json.dumps(raw))
            run(
                PY,"scripts/make-fingerprint.py",
                "--provenance",str(src),
                "--relevant-hash",REL,
                "--policy",str(POLICY),
                "--fingerprint-schema","v2",
                "--build-contract",str(BUILD_CONTRACT),
                "--output",str(out),
            )
            got=json.loads(out.read_text())
            expected_fp,expected_components=fingerprint_v2.build_fingerprint_v2(
                v2fly_relevant_hash=REL,
                ru_blocked_sha256=RU,
                geoip_sha256=GEO,
                routing_policy_sha256=sha(POLICY),
                build_contract_sha256=sha(BUILD_CONTRACT),
            )
            self.assertEqual(got["inputFingerprint"],expected_fp)
            self.assertEqual(got["fingerprintComponents"],expected_components)
            self.assertEqual(got["fingerprintSchema"],2)

    def test_valid_v2_current_production_recomputes_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            bundle,prov_path=make_bundle(root)
            release=release_for_bundle(bundle)
            p,out_path=inspect_v2(root,bundle,release)
            self.assertEqual(p.returncode,0)
            inspected=json.loads(out_path.read_text())
            prov=json.loads(prov_path.read_text())
            expected_fp,expected_components=fingerprint_v2.build_fingerprint_v2(
                v2fly_relevant_hash=prov["domainListCommunity"]["relevantHash"],
                ru_blocked_sha256=prov["ruBlockedGeosite"]["sha256"],
                geoip_sha256=prov["geoip"]["sha256"],
                routing_policy_sha256=prov["routingPolicySha256"],
                build_contract_sha256=prov["buildContractSha256"],
            )
            self.assertEqual(inspected["inputFingerprint"],expected_fp)
            self.assertEqual(prov["fingerprintComponents"],expected_components)

            changed=copy.deepcopy(prov)
            changed["geoip"]["sha256"]="9"*64
            with tempfile.TemporaryDirectory() as work:
                _,result=self.classify(work,inspected,changed)
            self.assertEqual(result["changeReasons"],["GEOIP_CONTENT"])
            self.assertTrue(result["scheduledAutoPublishEligible"])

    def test_buildplan_fingerprint_mismatch_fails(self):
        p=self.assert_inspection_fails_after_mutation(
            lambda m:m["buildPlan"].__setitem__("inputFingerprint","0"*64)
        )
        self.assertIn("buildPlan.inputFingerprint",p.stderr)

    def test_source_fingerprint_mismatch_fails(self):
        p=self.assert_inspection_fails_after_mutation(
            lambda m:m["source"].__setitem__("inputFingerprint","0"*64)
        )
        self.assertIn("source.inputFingerprint",p.stderr)

    def test_fingerprint_components_value_mismatches_fail(self):
        cases={
            "v2flyRelevantHash":"e"*64,
            "ruBlockedSha256":"e"*64,
            "geoipSha256":"e"*64,
            "routingPolicySha256":"e"*64,
            "buildContractSha256":"e"*64,
            "fingerprintSchema":99,
        }
        for key,value in cases.items():
            with self.subTest(key=key):
                p=self.assert_inspection_fails_after_mutation(
                    lambda m,k=key,v=value:m["source"]["fingerprintComponents"].__setitem__(k,v)
                )
                self.assertNotEqual(p.returncode,0)

    def test_fingerprint_components_structural_failures(self):
        mutations=[
            lambda m:m["source"]["fingerprintComponents"].pop("geoipSha256"),
            lambda m:m["source"]["fingerprintComponents"].__setitem__("unexpectedKey","x"),
            lambda m:m["source"]["fingerprintComponents"].__setitem__("ruBlockedSha256","bad"),
            lambda m:m["source"].__setitem__("routingPolicySha256","f"*64),
        ]
        for i,mutation in enumerate(mutations):
            with self.subTest(case=i):
                p=self.assert_inspection_fails_after_mutation(mutation)
                self.assertNotEqual(p.returncode,0)

    def test_same_id_build_contract_hash_drift_still_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            bundle,prov_path=make_bundle(root)
            release=release_for_bundle(bundle)
            _,cp_path=inspect_v2(root,bundle,release)
            prod=json.loads(cp_path.read_text())
            prov=json.loads(prov_path.read_text())
            self.assertEqual(prod["buildContractId"],prov["buildContractId"])
            prov["buildContractSha256"]="e"*64
            with tempfile.TemporaryDirectory() as work:
                _,result=self.classify(work,prod,prov)
            self.assertIn("BUILD_CONTRACT",result["changeReasons"])
            self.assertFalse(result["scheduledAutoPublishEligible"])


class PhaseB3ReleaseInventoryTests(unittest.TestCase):
    def release(self,i,*,draft=False,fp=None,tag=None):
        body=""
        if fp is not None:
            body=f"INPUT_FINGERPRINT={fp}"
        return {
            "id":i,
            "tag_name":tag or f"2098.12.31.{i}",
            "draft":draft,
            "body":body,
        }

    def collect(self,pages,max_pages=100):
        def fetcher(page):
            value=pages[page-1]
            if isinstance(value,Exception):
                raise value
            return value
        return inventory.fetch_all_releases(
            REPO,
            per_page=100,
            max_pages=max_pages,
            fetcher=fetcher,
        )

    def mutation_check(self,releases,check=True):
        td=tempfile.TemporaryDirectory()
        root=Path(td.name)
        src=root/"releases.json"
        out=root/"out.json"
        src.write_text(json.dumps(releases))
        p=run(
            PY,"scripts/check-mutation-state.py",
            "--releases-json",str(src),
            "--planned-tag",TAG,
            "--fingerprint",FP,
            "--output",str(out),
            check=check,
        )
        return td,p

    def test_stale_draft_beyond_first_100_is_detected(self):
        first=[self.release(i) for i in range(1,101)]
        second=[self.release(101,draft=True,fp=FP),self.release(102)]
        releases=self.collect([first,second])
        self.assertEqual(len(releases),102)
        td,p=self.mutation_check(releases,check=False)
        try:
            self.assertNotEqual(p.returncode,0)
            self.assertIn("STALE_DRAFT_REVALIDATION_REQUIRED",p.stderr)
        finally:
            td.cleanup()

    def test_multiple_pages_without_stale_draft_pass(self):
        first=[self.release(i) for i in range(1,101)]
        second=[self.release(i) for i in range(101,151)]
        releases=self.collect([first,second])
        td,p=self.mutation_check(releases,check=False)
        try:
            self.assertEqual(p.returncode,0,p.stderr)
        finally:
            td.cleanup()

    def test_later_page_failure_or_malformed_page_fails_closed(self):
        first=[self.release(i) for i in range(1,101)]
        with self.assertRaises(RuntimeError):
            self.collect([first,inventory.InventoryError("synthetic page failure")])
        with self.assertRaises(inventory.InventoryError):
            self.collect([first,{"not":"a list"}])

    def test_exact_multiple_of_100_requires_terminal_page(self):
        first=[self.release(i) for i in range(1,101)]
        second=[self.release(i) for i in range(101,201)]
        releases=self.collect([first,second,[]])
        self.assertEqual(len(releases),200)
        self.assertEqual(releases[-1]["id"],200)

    def test_hard_limit_and_duplicate_identity_fail_closed(self):
        full=[self.release(i) for i in range(1,101)]
        with self.assertRaises(inventory.InventoryError):
            self.collect([full],max_pages=1)

        first=[self.release(i) for i in range(1,101)]
        duplicate=[self.release(100),self.release(101)]
        with self.assertRaises(inventory.InventoryError):
            self.collect([first,duplicate])

    def test_planned_tag_collision_guard_preserved(self):
        releases=[self.release(1,tag=TAG)]
        td,p=self.mutation_check(releases,check=False)
        try:
            self.assertNotEqual(p.returncode,0)
            self.assertIn("planned tag already exists",p.stderr)
        finally:
            td.cleanup()


if __name__=="__main__":
    unittest.main()
