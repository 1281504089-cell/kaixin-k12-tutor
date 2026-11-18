"""Intel7 immutable-recheck controls; no network, model calls or installation."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from batch7_recheck import REQUIRED_INPUTS,validate_intel7_execution

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('intel7_reuse',ROOT/'ci-mac-reuse.py')
reuse=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse)


class IntelSevenReuseTest(unittest.TestCase):
    def setUp(self):
        self.pending=json.loads((ROOT/'intel-k12-7-reuse-lock.json').read_text())
        self.lock=copy.deepcopy(self.pending)
        self.lock['execution_frozen']=True
        self.lock['recipe_inputs_sha256']={name:'a'*64 for name in REQUIRED_INPUTS}
        self.raw=(ROOT/'attachment-final-manifests.json').read_bytes()

    def reject(self,change):
        changed=copy.deepcopy(self.lock);change(changed)
        with self.assertRaises((AssertionError,KeyError,TypeError)):
            reuse.validate_lock(changed,self.raw)

    def test_exact_synthetic_lock_is_read_only(self):
        with patch.object(reuse,'api',side_effect=AssertionError('no network')),patch.object(reuse,'run',side_effect=AssertionError('no execution')):
            self.assertEqual(len(reuse.validate_lock(self.lock,self.raw)['manifests']),45)

    def test_owner_pending_empty_inputs_and_optimized_execution_are_rejected(self):
        pending=copy.deepcopy(self.lock);pending['execution_frozen']=False
        with self.assertRaisesRegex(AssertionError,'not yet owner-frozen'):reuse.validate_lock(pending,self.raw)
        self.reject(lambda d:d.update(recipe_inputs_sha256={}))
        result=subprocess.run([sys.executable,'-O','-c',"from batch7_recheck import validate_intel7_lock;validate_intel7_lock({},b'')"],cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('assertions must remain enabled',result.stderr)

    def test_source_run_head_job_stage_release_platform_are_pinned(self):
        for key,value in [('target','macos-arm64'),('candidate_tag','student-20261117-k12-6'),('candidate_release_id',449332202),('source_commit','0'*40),('launcher_build','20261118-updater-3'),('baseline_latest_id',1),('baseline_latest_tag','student-20261117-k12-2'),('original_native_run',44202602948),('original_native_workflow_commit','0'*40),('original_failed_job',134460266559),('stage_delivery_commit','0'*40)]:
            with self.subTest(key=key):self.reject(lambda d:d.update({key:value}))
        self.reject(lambda d:d['frozen_stage'].update(sha256='0'*64))
        with self.assertRaises(AssertionError):reuse.validate_lock(self.lock,self.raw+b' ')

    def test_consistently_substituted_asset_ids_bytes_sha_and_urls_are_rejected(self):
        for field,value in [('id',1),('bytes',1),('sha256','0'*64),('url','https://example.com/f')]:
            def change(d):
                name=d['candidate_files'][0]['name'];d['candidate_files'][0][field]=value
                next(row for row in d['immutable_existing_assets'] if row['name']==name)[field]=value
            with self.subTest(field=field):self.reject(change)
        for key in ['core_asset','bridge','prior_manifest','prior_manifest_asset','prior_core_asset','baseline_feeds','native_pages']:
            with self.subTest(key=key):self.reject(lambda d:d.update({key:{}}))
        self.reject(lambda d:d['signed_runtime_assets'].pop())
        self.reject(lambda d:d['immutable_existing_assets'].pop())

    def test_all_mutable_qa_inputs_and_83_mac_tests_are_required(self):
        for name in REQUIRED_INPUTS:
            with self.subTest(name=name):self.reject(lambda d:d['recipe_inputs_sha256'].pop(name))
        for name in ['../outside','/private/file','x\\escape']:
            with self.subTest(name=name):self.reject(lambda d:d['recipe_inputs_sha256'].update({name:'a'*64}))
        self.reject(lambda d:d['recipe_inputs_sha256'].update({'ci-k12-library-ui.cjs':None}))
        self.reject(lambda d:d['launcher_tests'].update({'tests':82,'pass':82}))
        self.reject(lambda d:d['launcher_tests'].update(skipped=1))

    def test_no_partial_receipts_or_fresh_picture_reuse(self):
        for key in ['resume_artifact','reused_complete_entries','reused_fresh_picture_ui']:
            with self.subTest(key=key):self.reject(lambda d:d.update({key:{}}))

    def test_preflight_callers_and_their_original_fixtures_must_be_bound(self):
        callers_and_fixtures={
            'test_mac_reuse.py','test_k12_5_reuse.py','partial_native_evidence.py',
            'frozen-k12-4-manifests.json','frozen-k12-5-manifests.json',
            'windows-k12-4-reuse-lock.json','arm-k12-4-reuse-lock.json','intel-k12-4-reuse-lock.json',
            'intel-k12-5-reuse-lock.json','ci-k12-library-ui.visibility-baseline.cjs',
            'ci-k12-library-ui.click-baseline.cjs','ci-update-flow.baseline.cjs',
            'ci-update-flow.disposal-baseline.cjs','ci-update-flow.backup-baseline.cjs',
            'materials-launcher-src/i18n.mjs',
        }
        self.assertTrue(callers_and_fixtures <= REQUIRED_INPUTS)
        for name in callers_and_fixtures:
            with self.subTest(name=name):self.reject(lambda d:d['recipe_inputs_sha256'].pop(name))

    def test_execution_needs_raw_sha_expected_branch_new_run_and_clean_directory(self):
        raw=json.dumps(self.lock).encode();env={'KX_REUSE_LOCK_SHA256':hashlib.sha256(raw).hexdigest(),'GITHUB_REF_NAME':'codex/k12-intel7-reverify-20261118-test','GITHUB_RUN_ID':'44240000000','GITHUB_SHA':'a'*40}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);validate_intel7_execution(root,raw,env)
            for key,value in [('KX_REUSE_LOCK_SHA256','0'*64),('GITHUB_REF_NAME','codex/k12-native-20261117-7'),('GITHUB_RUN_ID','44230306905'),('GITHUB_SHA','short')]:
                with self.subTest(key=key),self.assertRaises(AssertionError):validate_intel7_execution(root,raw,{**env,key:value})
            for name in ['macos-x64-reuse-work','prior-update','materials-baseline','student-source','launcher-tests-macos-x64']:
                (root/name).mkdir()
                with self.subTest(name=name),self.assertRaises(AssertionError):validate_intel7_execution(root,raw,env)
                (root/name).rmdir()

    def test_metadata_and_evidence_uploads_never_mutate_existing_assets(self):
        metadata=[{'id':448283800},{'id':449471487,'tag_name':self.lock['candidate_tag'],'prerelease':True,'draft':False,'assets':[dict(name=r['name'],id=r['id'],size=r['bytes'],digest='sha256:'+r['sha256']) for r in self.lock['immutable_existing_assets']]},{'assets':[dict(name=n,digest='sha256:'+d) for n,d in self.lock['baseline_feeds'].items()]}]
        with patch.object(reuse,'api',side_effect=copy.deepcopy(metadata)),patch.object(reuse,'gh',side_effect=AssertionError('no writes')):self.assertEqual(reuse.verify_metadata(self.lock)['id'],449471487)
        for index in range(3):
            altered=copy.deepcopy(metadata)
            if index==0:altered[0]['id']=449471487
            elif index==1:altered[1]['assets'][-1]['id']+=1
            else:altered[2]['assets'][0]['digest']='sha256:'+'0'*64
            with patch.object(reuse,'api',side_effect=altered),self.assertRaises(AssertionError):reuse.verify_metadata(self.lock)
        for target,name in [('macos-x64','verification-macos-x64.json'),('macos-arm64','verification-macos-arm64.json'),('macos-x64','kaixin-bridge-20261117-k12-7-macos-x64.tar.gz')]:
            with patch.object(reuse,'api',return_value={'assets':[{'name':name}]}),patch.object(reuse,'gh',side_effect=AssertionError('no writes')),self.assertRaises(AssertionError):reuse.upload_new(self.lock['candidate_tag'],Path(name),target)

    def launcher_entries(self):
        good={'actual_download_install_backup_restart':'passed','check_again_current':True,'to_launcher':'20261118-updater-4','chat_preserved':True,'task_preserved':True,'saved_key_preserved':True}
        starts=['20261118-updater-4','a47b05f9136ca6fb72d2f1f8a04eeb425298f358','20261114-unified','a47b05f9136ca6fb72d2f1f8a04eeb425298f358']
        return [{**good,'from_launcher':start,'signed_launcher_restarted':index!=0,'old_pid':index*10+1,'restarted_pid':index*10+(1 if index==0 else 2)} for index,start in enumerate(starts)]

    def test_only_same_starting_launcher_current_entry_may_hot_update(self):
        entries=self.launcher_entries()
        self.assertIsNone(reuse.validate_intel7_launcher_transitions(*entries,self.lock))
        entries[0].update(signed_launcher_restarted=True,restarted_pid=2)
        self.assertIsNone(reuse.validate_intel7_launcher_transitions(*entries,self.lock))

    def test_migration_roles_cannot_claim_hot_update_or_swap_starting_launchers(self):
        for index in range(4):
            entries=self.launcher_entries();entries[index]['from_launcher']='20261118-updater-4' if index else '20261114-unified'
            with self.subTest(wrong_start=index),self.assertRaises(AssertionError):reuse.validate_intel7_launcher_transitions(*entries,self.lock)
        for index in [1,2,3]:
            for restarted in [False,True]:
                entries=self.launcher_entries();entries[index].update(signed_launcher_restarted=restarted,restarted_pid=entries[index]['old_pid'])
                with self.subTest(migration=index,restarted=restarted),self.assertRaises(AssertionError):reuse.validate_intel7_launcher_transitions(*entries,self.lock)
        entries=self.launcher_entries();entries[0]['restarted_pid']=2
        with self.assertRaises(AssertionError):reuse.validate_intel7_launcher_transitions(*entries,self.lock)
        entries=self.launcher_entries();entries[0]['old_pid']=entries[0]['restarted_pid']=0
        with self.assertRaises(AssertionError):reuse.validate_intel7_launcher_transitions(*entries,self.lock)

    def test_four_complete_entry_receipts_precede_any_picture_acceptance(self):
        for index in range(4):
            entries=self.launcher_entries();entries[index]['chat_preserved']=False
            with self.assertRaises(AssertionError):reuse.validate_native_proofs({},None,entries[0],entries[1],self.lock,entries[2],entries[3])
        for field,value in [('signed_launcher_restarted',True),('restarted_pid',2)]:
            entries=self.launcher_entries();entries[0][field]=value
            with self.assertRaises(AssertionError):reuse.validate_native_proofs({},None,entries[0],entries[1],self.lock,entries[2],entries[3])

    def test_routing_workflow_and_existing_full_path_are_preserved(self):
        self.assertEqual(reuse.lock_name('student-20261117-k12-7','macos-x64'),'intel-k12-7-reuse-lock.json')
        with self.assertRaises(AssertionError):reuse.lock_name('student-20261117-k12-7','windows-x64')
        source=(ROOT/'ci-mac-reuse.py').read_text();tree=ast.parse(source);calls={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertNotIn('prepare_candidate',calls);self.assertNotIn('prepare_bridge',calls);self.assertNotIn('--clobber',source);self.assertNotIn('signing-private',source)
        self.assertEqual(source.count('verify_update_entry(root,target,install,resources,home,evidence'),4)
        self.assertIn("if seven:assert counts==lock['launcher_tests']",source)
        workflow=(ROOT/'.github/workflows/k12-intel7-reverify.yml').read_text()
        self.assertIn('runs-on: macos-15-intel',workflow);self.assertNotIn('matrix:',workflow)
        self.assertIn('KX_REUSE_LOCK_SHA256',workflow);self.assertIn('--release-tag student-20261117-k12-7',workflow)
        self.assertIn('name: native (macos-x64, macos-15-intel)',workflow)
        self.assertIn('node ci-k12-session-diagnostics-selfcheck.cjs',workflow)
        self.assertEqual(workflow.count('          node '),10)
        self.assertNotIn('nsis',workflow);self.assertNotIn('build-runtime',workflow)


if __name__=='__main__':unittest.main()
