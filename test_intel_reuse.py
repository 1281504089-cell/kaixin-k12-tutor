import ast
import copy
import importlib.util
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('intel_reuse', ROOT/'ci-intel-reuse.py')
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)

class IntelReuseTest(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads((ROOT/'intel-reuse-lock.json').read_text())
        self.raw = (ROOT/'attachment-final-manifests.json').read_bytes()

    def test_frozen_lock_validates_without_network_or_execution(self):
        with patch.object(reuse,'api',side_effect=AssertionError('network forbidden')), patch.object(reuse,'run',side_effect=AssertionError('execution forbidden')):
            self.assertEqual(len(reuse.validate_lock(self.lock,self.raw)['manifests']),36)

    def test_changed_stage_or_candidate_path_is_rejected(self):
        with self.assertRaises(AssertionError):reuse.validate_lock(self.lock,self.raw+b' ')
        changed=copy.deepcopy(self.lock);changed['candidate_files'][0]['url']='https://example.com/installer'
        with self.assertRaises(AssertionError):reuse.validate_lock(changed,self.raw)

    def test_wrong_prior_and_core_binding_are_rejected(self):
        changed=copy.deepcopy(self.lock);changed['prior_manifest']['sha256']='0'*64
        with self.assertRaises(AssertionError):reuse.validate_lock(changed,self.raw)
        changed=copy.deepcopy(self.lock);changed['included_manifest']['sha256']='0'*64
        with self.assertRaises(AssertionError):reuse.validate_lock(changed,self.raw)

    def test_actual_asset_mismatch_stops_before_writes(self):
        expected=[*self.lock['candidate_files'],self.lock['core_asset'],dict(name=self.lock['bridge']['name'],id=self.lock['bridge']['asset_id'],bytes=self.lock['bridge']['bytes'],sha256=self.lock['bridge']['sha256']),*self.lock['signed_runtime_assets']]
        assets=[dict(name=r['name'],id=r['id'],size=r['bytes'],digest='sha256:'+r['sha256']) for r in expected]
        assets[0]['digest']='sha256:'+'0'*64
        release=dict(id=self.lock['candidate_release_id'],prerelease=True,draft=False,assets=assets)
        with patch.object(reuse,'api',side_effect=[{'id':self.lock['baseline_latest_id']},release]),patch.object(reuse,'gh',side_effect=AssertionError('write forbidden')):
            with self.assertRaises(AssertionError):reuse.verify_metadata(self.lock)

    def test_frozen_metadata_and_baseline_feeds_are_checked_without_writes(self):
        rows=[*self.lock['candidate_files'],self.lock['core_asset'],dict(name=self.lock['bridge']['name'],id=self.lock['bridge']['asset_id'],bytes=self.lock['bridge']['bytes'],sha256=self.lock['bridge']['sha256']),*self.lock['signed_runtime_assets']]
        release=dict(id=self.lock['candidate_release_id'],prerelease=True,draft=False,assets=[dict(name=r['name'],id=r['id'],size=r['bytes'],digest='sha256:'+r['sha256']) for r in rows])
        stable={'assets':[dict(name=name,digest='sha256:'+digest) for name,digest in self.lock['baseline_feeds'].items()]}
        with patch.object(reuse,'api',side_effect=[{'id':self.lock['baseline_latest_id']},release,stable]),patch.object(reuse,'gh',side_effect=AssertionError('write forbidden')):
            self.assertEqual(reuse.verify_metadata(self.lock)['id'],447366728)

    def test_no_packaging_bridge_rebuild_or_existing_upload_overwrite(self):
        source=(ROOT/'ci-intel-reuse.py').read_text();tree=ast.parse(source)
        calls={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertNotIn('prepare_candidate',calls);self.assertNotIn('prepare_bridge',calls)
        self.assertNotIn('--clobber',source)
        self.assertIn("'ci-fresh-smoke.mjs'",source)
        self.assertIn('legacy=True',source)
        self.assertEqual(source.count('verify_update_entry(root,TARGET,install,resources,home,evidence'),2)
        with patch.object(reuse,'api',return_value={'assets':[{'name':'already.json'}]}),patch.object(reuse,'gh',side_effect=AssertionError('write forbidden')):
            with self.assertRaises(AssertionError):reuse.upload_new('student-20261117-k12-1',Path('already.json'))

    def test_next_bridge_names_use_the_actual_batch_tag(self):
        from ci_attachment_bridge import bridge_identity
        self.assertEqual(bridge_identity('student-20261117-k12-1','macos-x64'),('kaixin-bridge-20261117-k12-1-macos-x64.tar.gz','1.7.1-kaixin-20261117-k12-1-macos-x64-universal'))
        self.assertNotEqual(bridge_identity('student-20261115-preview3','macos-x64'),bridge_identity('student-20261117-k12-1','macos-x64'))

    def test_insecure_redirect_and_oversized_stream_leave_no_partial(self):
        class Response(io.BytesIO):
            def __init__(self,url,data):super().__init__(data);self.url=url
            def geturl(self):return self.url
        for url,data in [('http://github.com/frozen',b'abc'),('https://github.com/frozen',b'abcd')]:
            with self.subTest(url=url),tempfile.TemporaryDirectory() as directory:
                row=dict(name='frozen.bin',url='https://github.com/frozen',id=1,bytes=3,sha256='0'*64)
                with patch.object(reuse,'urlopen',side_effect=lambda *_args,**_kwargs:Response(url,data)):
                    with self.assertRaises(RuntimeError):reuse.download(row,Path(directory))
                self.assertEqual(list(Path(directory).iterdir()),[])

if __name__=='__main__':unittest.main()
