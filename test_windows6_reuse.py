"""Synthetic Windows6 guard tests: no download, model, install or real learning data."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('windows6_reuse',ROOT/'ci-mac-reuse.py')
reuse=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse)


class WindowsSixReuseTest(unittest.TestCase):
    def setUp(self):
        self.pending=json.loads((ROOT/'windows-k12-6-reuse-lock.json').read_text())
        self.lock=copy.deepcopy(self.pending)
        self.lock['execution_frozen']=True
        self.lock['recipe_inputs_sha256']={k:(v or 'a'*64) for k,v in self.lock['recipe_inputs_sha256'].items()}
        self.raw=(ROOT/'attachment-final-manifests.json').read_bytes()

    def reject(self,change):
        d=copy.deepcopy(self.lock);change(d)
        with self.assertRaises((AssertionError,KeyError,TypeError)):
            reuse.validate_lock(d,self.raw)

    def test_exact_synthetic_lock_without_network_or_execution(self):
        with patch.object(reuse,'api',side_effect=AssertionError('no network')),patch.object(reuse,'run',side_effect=AssertionError('no execution')):
            self.assertEqual(len(reuse.validate_lock(self.lock,self.raw)['manifests']),45)

    def test_pending_lock_cannot_execute(self):
        pending=copy.deepcopy(self.pending);pending['execution_frozen']=False
        with self.assertRaisesRegex(AssertionError,'not yet owner-frozen'):
            reuse.validate_lock(pending,self.raw)

    def test_source_run_head_job_stage_release_platform_cannot_be_substituted(self):
        for key,value in [('target','macos-x64'),('source_commit','9328240380d13ef75435434a8c901028ea4470dc'),('candidate_release_id',448792391),('baseline_latest_id',1),('baseline_latest_tag','student-20261117-k12-2'),('original_native_run',44132557405),('original_native_workflow_commit','0'*40),('original_failed_job',134213284667),('stage_delivery_commit','0'*40),('launcher_build','20261117-updater-2')]:
            with self.subTest(key=key):self.reject(lambda d:d.update({key:value}))
        with self.assertRaises(AssertionError):reuse.validate_lock(self.lock,self.raw+b'\n')

    def test_each_asset_identity_size_sha_url_must_be_exact_even_if_changed_consistently(self):
        for key,value in [('id',999),('bytes',1),('sha256','0'*64),('url','https://example.com/f')]:
            def change(d):
                name=d['candidate_files'][0]['name'];d['candidate_files'][0][key]=value
                next(r for r in d['immutable_existing_assets'] if r['name']==name)[key]=value
            with self.subTest(key=key):self.reject(change)
        for key in ['core_asset','bridge','prior_manifest','prior_manifest_asset','prior_core_asset','baseline_feeds','native_pages']:
            with self.subTest(key=key):self.reject(lambda d:d.update({key:{}}))
        self.reject(lambda d:d['signed_runtime_assets'].pop())
        self.reject(lambda d:d['immutable_existing_assets'].pop())

    def test_no_candidate5_partial_receipts_or_fresh_reuse(self):
        for key in ['resume_artifact','reused_complete_entries','reused_fresh_picture_ui']:
            with self.subTest(key=key):self.reject(lambda d:d.update({key:{}}))

    def test_missing_unfrozen_unsafe_recipe_inputs_and_wrong_counts_rejected(self):
        for change in [lambda d:d['recipe_inputs_sha256'].pop('ci_update_probe.py'),lambda d:d['recipe_inputs_sha256'].update({'ci-update-flow.cjs':None}),lambda d:d['recipe_inputs_sha256'].update({'../escape':'a'*64}),lambda d:d['launcher_tests'].update(skipped=5)]:self.reject(change)
        for name in ['ci-materials-ui.cjs','native-materials-fixture.py','attachment-final-manifests.json']:
            with self.subTest(name=name):self.reject(lambda d:d['recipe_inputs_sha256'].pop(name))

    def metadata(self):
        return [{'id':448283800},{'id':449332202,'tag_name':'student-20261117-k12-6','prerelease':True,'draft':False,'assets':[dict(name=r['name'],id=r['id'],size=r['bytes'],digest='sha256:'+r['sha256']) for r in self.lock['immutable_existing_assets']]},{'assets':[dict(name=n,digest='sha256:'+s) for n,s in self.lock['baseline_feeds'].items()]}]

    def test_latest4_all_existing6_and_stable_feeds_remain_exact(self):
        with patch.object(reuse,'api',side_effect=self.metadata()),patch.object(reuse,'gh',side_effect=AssertionError('no write')):
            self.assertEqual(reuse.verify_metadata(self.lock)['id'],449332202)
        for index in range(3):
            responses=self.metadata()
            if index==0:responses[0]['id']=449332202
            elif index==1:responses[1]['assets'][-1]['id']+=1
            else:responses[2]['assets'][0]['digest']='sha256:'+'0'*64
            with patch.object(reuse,'api',side_effect=responses),self.assertRaises(AssertionError):reuse.verify_metadata(self.lock)

    def test_evidence_permission_kept_but_no_overwrite_or_foreign_target(self):
        with patch.object(reuse,'api',return_value={'assets':[{'name':'verification-windows-x64.json'}]}),patch.object(reuse,'gh',side_effect=AssertionError('no write')),self.assertRaises(AssertionError):
            reuse.upload_new(self.lock['candidate_tag'],Path('verification-windows-x64.json'),'windows-x64')
        for target,name in [('macos-x64','verification-macos-x64.json'),('windows-x64','kaixin-bridge-20261117-k12-6-windows-x64.tar.gz')]:
            with self.assertRaises(AssertionError):reuse.upload_new(self.lock['candidate_tag'],Path(name),target)

    def test_all_four_actual_entries_required_before_native_picture_proofs(self):
        good={'actual_download_install_backup_restart':'passed','check_again_current':True,'to_launcher':'20261118-updater-3','chat_preserved':True,'task_preserved':True,'saved_key_preserved':True}
        # Invalid entry must be rejected before any API/native-page proof can be consulted.
        for i in range(4):
            entries=[dict(good) for _ in range(4)];entries[i]['chat_preserved']=False
            with self.assertRaises(AssertionError):reuse.validate_native_proofs({},None,entries[0],entries[1],self.lock,entries[2],entries[3])

    def test_operational_path_remains_no_rebuild_and_no_automatic_partial_retry(self):
        source=(ROOT/'ci-mac-reuse.py').read_text();tree=ast.parse(source)
        calls={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertNotIn('prepare_candidate',calls);self.assertNotIn('prepare_bridge',calls)
        self.assertNotIn('--clobber',source);self.assertNotIn('signing-private',source)
        self.assertEqual(source.count('verify_update_entry(root,target,install,resources,home,evidence'),4)
        self.assertIn("if six:assert counts==lock['launcher_tests']",source)
        self.assertIn('immutable-assets-before.json',source);self.assertIn('immutable-assets-after.json',source)
        self.assertIn("oldest_and_current_ipc_rerun=not bool(completed)",source)
        workflow=(ROOT/'.github/workflows/k12-windows6-reverify.yml').read_text()
        self.assertIn('contents: write',workflow);self.assertIn('actions: read',workflow)
        self.assertIn('runs-on: windows-2025',workflow);self.assertNotIn('matrix:',workflow)
        self.assertIn('KX_REUSE_LOCK_SHA256',workflow);self.assertNotIn('choco install nsis',workflow)


if __name__=='__main__':unittest.main()
