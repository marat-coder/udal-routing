#!/usr/bin/env python3
import copy
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from common import (
    BASELINE,
    BUILD_CONTRACT,
    FP,
    GEO,
    LAST,
    POLICY,
    PY,
    REPO,
    REL,
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

def load_script(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

normalizer=load_script("normalize_run_mode_test","normalize-run-mode.py")


class PhaseB2Tests(unittest.TestCase):
    def classify(self,root,current_prod,prov,build_contract=BUILD_CONTRACT,check=True):
        root=Path(root)
        cp=root/"current-production.json"
        pp=root/"candidate-provenance.json"
        out=root/"change.json"
        cp.write_text(json.dumps(current_prod,indent=2)+"\n")
        pp.write_text(json.dumps(prov,indent=2)+"\n")
        p=run(
            PY,"scripts/classify-change.py",
            "--current-production",str(cp),
            "--provenance",str(pp),
            "--build-contract",str(build_contract),
            "--output",str(out),
            check=check,
        )
        return p,(json.loads(out.read_text()) if out.exists() else None)

    def legacy_current_production(self):
        b=json.loads(BASELINE.read_text())
        c=json.loads(BUILD_CONTRACT.read_text())
        legacy=c["legacyProductionContract"]
        return {
            "releaseId":396660739,
            "tag":b["baselineRelease"],
            "manifestSchema":1,
            "fingerprintSchema":1,
            "inputFingerprint":b["fingerprintContract"]["baselineInputFingerprint"],
            "lastUpdated":b["routingLastUpdated"],
            "v2flyRelevantHash":legacy["relevantHash"],
            "ruBlockedSha256":b["sources"]["ruBlockedGeosite"]["sha256"],
            "geoipSha256":b["sources"]["geoip"]["sha256"],
            "routingPolicySha256":b["routingPolicySha256"],
            "buildContractSha256":None,
            "buildContractId":legacy["buildContractId"],
            "urlModelId":legacy["urlModelId"],
            "assetSetVersion":1,
            "mode":"legacy-v1",
        }

    def test_workflow_write_token_isolation(self):
        wf=(ROOT/".github/workflows/update-geo.yml").read_text()
        build=wf.split("\n  build:",1)[1].split("\n  draft:",1)[0]
        self.assertIn("permissions:\n      contents: read",build)
        self.assertNotIn("contents: write",build)
        self.assertNotRegex(build,r"(?m)^    env:\n      GH_TOKEN:")
        self.assertIn("persist-credentials: false",build)

        for name in ("Build GeoSite and GeoIP","Validate geodata with Xray"):
            part=build.split(f"- name: {name}",1)[1].split("\n      - name:",1)[0]
            self.assertNotIn("GH_TOKEN",part)

        self.assertEqual(wf.count("contents: write"),1)
        draft=wf.split("\n  draft:",1)[1]
        self.assertIn("permissions:\n      contents: write",draft)
        smoke=wf.split("\n  phase-b-geodata-smoke:",1)[1].split("\n  manifest-v2-determinism:",1)[0]
        self.assertIn("permissions:\n      contents: read",smoke)
        self.assertIn('test -z "${GH_TOKEN:-}"',smoke)
        self.assertIn('test -z "${GITHUB_TOKEN:-}"',smoke)

    def test_draft_job_checkout_precedes_repository_scripts(self):
        wf=(ROOT/".github/workflows/update-geo.yml").read_text()
        draft=wf.split("\n  draft:",1)[1]
        checkout_name="- name: Checkout automation repository"
        checkout_pos=draft.find(checkout_name)
        self.assertGreaterEqual(checkout_pos,0,"draft job checkout missing")
        next_step=draft.find("\n      - name:",checkout_pos+len(checkout_name))
        checkout=draft[checkout_pos:next_step if next_step >= 0 else len(draft)]
        self.assertIn("uses: actions/checkout@v4",checkout)
        self.assertIn("ref: ${{ github.sha }}",checkout)
        self.assertIn("persist-credentials: false",checkout)

        first_repo_script=re.search(r"(?m)^\s+(?:python3\s+)?scripts/[^\s\\]+",draft)
        self.assertIsNotNone(first_repo_script,"draft job has no repository script invocation")
        self.assertLess(checkout_pos,first_repo_script.start())

        for script in (
            "scripts/fetch-release-inventory.py",
            "scripts/check-mutation-state.py",
            "scripts/verify-draft-release.py",
            "scripts/publish-validated-draft.sh",
        ):
            with self.subTest(script=script):
                script_pos=draft.find(script)
                self.assertGreaterEqual(script_pos,0,f"draft job missing {script}")
                self.assertLess(checkout_pos,script_pos)

    def test_scheduled_publish_step_requires_explicit_bash_invocation(self):
        wf=(ROOT/".github/workflows/update-geo.yml").read_text()
        draft=wf.split("\n  draft:",1)[1]
        publish_name="- name: Publish exact validated draft on scheduled upstream-only change"
        checkout_name="- name: Checkout automation repository"

        publish_pos=draft.find(publish_name)
        self.assertGreaterEqual(publish_pos,0,"scheduled publish step missing")
        checkout_pos=draft.find(checkout_name)
        self.assertGreaterEqual(checkout_pos,0,"draft job checkout missing")
        self.assertLess(checkout_pos,publish_pos,"checkout must precede publish helper usage")

        next_step=draft.find("\n      - name:",publish_pos+len(publish_name))
        publish_step=draft[publish_pos:next_step if next_step >= 0 else len(draft)]

        helper_invocations=re.findall(
            r"(?m)^\s*(?:(?:bash|python3)\s+)?(scripts/[^\s\\]+)",
            publish_step,
        )
        self.assertEqual(
            helper_invocations,
            ["scripts/publish-validated-draft.sh"],
            "publish step must invoke only the validated-draft helper",
        )
        self.assertRegex(
            publish_step,
            r"(?m)^\s*bash\s+scripts/publish-validated-draft\.sh\s+\\$",
        )
        self.assertNotRegex(
            publish_step,
            r"(?m)^\s*scripts/publish-validated-draft\.sh(?:\s|$)",
        )

    def test_run_mode_normalization_and_workflow_gates(self):
        ci=normalizer.normalize("pull_request")
        self.assertEqual(ci["run_mode"],"ci")
        self.assertFalse(ci["run_build"])
        self.assertTrue(ci["dry_run"])
        self.assertFalse(ci["auto_publish"])

        scheduled=normalizer.normalize("schedule")
        self.assertEqual(scheduled["run_mode"],"scheduled")
        self.assertTrue(scheduled["run_build"])
        self.assertTrue(scheduled["auto_publish"])
        self.assertFalse(scheduled["dry_run"])

        manual=normalizer.normalize("workflow_dispatch","false","false","false")
        self.assertEqual(manual["run_mode"],"manual")
        self.assertTrue(manual["run_build"])
        self.assertFalse(manual["auto_publish"])

        manifest=normalizer.normalize("workflow_dispatch","false","true","true")
        self.assertEqual(manifest["run_mode"],"manifest-test")
        self.assertFalse(manifest["run_build"])

        wf=(ROOT/".github/workflows/update-geo.yml").read_text()
        self.assertIn("needs.mode.outputs.run_mode == 'ci'",wf)
        self.assertIn("needs.mode.outputs.run_mode == 'scheduled'",wf)
        self.assertIn("needs.mode.outputs.run_mode == 'manual' || needs.build.outputs.schedule_eligible == 'true'",wf)
        self.assertIn("needs.mode.outputs.auto_publish == 'true' && needs.build.outputs.schedule_eligible == 'true'",wf)

    def test_initial_legacy_to_v2_migration_manual_only(self):
        prod=self.legacy_current_production()
        prov=base_provenance()
        prov["domainListCommunity"]["relevantHash"]=prod["v2flyRelevantHash"]
        prov["ruBlockedGeosite"]["sha256"]=prod["ruBlockedSha256"]
        prov["geoip"]["sha256"]=prod["geoipSha256"]
        prov["routingPolicySha256"]=prod["routingPolicySha256"]
        with tempfile.TemporaryDirectory() as td:
            _,out=self.classify(td,prod,prov)
        self.assertIn("BUILD_CONTRACT",out["changeReasons"])
        self.assertIn("URL_MODEL",out["changeReasons"])
        self.assertIn("FINGERPRINT_SCHEMA",out["changeReasons"])
        self.assertFalse(out["scheduledAutoPublishEligible"])

    def test_post_migration_upstream_only_is_schedule_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            bundle,prov_path=make_bundle(td)
            release=release_for_bundle(bundle)
            _,cp_path=inspect_v2(td,bundle,release)
            prod=json.loads(cp_path.read_text())
            prov=json.loads(prov_path.read_text())
            prov["geoip"]["sha256"]="9"*64
            with tempfile.TemporaryDirectory() as work:
                _,out=self.classify(work,prod,prov)
            self.assertEqual(out["changeReasons"],["GEOIP_CONTENT"])
            self.assertTrue(out["scheduledAutoPublishEligible"])

    def test_mixed_upstream_and_policy_change_blocks_schedule(self):
        with tempfile.TemporaryDirectory() as td:
            bundle,prov_path=make_bundle(td)
            _,cp_path=inspect_v2(td,bundle,release_for_bundle(bundle))
            prod=json.loads(cp_path.read_text())
            prov=json.loads(prov_path.read_text())
            prov["geoip"]["sha256"]="9"*64
            prov["routingPolicySha256"]="8"*64
            with tempfile.TemporaryDirectory() as work:
                _,out=self.classify(work,prod,prov)
            self.assertIn("GEOIP_CONTENT",out["changeReasons"])
            self.assertIn("ROUTING_POLICY",out["changeReasons"])
            self.assertFalse(out["scheduledAutoPublishEligible"])

    def test_same_id_build_contract_hash_drift_blocks_schedule(self):
        with tempfile.TemporaryDirectory() as td:
            bundle,prov_path=make_bundle(td)
            _,cp_path=inspect_v2(td,bundle,release_for_bundle(bundle))
            prod=json.loads(cp_path.read_text())
            prov=json.loads(prov_path.read_text())
            self.assertEqual(prov["buildContractId"],prod["buildContractId"])
            prov["buildContractSha256"]="e"*64
            with tempfile.TemporaryDirectory() as work:
                _,out=self.classify(work,prod,prov)
            self.assertIn("BUILD_CONTRACT",out["changeReasons"])
            self.assertFalse(out["scheduledAutoPublishEligible"])

    def test_malformed_or_unverifiable_current_production_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            bundle,_=make_bundle(td)
            release=release_for_bundle(bundle)
            manifest_path=bundle/"MANIFEST.json"
            manifest=json.loads(manifest_path.read_text())
            manifest.pop("buildContract")
            manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
            for asset in release["assets"]:
                if asset["name"]=="MANIFEST.json":
                    asset["digest"]="sha256:"+sha(manifest_path)
                    asset["size"]=manifest_path.stat().st_size
            p,_=inspect_v2(td,bundle,release,check=False)
            self.assertNotEqual(p.returncode,0)
            self.assertIn("control-plane metadata missing",p.stderr)

        with tempfile.TemporaryDirectory() as td:
            bundle,_=make_bundle(td)
            release=release_for_bundle(bundle,immutable=None)
            p,_=inspect_v2(td,bundle,release,check=False)
            self.assertNotEqual(p.returncode,0)
            self.assertIn("immutable contract missing",p.stderr)

    def test_release_state_uses_current_production_fingerprint(self):
        prod={
            "tag":"2099.01.01.1",
            "inputFingerprint":FP,
            "lastUpdated":LAST,
        }
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            cp=root/"cp.json"; out=root/"state.json"
            cp.write_text(json.dumps(prod))
            run(PY,"scripts/release-state.py",
                "--current-production",str(cp),
                "--current-fingerprint",FP,
                "--run-number","42",
                "--output",str(out))
            state=json.loads(out.read_text())
            self.assertTrue(state["noChanges"])
            self.assertTrue(state["publishedFingerprintMatch"])
            self.assertTrue(state["newTag"].endswith(".42"))

    def test_stale_draft_and_tag_collision_fail_closed(self):
        clean=[{"tag_name":"2026.09.25.3","draft":False,"body":"INPUT_FINGERPRINT="+"2"*64}]
        stale=clean+[{"tag_name":"2099.01.01.2","draft":True,"body":"INPUT_FINGERPRINT="+FP}]
        collision=clean+[{"tag_name":TAG,"draft":True,"body":"INPUT_FINGERPRINT="+"3"*64}]
        for name,releases,should_pass in (
            ("clean",clean,True),
            ("stale",stale,False),
            ("collision",collision,False),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root=Path(td); rp=root/"releases.json"; out=root/"out.json"
                rp.write_text(json.dumps(releases))
                p=run(PY,"scripts/check-mutation-state.py",
                    "--releases-json",str(rp),
                    "--planned-tag",TAG,
                    "--fingerprint",FP,
                    "--output",str(out),
                    check=False)
                self.assertEqual(p.returncode==0,should_pass)

    def test_draft_verifier_binds_rid_tag_and_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); bundle,_=make_bundle(root)
            release=release_for_bundle(bundle,draft=True)
            rj=root/"release.json"; rj.write_text(json.dumps(release))
            base=[
                PY,"scripts/verify-draft-release.py",
                "--release-json",str(rj),
                "--bundle",str(bundle),
                "--build-contract",str(BUILD_CONTRACT),
                "--expected-rid","123",
                "--expected-tag",TAG,
            ]
            self.assertEqual(run(*base,check=False).returncode,0)

            wrong=copy.deepcopy(release); wrong["id"]=999; rj.write_text(json.dumps(wrong))
            self.assertNotEqual(run(*base,check=False).returncode,0)

            wrong=copy.deepcopy(release); wrong["tag_name"]="2099.01.01.999"; rj.write_text(json.dumps(wrong))
            self.assertNotEqual(run(*base,check=False).returncode,0)

            wrong=copy.deepcopy(release); wrong["assets"][0]["digest"]="sha256:"+"0"*64; rj.write_text(json.dumps(wrong))
            self.assertNotEqual(run(*base,check=False).returncode,0)

    def published_verify(self,td,immutable):
        root=Path(td); bundle,_=make_bundle(root)
        latest_dir=root/"latest"; latest_dir.mkdir()
        for name in ("UDAL-GEOIP.dat","UDAL-GEOSITE.dat"):
            (latest_dir/name).write_bytes((bundle/name).read_bytes())
        release=release_for_bundle(bundle,immutable=immutable)
        latest=release_for_bundle(bundle,immutable=True)
        rj=root/"release.json"; lj=root/"latest.json"
        rj.write_text(json.dumps(release)); lj.write_text(json.dumps(latest))
        return run(PY,"scripts/verify-published-release.py",
            "--release-json",str(rj),
            "--latest-json",str(lj),
            "--bundle",str(bundle),
            "--latest-dir",str(latest_dir),
            "--build-contract",str(BUILD_CONTRACT),
            "--tag",TAG,
            "--release-id","123",
            check=False)

    def test_immutable_true_passes_missing_and_false_fail(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self.published_verify(td,True).returncode,0)
        with tempfile.TemporaryDirectory() as td:
            self.assertNotEqual(self.published_verify(td,None).returncode,0)
        with tempfile.TemporaryDirectory() as td:
            self.assertNotEqual(self.published_verify(td,False).returncode,0)

    def make_fake_publish_tools(self,root,bundle,draft,pending,final,latest,immutable_after):
        root=Path(root)
        fakebin=root/"fakebin"; fakebin.mkdir()
        state=root/"state"; state.mkdir()
        for name,obj in (("draft",draft),("pending",pending),("final",final),("latest",latest)):
            (state/f"{name}.json").write_text(json.dumps(obj))
        gh=fakebin/"gh"
        gh.write_text("""#!/usr/bin/env python3
import os,sys
from pathlib import Path
state=Path(os.environ["FAKE_STATE"])
args=sys.argv[1:]
joined=" ".join(args)
def emit(name):
    sys.stdout.write((state/f"{name}.json").read_text())
def count(name):
    p=state/name
    n=int(p.read_text()) if p.exists() else 0
    n+=1
    p.write_text(str(n))
    return n
if not args or args[0]!="api":
    raise SystemExit(2)
if "--method" in args and args[args.index("--method")+1]=="PATCH":
    count("patch-count")
    (state/"published").write_text("1")
    emit("pending")
elif "releases/latest" in joined:
    emit("latest")
elif "/releases/" in joined:
    if not (state/"published").exists():
        emit("draft")
    else:
        n=count("poll-count")
        after=int(os.environ.get("FAKE_IMMUTABLE_AFTER","1"))
        emit("final" if n>=after else "pending")
else:
    raise SystemExit(2)
""")
        gh.chmod(0o755)
        curl=fakebin/"curl"
        curl.write_text("""#!/usr/bin/env python3
import os,shutil,sys
from pathlib import Path
args=sys.argv[1:]
out=Path(args[args.index("-o")+1])
url=args[-1]
name=url.rsplit("/",1)[-1]
shutil.copyfile(Path(os.environ["FAKE_BUNDLE"])/name,out)
""")
        curl.chmod(0o755)
        env=os.environ.copy()
        env["PATH"]=str(fakebin)+os.pathsep+env["PATH"]
        env["FAKE_STATE"]=str(state)
        env["FAKE_BUNDLE"]=str(bundle)
        env["FAKE_IMMUTABLE_AFTER"]=str(immutable_after)
        env["IMMUTABLE_POLL_ATTEMPTS"]="3"
        env["IMMUTABLE_POLL_SECONDS"]="0"
        return env,state

    def test_publish_helper_jit_binding_and_bounded_polling(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); bundle,_=make_bundle(root/"fixture")
            draft=release_for_bundle(bundle,draft=True)
            pending=release_for_bundle(bundle,immutable=None)
            final=release_for_bundle(bundle,immutable=True)
            latest=copy.deepcopy(final)
            env,state=self.make_fake_publish_tools(root,bundle,draft,pending,final,latest,2)
            p=run("bash","scripts/publish-validated-draft.sh",
                REPO,TAG,"123",str(bundle),str(BUILD_CONTRACT),str(root/"work"),
                env=env,check=False)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual((state/"patch-count").read_text(),"1")
            self.assertEqual((state/"poll-count").read_text(),"2")
            self.assertIn("PREPUBLISH_JIT_BINDING=PASS",p.stdout)
            self.assertIn("IMMUTABLE_BOUNDED_POLLING=PASS",p.stdout)

    def test_publish_helper_wrong_identity_or_digest_blocks_before_patch(self):
        cases=[]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); bundle,_=make_bundle(root/"fixture")
            good=release_for_bundle(bundle,draft=True)
            wrong_id=copy.deepcopy(good); wrong_id["id"]=999
            wrong_tag=copy.deepcopy(good); wrong_tag["tag_name"]="2099.01.01.999"
            drift=copy.deepcopy(good); drift["assets"][0]["digest"]="sha256:"+"0"*64
            cases=[("rid",wrong_id),("tag",wrong_tag),("digest",drift)]
            for name,draft in cases:
                with self.subTest(name=name):
                    case=root/name; case.mkdir()
                    pending=release_for_bundle(bundle,immutable=None)
                    final=release_for_bundle(bundle,immutable=True)
                    env,state=self.make_fake_publish_tools(case,bundle,draft,pending,final,final,1)
                    p=run("bash","scripts/publish-validated-draft.sh",
                        REPO,TAG,"123",str(bundle),str(BUILD_CONTRACT),str(case/"work"),
                        env=env,check=False)
                    self.assertNotEqual(p.returncode,0)
                    self.assertFalse((state/"patch-count").exists())

    def test_publish_helper_immutable_missing_or_false_fails_bounded(self):
        for label,value in (("missing",None),("false",False)):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root=Path(td); bundle,_=make_bundle(root/"fixture")
                draft=release_for_bundle(bundle,draft=True)
                pending=release_for_bundle(bundle,immutable=value)
                env,state=self.make_fake_publish_tools(root,bundle,draft,pending,pending,pending,999)
                env["IMMUTABLE_POLL_ATTEMPTS"]="2"
                p=run("bash","scripts/publish-validated-draft.sh",
                    REPO,TAG,"123",str(bundle),str(BUILD_CONTRACT),str(root/"work"),
                    env=env,check=False)
                self.assertNotEqual(p.returncode,0)
                self.assertEqual((state/"patch-count").read_text(),"1")
                self.assertEqual((state/"poll-count").read_text(),"2")
                self.assertIn("immutable=true not observed after bounded polling",p.stderr)

    def test_pr_nonmutating_integration_uses_production_build_validation_logic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            bundle_a,prov_a=make_bundle(a)
            bundle_b,prov_b=make_bundle(b)
            from common import validate_bundle
            self.assertEqual(validate_bundle(bundle_a,prov_a).returncode,0)
            self.assertEqual(validate_bundle(bundle_b,prov_b).returncode,0)
            self.assertEqual((bundle_a/"MANIFEST.json").read_bytes(),(bundle_b/"MANIFEST.json").read_bytes())
            self.assertEqual((bundle_a/"SHA256SUMS").read_bytes(),(bundle_b/"SHA256SUMS").read_bytes())


if __name__=="__main__":
    unittest.main()
