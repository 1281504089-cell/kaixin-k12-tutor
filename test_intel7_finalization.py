"""Pure controls for supplementary Intel7 postflight; no downloads or native scenarios."""
import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('intel7_finalization', ROOT/'ci-finalize-intel7.py')
finalize = importlib.util.module_from_spec(spec); spec.loader.exec_module(finalize)


class IntelSevenFinalizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads((ROOT/finalize.SOURCE_LOCK).read_bytes())
        cls.inputs = {name:finalize.sha(ROOT/name) for name in set(cls.original['recipe_inputs_sha256']) | finalize.NEW_INPUTS}
        cls.final = dict(schema_version=1, frozen=True, target='macos-x64', candidate_tag=cls.original['candidate_tag'],
                         source_commit=cls.original['source_commit'], launcher_build=cls.original['launcher_build'],
                         source_lock_file=finalize.SOURCE_LOCK, source_lock_sha256=finalize.SOURCE_LOCK_SHA,
                         complete_native_execution=finalize.COMPLETE_SOURCE, frozen_stage=cls.original['frozen_stage'],
                         allowed_source_input_changes=finalize.ALLOWED_CHANGES,
                         postflight_inputs_sha256=cls.inputs, workflow_branch_prefix=finalize.BRANCH_PREFIX)
        cls.records = json.loads((ROOT/'intel7-complete-record-fixtures.json').read_bytes())

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in set(self.inputs) | {finalize.SOURCE_LOCK}:
            destination = self.root/name; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, destination)
        self.final = copy.deepcopy(type(self).final)
        self.env = dict(GITHUB_RUN_ID='44260000001', GITHUB_SHA='a'*40,
                        GITHUB_REF_NAME=finalize.BRANCH_PREFIX+'unit-test')
        self.freeze()

    def freeze(self):
        raw = json.dumps(self.final).encode()
        (self.root/finalize.FINALIZATION_LOCK).write_bytes(raw)
        self.env['KX_FINALIZATION_LOCK_SHA256'] = hashlib.sha256(raw).hexdigest()

    def reject(self, change):
        saved = copy.deepcopy(self.final)
        change(self.final); self.freeze()
        with self.assertRaises((AssertionError, KeyError, TypeError, ValueError)):
            finalize.preflight(self.root, self.env, native=False)
        self.final = saved; self.freeze()

    def test_exact_current_inputs_pass_without_network_or_writes(self):
        before = {str(p.relative_to(self.root)):finalize.sha(p) for p in self.root.rglob('*') if p.is_file()}
        with patch.object(finalize, 'load_module', side_effect=AssertionError('no imports before lock')):
            source, lock, batch = finalize.preflight(self.root, self.env, native=False)
        self.assertEqual(source, self.original); self.assertEqual(lock, self.final); self.assertEqual(len(batch['shell_files']), 24)
        self.assertEqual(before, {str(p.relative_to(self.root)):finalize.sha(p) for p in self.root.rglob('*') if p.is_file()})

    def test_pending_or_substituted_identity_is_rejected(self):
        for name, value in [('frozen',False), ('target','macos-arm64'), ('candidate_tag','student-20261117-k12-6'),
                            ('source_commit','0'*40), ('launcher_build','20261118-updater-3'),
                            ('source_lock_file','intel-k12-5-reuse-lock.json'), ('source_lock_sha256','0'*64),
                            ('workflow_branch_prefix','codex/other-')]:
            with self.subTest(name=name): self.reject(lambda d:d.update({name:value}))
        for field, value in [('id',1), ('bytes',1), ('sha256','0'*64), ('run_id',44230306905),
                             ('workflow_commit','0'*40), ('job_id',1), ('source_lock_sha256','0'*64)]:
            with self.subTest(field=field): self.reject(lambda d:d['complete_native_execution'].update({field:value}))
        self.reject(lambda d:d['frozen_stage'].update(sha256='0'*64))

    def test_exact_raw_locks_and_all_original_plus_new_inputs_are_required(self):
        with self.assertRaises(AssertionError): finalize.preflight(self.root, {**self.env,'KX_FINALIZATION_LOCK_SHA256':'ROOT_WILL_FREEZE'}, native=False)
        path = self.root/finalize.SOURCE_LOCK; path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(AssertionError,'Original source lock bytes'): finalize.preflight(self.root,self.env,native=False)
        shutil.copyfile(ROOT/finalize.SOURCE_LOCK,path)
        for name in ['ci-update-flow.cjs', *sorted(finalize.NEW_INPUTS)]:
            with self.subTest(name=name): self.reject(lambda d:d['postflight_inputs_sha256'].pop(name))
        for name in ['ci-update-flow.cjs', 'ci-mac-reuse.py', 'intel7_complete_evidence.py']:
            path = self.root/name; original = path.read_bytes(); path.write_bytes(original+b'\n')
            with self.subTest(changed=name), self.assertRaises(AssertionError): finalize.preflight(self.root,self.env,native=False)
            path.write_bytes(original)

    def test_only_exact_three_reviewed_source_input_changes_are_allowed(self):
        self.assertEqual(finalize.ALLOWED_CHANGES, ['ci-mac-reuse.py','test_intel7_reuse.py','ci-promote-attachments.py'])
        self.reject(lambda d:d['allowed_source_input_changes'].append('ci-update-flow.cjs'))
        path = self.root/'ci-update-flow.cjs'; path.write_bytes(path.read_bytes()+b'\n')
        self.reject(lambda d:d['postflight_inputs_sha256'].update({'ci-update-flow.cjs':finalize.sha(path)}))

    def test_unsafe_input_paths_and_hash_cycles_are_rejected(self):
        for name in ['../escape','/tmp/escape','x\\escape',finalize.FINALIZATION_LOCK,finalize.SOURCE_LOCK,'.github/workflows/test.yml']:
            with self.subTest(name=name): self.reject(lambda d:d['postflight_inputs_sha256'].update({name:'a'*64}))
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside)/'file'; target.write_text('outside')
            (self.root/'escape').symlink_to(target)
            self.reject(lambda d:d['postflight_inputs_sha256'].update({'escape':finalize.sha(target)}))

    def test_new_native_run_branch_and_empty_disposable_paths_are_required(self):
        for key,value in [('GITHUB_RUN_ID',str(finalize.COMPLETE_SOURCE['run_id'])),('GITHUB_RUN_ID','44230306905'),
                          ('GITHUB_RUN_ID','0'),('GITHUB_SHA',finalize.COMPLETE_SOURCE['workflow_commit']),
                          ('GITHUB_SHA','0738e1ac8cfbfddb9123d097bc90598abf5827fb'),('GITHUB_SHA','short'),
                          ('GITHUB_REF_NAME','codex/k12-intel7-reverify-20261118-old'),('GITHUB_REF_NAME',finalize.BRANCH_PREFIX)]:
            with self.subTest(key=key,value=value), self.assertRaises(AssertionError): finalize.preflight(self.root,{**self.env,key:value},native=False)
        with patch.object(finalize.sys,'platform','darwin'),patch.object(finalize.platform,'machine',return_value='arm64'),self.assertRaisesRegex(AssertionError,'Actual Intel'): finalize.preflight(self.root,self.env)
        for name in [finalize.WORK,finalize.EVIDENCE,'macos-x64-reuse-work','prior-update','materials-baseline','student-source','launcher-tests-macos-x64']:
            path=self.root/name;path.mkdir(parents=True)
            with self.subTest(path=name),self.assertRaises(AssertionError):finalize.preflight(self.root,self.env,native=False)
            path.rmdir()

    def test_optimized_execution_is_rejected_before_any_lock_read(self):
        code="import importlib.util;from pathlib import Path;s=importlib.util.spec_from_file_location('f',Path('ci-finalize-intel7.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.preflight(Path('.'),{},native=False)"
        result=subprocess.run([sys.executable,'-B','-O','-c',code],cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('assertions must remain enabled',result.stderr)

    def mock_execution(self):
        files={name:raw.encode() for name,raw in self.records.items()}
        entry_files={'update_entry':'update-entry.json','oldest_launcher_entry':'oldest-update-entry.json',
                     'materials_launcher_entry':'materials-update-entry.json','materials_oldest_launcher_entry':'materials-oldest-update-entry.json'}
        proof=dict(files=files,entries={name:json.loads(files[file]) for name,file in entry_files.items()},
                   smoke=json.loads(files['app.json']),fresh_picture_ui=json.loads(files['picture-fresh-ui.json']),
                   network=json.loads(files['network.json']),launcher_tests=json.loads(files['launcher-tests.json']),download_files=json.loads(files['downloads.json']))
        reuse=MagicMock();complete=MagicMock();complete.fetch_complete_archive.return_value=proof
        assets=[dict(name=r['name'],id=r['id'],size=r['bytes'],digest='sha256:'+r['sha256']) for r in self.original['immutable_existing_assets']]
        release=dict(id=self.original['candidate_release_id'],assets=assets)
        reuse.verify_metadata.return_value=release
        reuse.download.side_effect=lambda row,directory:{**row,'anonymous_download':True,'sha256_verified':True}
        batch=json.loads((ROOT/'attachment-batch.json').read_bytes())
        batch['shell_files']={f'src/test-{index}.mjs':{'sha256':hashlib.sha256(str(index).encode()).hexdigest()} for index in range(24)}
        def installed(work,downloads,module):
            app=work/'installed/开心动力超级学霸.app'
            for index,name in enumerate(batch['shell_files']):
                path=app/'Contents/Resources/app'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(str(index))
            return app
        return proof,reuse,complete,batch,installed

    def execute_mock(self, failure=None):
        proof,reuse,complete,batch,installed=self.mock_execution()
        if failure:failure(proof,reuse,complete)
        with patch.object(finalize,'preflight',return_value=(self.original,self.final,batch)), \
             patch.object(finalize,'load_module',side_effect=[reuse,complete]), \
             patch.object(finalize,'install_intel',side_effect=installed), \
             patch.object(finalize,'verify_installed',return_value=None):
            with contextlib.redirect_stdout(io.StringIO()):
                report=finalize.finalize(self.root,self.env)
        return report,proof,reuse,complete

    def test_complete_source_failure_precedes_downloads_uploads_and_writes(self):
        proof,reuse,complete,batch,installed=self.mock_execution()
        complete.fetch_complete_archive.side_effect=AssertionError('wrong original archive')
        with patch.object(finalize,'preflight',return_value=(self.original,self.final,batch)),patch.object(finalize,'load_module',side_effect=[reuse,complete]),self.assertRaisesRegex(AssertionError,'wrong original archive'):
            finalize.finalize(self.root,self.env)
        for name in ['verify_metadata','download','upload_new','run']:getattr(reuse,name).assert_not_called()
        self.assertFalse((self.root/finalize.EVIDENCE).exists());self.assertFalse((self.root/finalize.WORK).exists())

    def test_postflight_preserves_original_members_and_never_claims_reruns(self):
        report,proof,reuse,complete=self.execute_mock()
        evidence=self.root/finalize.EVIDENCE
        for name,raw in proof['files'].items():self.assertEqual((evidence/name).read_bytes(),raw)
        self.assertEqual(json.loads((evidence/'downloads.json').read_bytes()),proof['download_files'])
        self.assertEqual(len(json.loads((evidence/'postflight-downloads.json').read_bytes())),5)
        self.assertEqual(reuse.download.call_count,50);self.assertEqual(reuse.validate_native_proofs.call_count,2)
        self.assertEqual([call.args[1].name for call in reuse.upload_new.call_args_list],[f'native-reverify-run-macos-x64-{self.env["GITHUB_RUN_ID"]}.json','verification-macos-x64.json'])
        for name in ['fresh_smoke_rerun','proxy_smoke_rerun','oldest_and_current_ipc_rerun','fresh_picture_ui_rerun','materials_both_variants_rerun','bridge_rebuilt','installers_repackaged','existing_assets_overwritten']:
            self.assertIs(report['provenance'][name],False)
        self.assertEqual(report['provenance']['source_native_run'],44248561243)
        self.assertEqual(report['provenance']['source_native_job'],134613361890)
        self.assertEqual(report['provenance']['source_native_workflow_commit'],'7a7c7e0d26f1796f35f606afe42eaa8c31599db6')
        self.assertEqual(report['provenance']['original_failed_run'],44230306905)
        self.assertEqual(report['provenance']['original_failed_job'],134553415977)
        self.assertEqual(report['provenance']['original_stage_run'],44230306905)
        self.assertEqual(report['provenance']['original_stage_workflow_commit'],'0738e1ac8cfbfddb9123d097bc90598abf5827fb')
        self.assertEqual(report['provenance']['postcheck_run'],int(self.env['GITHUB_RUN_ID']))
        self.assertTrue(report['native_postflight']['production_codesign_deep_strict_passed'])
        self.assertEqual(report['native_postflight']['production_launcher_files_verified'],24)
        self.assertEqual(sum(not r['within_original_5s'] for r in report['pre_update_read_only_math_preparation']),2)
        self.assertIs(report['model_answer_speed_tested'],False)
        self.assertFalse((evidence/'completed-source-reuse-lock.json').exists())
        tree=ast.parse((ROOT/'ci-promote-attachments.py').read_text())
        checks=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'verify_complete_native_source','verify_native_entry_artifacts'}]
        self.assertEqual(len(checks),2)
        namespace={'json':json};exec(compile(ast.Module(body=checks,type_ignores=[]),'publisher-pure-guards','exec'),namespace)
        namespace['verify_complete_native_source'](report,proof,finalize.COMPLETE_SOURCE,self.original['frozen_stage']['sha256'])
        self.assertEqual(namespace['verify_native_entry_artifacts'](report,evidence)['per_entry_receipts_verified'],4)

    def test_failed_codesign_cannot_publish_final_verification(self):
        proof,reuse,complete,batch,installed=self.mock_execution()
        reuse.run.side_effect=subprocess.CalledProcessError(1,['codesign'])
        with patch.object(finalize,'preflight',return_value=(self.original,self.final,batch)),patch.object(finalize,'load_module',side_effect=[reuse,complete]),patch.object(finalize,'install_intel',side_effect=installed),patch.object(finalize,'verify_installed',return_value=None),self.assertRaises(subprocess.CalledProcessError):
            finalize.finalize(self.root,self.env)
        self.assertEqual(reuse.upload_new.call_count,1)
        for name in ['verified.json','verification-macos-x64.json','postflight-checks.json','immutable-assets-after.json']:self.assertFalse((self.root/finalize.EVIDENCE/name).exists())

    def test_installed_core_base_source_and_signature_failures_remain_fatal(self):
        app=self.root/'fixture.app';resources=app/'Contents/Resources'
        for name in ['update','seed','app/src']:(resources/name).mkdir(parents=True)
        included=dict(archive='core.tar.gz',baseRuntimeId='frozen-base')
        (resources/'update/runtime.json').write_text(json.dumps(included))
        (resources/'seed/runtime.json').write_text(json.dumps({'runtimeId':'frozen-base'}))
        core=resources/'update/core.tar.gz';core.write_bytes(b'frozen-core')
        shell=resources/'app/src/main.mjs';shell.write_bytes(b'frozen-launcher')
        lock=dict(included_manifest=included,core_asset=dict(bytes=core.stat().st_size,sha256=finalize.sha(core)))
        batch=dict(shell_files={'src/main.mjs':{'sha256':finalize.sha(shell)}});reuse=MagicMock()
        self.assertEqual(finalize.verify_installed(self.root,app,lock,batch,self.root,reuse),resources)
        reuse.verify_signatures.assert_called_once()
        for file,changed in [(core,b'wrong-core'),(shell,b'wrong-launcher'),(resources/'seed/runtime.json',b'{"runtimeId":"wrong"}'),(resources/'update/runtime.json',b'{}')]:
            raw=file.read_bytes();file.write_bytes(changed)
            with self.subTest(file=file.name),self.assertRaises(AssertionError):finalize.verify_installed(self.root,app,lock,batch,self.root,reuse)
            file.write_bytes(raw)
        extra=resources/'app/src/extra.mjs';extra.write_bytes(b'extra')
        with self.assertRaisesRegex(AssertionError,'Unexpected launcher'):finalize.verify_installed(self.root,app,lock,batch,self.root,reuse)
        extra.unlink();reuse.verify_signatures.side_effect=AssertionError('signature rejected')
        with self.assertRaisesRegex(AssertionError,'signature rejected'):finalize.verify_installed(self.root,app,lock,batch,self.root,reuse)

    def test_split_image_cleanup_and_install_errors_remain_fatal(self):
        work=self.root/'install-control';work.mkdir();downloads=work/'downloads';downloads.mkdir();(downloads/'frozen-part.dmg').write_bytes(b'fixture')
        reuse=MagicMock();reuse.run.side_effect=[None,None,subprocess.CalledProcessError(1,['ditto']),None]
        with self.assertRaises(subprocess.CalledProcessError):finalize.install_intel(work,downloads,reuse)
        self.assertEqual(reuse.run.call_args_list[-1].args[0][1],'detach')

    def test_workflow_and_script_do_not_repeat_or_repackage_native_scenarios(self):
        source=(ROOT/'ci-finalize-intel7.py').read_text();tree=ast.parse(source)
        calls={node.func.id if isinstance(node.func,ast.Name) else node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,(ast.Name,ast.Attribute))}
        self.assertFalse(calls & {'verify_update_entry','verify_picture_fresh','verify_proxy','prepare_bridge','prepare_candidate','validate_intel7_execution'})
        self.assertNotIn('--force',source);self.assertNotIn('--sign',source);self.assertNotIn('--clobber',source)
        workflow=(ROOT/'.github/workflows/k12-intel7-postflight.yml').read_text()
        self.assertIn('runs-on: macos-15-intel',workflow);self.assertIn('timeout-minutes: 60',workflow)
        self.assertRegex(workflow,r'KX_FINALIZATION_LOCK_SHA256: (ROOT_WILL_FREEZE|[a-f0-9]{64})\n')
        self.assertNotIn('matrix:',workflow);self.assertNotIn('ci-mac-reuse.py --target',workflow)
        self.assertNotIn('validate_intel7_execution',workflow)
        self.assertLess(workflow.index('--validate-only'),workflow.index('python -B -m unittest'))


if __name__=='__main__':unittest.main()
