"""Reject source, stage, signature or installer substitution in the Intel5-only retry."""
import copy,importlib.util,json,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('reuse5',ROOT/'ci-mac-reuse.py');reuse=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse)
class IntelFiveReuseTest(unittest.TestCase):
 def setUp(self):
  self.lock=json.loads((ROOT/'intel-k12-5-reuse-lock.json').read_text());self.raw=(ROOT/'frozen-k12-5-manifests.json').read_bytes()
 def test_exact_current_stage_without_network_or_execution(self):
  with patch.object(reuse,'api',side_effect=AssertionError('no network')),patch.object(reuse,'run',side_effect=AssertionError('no execution')):self.assertEqual(len(reuse.validate_lock(self.lock,self.raw)['manifests']),45)
 def test_wrong_source_stage_platform_or_signed_bytes_rejected(self):
  mutations=[lambda d:d.update(target='macos-arm64'),lambda d:d.update(source_commit='0'*40),lambda d:d.update(original_native_run=44124283096),lambda d:d.update(original_native_workflow_commit='0'*40),lambda d:d.update(original_failed_job=134183700623),lambda d:d.update(stage_delivery_commit='0'*40)]
  for mutate in mutations:
   d=copy.deepcopy(self.lock);mutate(d)
   with self.subTest(change=mutate),self.assertRaises(AssertionError):reuse.validate_lock(d,self.raw)
  with self.assertRaises(AssertionError):reuse.validate_lock(self.lock,self.raw+b'\n')
 def test_missing_fifth_segment_or_replaced_asset_rejected(self):
  for mutate in [lambda d:d['candidate_files'].pop(),lambda d:d['candidate_files'][0].update(sha256='0'*64),lambda d:d['candidate_files'][0].update(id=d['candidate_files'][1]['id']),lambda d:d['bridge'].update(bytes=1),lambda d:d['signed_runtime_assets'].pop()]:
   d=copy.deepcopy(self.lock);mutate(d)
   with self.subTest(change=mutate),self.assertRaises((AssertionError,KeyError)):reuse.validate_lock(d,self.raw)
 def test_missing_native_caller_hash_and_foreign_prior_rejected(self):
  for mutate in [lambda d:d['recipe_inputs_sha256'].pop('ci_picture_fresh.py'),lambda d:d['recipe_inputs_sha256'].update({'ci-mac-reuse.py':'bad'}),lambda d:d['prior_manifest_asset'].update(url='https://example.com/prior')]:
   d=copy.deepcopy(self.lock);mutate(d)
   with self.assertRaises(AssertionError):reuse.validate_lock(d,self.raw)
 def metadata(self):
  return [{'id':448283800},{'id':448792391,'prerelease':True,'draft':False,'assets':[dict(name=x['name'],id=x['id'],size=x['bytes'],digest='sha256:'+x['sha256']) for x in self.lock['immutable_existing_assets']]},{'assets':[dict(name=k,digest='sha256:'+v) for k,v in self.lock['baseline_feeds'].items()]}]
 def test_current_four_and_all_existing_five_metadata_must_stay_fixed(self):
  with patch.object(reuse,'api',side_effect=self.metadata()),patch.object(reuse,'gh',side_effect=AssertionError('no write')):self.assertEqual(reuse.verify_metadata(self.lock)['id'],448792391)
  for index in range(3):
   d=self.metadata()
   if index==0:d[0]['id']+=1
   elif index==1:d[1]['assets'][0]['id']+=1
   else:d[2]['assets'][0]['digest']='sha256:'+'0'*64
   with patch.object(reuse,'api',side_effect=d),self.assertRaises(AssertionError):reuse.verify_metadata(self.lock)
 def test_existing_evidence_cannot_be_overwritten_or_foreign_target_uploaded(self):
  with patch.object(reuse,'api',return_value={'assets':[{'name':'verification-macos-x64.json'}]}),patch.object(reuse,'gh',side_effect=AssertionError('no write')),self.assertRaises(AssertionError):reuse.upload_new(self.lock['candidate_tag'],Path('verification-macos-x64.json'),'macos-x64')
  with self.assertRaises(AssertionError):reuse.upload_new(self.lock['candidate_tag'],Path('verification-macos-arm64.json'),'macos-arm64')
if __name__=='__main__':unittest.main()
