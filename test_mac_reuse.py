import ast
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('mac_reuse', ROOT/'ci-mac-reuse.py')
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)


class MacReuseContract:
    def setUp(self):
        self.lock=json.loads((ROOT/reuse.TARGETS[self.target]['lock']).read_text())
        self.raw=(ROOT/'attachment-final-manifests.json').read_bytes()

    def test_exact_lock_without_network_or_execution(self):
        with patch.object(reuse,'api',side_effect=AssertionError('no network')),patch.object(reuse,'run',side_effect=AssertionError('no execution')):
            self.assertEqual(len(reuse.validate_lock(self.lock,self.raw)['manifests']),39)

    def test_wrong_frozen_asset_or_full_prior_is_rejected(self):
        changes=[lambda d:d['candidate_files'][0].update(url='https://example.com/file'),lambda d:d['prior_manifest'].pop('baseRuntimeId'),lambda d:d['bridge'].update(sha256='0'*64),lambda d:d['signed_runtime_assets'].pop(),lambda d:d['immutable_existing_assets'].pop(0)]
        for change in changes:
            changed=copy.deepcopy(self.lock);change(changed)
            with self.subTest(change=change),self.assertRaises((AssertionError,KeyError)):reuse.validate_lock(changed,self.raw)
        with self.assertRaises(AssertionError):reuse.validate_lock(self.lock,self.raw+b' ')

    def fake_metadata(self):
        release={'id':447749595,'prerelease':True,'draft':False,'assets':[dict(name=r['name'],id=r['id'],size=r['bytes'],digest='sha256:'+r['sha256']) for r in self.lock['immutable_existing_assets']]}
        stable={'assets':[dict(name=n,digest='sha256:'+s) for n,s in self.lock['baseline_feeds'].items()]}
        return [{'id':447366728},release,stable]

    def test_all_existing_metadata_checked_without_writes(self):
        with patch.object(reuse,'api',side_effect=self.fake_metadata()),patch.object(reuse,'gh',side_effect=AssertionError('no write')):
            self.assertEqual(reuse.verify_metadata(self.lock)['id'],447749595)
        changed=self.fake_metadata();changed[1]['assets'][-1]['id']+=1
        with patch.object(reuse,'api',side_effect=changed),patch.object(reuse,'gh',side_effect=AssertionError('no write')):
            with self.assertRaises(AssertionError):reuse.verify_metadata(self.lock)

    def test_existing_or_unapproved_uploads_are_never_overwritten(self):
        for name in ['attachment-final-manifests.json','verification-'+self.target+'.json','verification-'+('macos-x64' if self.target=='macos-arm64' else 'macos-arm64')+'.json','mac-reverify-run-windows-x64-123.json']:
            with self.subTest(name=name),patch.object(reuse,'api',return_value={'assets':[{'name':name}]}),patch.object(reuse,'gh',side_effect=AssertionError('no write')):
                with self.assertRaises(AssertionError):reuse.upload_new(self.lock['candidate_tag'],Path(name),self.target)

    def test_unsafe_redirect_or_oversize_leaves_no_partial(self):
        class Response(io.BytesIO):
            def __init__(self,url,data):super().__init__(data);self.url=url
            def geturl(self):return self.url
        for url,data in [('http://github.com/file',b'abc'),('https://github.com/file',b'abcd')]:
            with tempfile.TemporaryDirectory() as directory,patch.object(reuse,'urlopen',side_effect=lambda *_a,**_k:Response(url,data)):
                with self.assertRaises(RuntimeError):reuse.download(dict(name='frozen.bin',url='https://github.com/file',id=1,bytes=3,sha256='0'*64),Path(directory))
                self.assertEqual(list(Path(directory).iterdir()),[])

    def test_fresh_current_oldest_picture_proof_all_required(self):
        api={'passed':True,'model_calls':0,'prepared_picture_bindings':294,'prepared_picture_manifest_sha256':self.lock['picture_manifest_sha256'],'runtime_isolated_count':17,'runtime_exclusion_kinds':self.lock['runtime_exclusion_kinds'],'runtime_exclusion_ledger_sha256':self.lock['runtime_exclusion_ledger_sha256'],'bank_revision':self.lock['bank_revision']}
        ui={'passed':True,'actualNativeRenderer':True,'bank_revision':self.lock['bank_revision'],'views':[{'preparedPicture':{key:True for key in ['native_http_image_sha_verified','body_dom_before_image_response','second_history_restore']}} for _ in range(4)]}
        fresh={'passed':True,'production_launcher_source_byte_identical':True,'qa_code_only_in_disposable_copy':True,'k12_library':ui}
        reuse.validate_native_proofs({'k12_api':api},fresh,{'k12_library':ui},{'k12_library':ui},self.lock)
        bad=copy.deepcopy(fresh);bad['k12_library']['views'][1]['preparedPicture']['body_dom_before_image_response']=False
        with self.assertRaises(AssertionError):reuse.validate_native_proofs({'k12_api':api},bad,{'k12_library':ui},{'k12_library':ui},self.lock)

    def test_no_distribution_rebuild_or_resign(self):
        source=(ROOT/'ci-mac-reuse.py').read_text();tree=ast.parse(source)
        calls={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertNotIn('prepare_candidate',calls);self.assertNotIn('prepare_bridge',calls);self.assertNotIn('--clobber',source)
        self.assertIn('verify_picture_fresh(root,target,install,resources,home,evidence)',source)
        self.assertEqual(source.count('verify_update_entry(root,target,install,resources,home,evidence'),2)
        self.assertNotIn('signing-private',source)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),'15d74b06b44ed8afa233d39a290d2ef94806f87e23ce0370c791860636978ab1')


class ArmReuseTest(MacReuseContract,unittest.TestCase):
    target='macos-arm64'


class IntelReuseTest(MacReuseContract,unittest.TestCase):
    target='macos-x64'


if __name__=='__main__':unittest.main()
