"""Boundary tests for exact completed Intel7 native evidence; no live native run."""
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import unittest
from unittest.mock import patch
import zipfile
import intel7_complete_evidence as complete


class CompleteEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=(Path(__file__).parent/'intel7-complete-record-fixtures.json').read_bytes()
        assert hashlib.sha256(raw).hexdigest()=='6e97aaeefa7067dadf3b338534aee1aec032a397f699afdf39a24b9cf3a6d29c'
        cls.original={name:text.encode() for name,text in json.loads(raw).items()}
        cls.lock=json.loads(cls.original['reuse-lock.json'])

    def setUp(self):
        self.files=copy.deepcopy(self.original)

    def mutate(self,name,change):
        value=json.loads(self.files[name]);change(value)
        self.files[name]=json.dumps(value).encode()

    def records(self):
        # Unit isolation only: public archive tests retain the exact 152-byte/SHA boundary.
        with patch.object(complete,'_validate_member_bytes'):
            return complete.validate_complete_records(self.lock,self.files)

    def test_all_real_records_and_hot_current_route(self):
        result=self.records()
        self.assertEqual(len(result['entries']),4)
        current=result['entries']['update_entry']
        self.assertIs(current['signed_launcher_restarted'],False)
        self.assertEqual(current['old_pid'],current['restarted_pid'])
        for name in ['oldest_launcher_entry','materials_launcher_entry','materials_oldest_launcher_entry']:
            entry=result['entries'][name]
            self.assertIs(entry['signed_launcher_restarted'],True)
            self.assertNotEqual(entry['old_pid'],entry['restarted_pid'])
        self.assertEqual(result['launcher_tests']['pass'],83)

    def test_original_source_lock_is_immutable(self):
        altered=copy.deepcopy(self.lock);altered['source_commit']='a'*40
        with self.assertRaisesRegex(AssertionError,'source lock changed'):
            complete.validate_source_lock(altered)
        with patch.object(complete.sys,'flags',type('Flags',(),{'optimize':1})()):
            with self.assertRaises(RuntimeError):complete.validate_source_lock(self.lock)

    def test_all_four_routes_and_preservation_required(self):
        for name in complete.ENTRY_FILES.values():
            with self.subTest(name=name):
                self.files=copy.deepcopy(self.original);self.files.pop(name)
                with self.assertRaises(KeyError):self.records()
        for field in ['chat_preserved','task_preserved','saved_key_preserved']:
            with self.subTest(field=field):
                self.files=copy.deepcopy(self.original)
                self.mutate('update-entry.json',lambda v:v.update({field:False}))
                with self.assertRaises(AssertionError):self.records()

    def test_exact_launcher_roles_and_download_routes(self):
        cases=[('update-entry.json',{'from_launcher':'20261114-unified'}),
               ('oldest-update-entry.json',{'signed_launcher_restarted':False}),
               ('materials-update-entry.json',{'restarted_pid':66503}),
               ('materials-oldest-update-entry.json',{'selected_archive':'wrong.zip'}),
               ('update-entry.json',{'to_runtime':'old-runtime'})]
        for name,delta in cases:
            with self.subTest(name=name,delta=delta):
                self.files=copy.deepcopy(self.original);self.mutate(name,lambda v:v.update(delta))
                with self.assertRaises(AssertionError):self.records()

    def test_every_viewport_and_original_picture_required(self):
        self.mutate('picture-fresh-ui.json',lambda v:v['k12_library']['views'].pop())
        with self.assertRaises(AssertionError):self.records()
        self.files=copy.deepcopy(self.original)
        self.mutate('picture-fresh-ui.json',lambda v:v['k12_library']['views'][0].update({'allOriginalImagesLoaded':False}))
        with self.assertRaises(AssertionError):self.records()
        self.files=copy.deepcopy(self.original)
        sidecar=next(name for name in self.files if name.startswith('k12-library-fresh-'))
        self.mutate(sidecar,lambda v:v.update({'passed':False}))
        with self.assertRaises(AssertionError):self.records()

    def test_counts_downloads_network_immutable_and_math_cannot_degrade(self):
        cases=[('launcher-tests.json',lambda v:v.update({'tests':82,'pass':82})),
               ('downloads.json',lambda v:v[0].update({'anonymous_download':False})),
               ('immutable-assets-before.json',lambda v:v.pop()),
               ('network.json',lambda v:v.update({'signature_verified':False})),
               ('app.json',lambda v:v.update({'core_commit':'a'*40})),
               ('update-entry.json.math-before.json',lambda v:v.update({'accepted':1}))]
        for name,change in cases:
            with self.subTest(name=name):
                self.files=copy.deepcopy(self.original);self.mutate(name,change)
                with self.assertRaises(AssertionError):self.records()

    def test_all_152_members_and_original_byte_hashes_required(self):
        with self.assertRaisesRegex(AssertionError,'152 exact members'):
            complete._validate_member_bytes(self.files)
        expected=complete._member_manifest()
        fake={name:self.original.get(name,b'x') for name in expected}
        fake['app.json']+=b' '
        with self.assertRaisesRegex(AssertionError,'Source member changed: app.json'):
            complete._validate_member_bytes(fake)
        fake['unexpected']=b'x'
        with self.assertRaisesRegex(AssertionError,'152 exact members'):
            complete._validate_member_bytes(fake)
        with self.assertRaisesRegex(AssertionError,'exact complete native source ZIP'):
            complete.validate_complete_archive(self.lock,b'not the pinned archive')

    def archive(self,first=None,duplicate=False,symlink=False,large=False):
        buffer=io.BytesIO();names=list(complete._member_manifest())
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for index,name in enumerate(names):
                if index==0 and first:name=first
                if duplicate and index==1:name=names[0]
                info=zipfile.ZipInfo(name);info.compress_type=zipfile.ZIP_DEFLATED
                if index==0 and symlink:info.external_attr=(stat.S_IFLNK|0o777)<<16
                archive.writestr(info,b'x'*(16*1024**2 if index==0 and large else 1))
        return buffer.getvalue()

    def test_zip_paths_links_duplicates_sizes_and_crc(self):
        self.assertEqual(len(complete._extract_archive(self.archive())),152)
        for options in [{'first':'../escape'},{'first':'bad\\path'},{'symlink':True},{'duplicate':True},{'large':True}]:
            with self.subTest(options=options):
                with self.assertRaises(AssertionError):complete._extract_archive(self.archive(**options))
        with self.assertRaises(AssertionError):complete._extract_archive(b'bad zip')

    def api(self,path):
        source=complete.COMPLETE_SOURCE
        if path.startswith('actions/artifacts/'):
            return {'id':source['id'],'size_in_bytes':source['bytes'],'digest':'sha256:'+source['sha256'],'expired':False}
        if path.endswith('/jobs'):return {'jobs':[{'id':source['job_id'],'conclusion':'failure'}]}
        return {'status':'completed','conclusion':'failure','head_sha':source['workflow_commit']}

    def test_fetch_pins_real_failed_execution_and_artifact(self):
        with patch.object(complete,'validate_complete_archive',return_value={'checked':True}) as verify:
            gh=lambda *args:b'archive'
            self.assertEqual(complete.fetch_complete_archive(self.lock,self.api,gh),{'checked':True})
            verify.assert_called_once_with(self.lock,b'archive')
        for suffix,delta in [('artifact',{'expired':True}),('artifact',{'digest':'sha256:'+'0'*64}),('run',{'head_sha':'0'*40}),('jobs',{'jobs':[]})]:
            def bad_api(path):
                value=self.api(path)
                match=('/artifacts/' in path if suffix=='artifact' else path.endswith('/jobs') if suffix=='jobs' else '/runs/' in path and not path.endswith('/jobs'))
                if match:value.update(delta)
                return value
            with self.subTest(suffix=suffix,delta=delta):
                with patch.object(complete,'validate_complete_archive') as verify:
                    with self.assertRaises(AssertionError):complete.fetch_complete_archive(self.lock,bad_api,lambda *args:self.fail('must not download'))
                    verify.assert_not_called()

    def provenance(self):
        source=complete.COMPLETE_SOURCE
        p={'complete_native_execution':copy.deepcopy(source),'source_native_run':source['run_id'],'source_native_job':source['job_id'],'source_native_workflow_commit':source['workflow_commit'],
           'postcheck_run':44260000000,'verification_run':44260000000,'postcheck_workflow_commit':'a'*40,'workflow_commit':'a'*40}
        p.update({name:False for name in (*complete.RERUN_FLAGS,'bridge_rebuilt','installers_repackaged','existing_assets_overwritten')})
        p.update({name:True for name in ['complete_native_records_reverified','production_launcher_byte_identical','existing_asset_metadata_before_after_unchanged','final_postchecks_completed']})
        return p,{'complete_native_execution':copy.deepcopy(source)}

    def test_provenance_separates_source_execution_from_new_postchecks(self):
        p,lock=self.provenance()
        self.assertIs(complete.validate_finalized_provenance(self.lock,p,lock),True)
        deltas=[{'source_native_run':1},{'source_native_job':1},{'source_native_workflow_commit':'0'*40},
                {'postcheck_run':complete.COMPLETE_SOURCE['run_id']},{'postcheck_workflow_commit':complete.COMPLETE_SOURCE['workflow_commit']},
                {'verification_run':123},{'workflow_commit':'0'*40}]
        for delta in deltas:
            with self.subTest(delta=delta):
                p,lock=self.provenance();p.update(delta)
                with self.assertRaises(AssertionError):complete.validate_finalized_provenance(self.lock,p,lock)

    def test_provenance_cannot_claim_reruns_or_skip_final_checks(self):
        for name in (*complete.RERUN_FLAGS,'bridge_rebuilt','installers_repackaged','existing_assets_overwritten'):
            with self.subTest(name=name):
                p,lock=self.provenance();p[name]=True
                with self.assertRaises(AssertionError):complete.validate_finalized_provenance(self.lock,p,lock)
        for name in ['complete_native_records_reverified','production_launcher_byte_identical','existing_asset_metadata_before_after_unchanged','final_postchecks_completed']:
            with self.subTest(name=name):
                p,lock=self.provenance();p[name]=False
                with self.assertRaises(AssertionError):complete.validate_finalized_provenance(self.lock,p,lock)
        p,lock=self.provenance();p['complete_native_execution']['id']=1;lock['complete_native_execution']['id']=1
        with self.assertRaises(AssertionError):complete.validate_finalized_provenance(self.lock,p,lock)


if __name__=='__main__':unittest.main()
