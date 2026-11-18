import copy,json,tempfile,unittest
from pathlib import Path
import ci_native8_health_acceptance as gate
class ExactAcceptance(unittest.TestCase):
 def setUp(self):
  self.batch=json.loads(Path('attachment-batch.json').read_text());self.manifest=self.batch['manifests']['macos-arm64'];self.lock=json.loads(Path('fresh-install-lock-arm8-health.json').read_text());self.acceptance=Path('native8-arm-health-acceptance.json');self.artifact=Path('native8-arm-health-original.zip')
 def report(self,**kw):return gate.validate_original(kw.get('acceptance',self.acceptance),kw.get('artifact',self.artifact),kw.get('target','macos-arm64'),kw.get('batch',self.batch),kw.get('manifest',self.manifest))
 def test_exact_original_sample_explicitly_reused_not_relabelled(self):
  r=self.report();self.assertEqual(r['health_max_seconds'],5.248);self.assertFalse(r['explicit_health_acceptance']['original_health_gate_passed']);self.assertFalse(r['explicit_health_acceptance']['attachment_scenario_rerun_in_new_profile']);self.assertFalse(r['explicit_health_acceptance']['remaining_checks_completed_by_this_receipt']);self.assertTrue(r['scanned_pdf_retrievable'])
 def test_original_default_gate_file_kept(self):self.assertEqual(gate.sha('ci-attachment-native.py'),gate.ORIGINAL_TEST_SHA)
 def test_wrong_target_rejected(self):
  with self.assertRaises(AssertionError):self.report(target='macos-x64')
 def test_wrong_batch_rejected(self):
  b=copy.deepcopy(self.batch);b['tag']='student-20261117-k12-9'
  with self.assertRaises(AssertionError):self.report(batch=b)
 def test_changed_core_rejected(self):
  b=copy.deepcopy(self.batch);b['core_asset']['digest']='sha256:'+'0'*64
  with self.assertRaises(AssertionError):self.report(batch=b)
 def test_changed_manifest_rejected(self):
  m=copy.deepcopy(self.manifest);m['commit']='0'*40
  with self.assertRaises(AssertionError):self.report(manifest=m)
 def test_mutated_original_receipt_rejected(self):
  for mutate in [lambda x:x['reported_metrics'].update(health_max_seconds=5.249),lambda x:x.update(job_id=1),lambda x:x['reported_metrics'].update(raw_originals_verified=False),lambda x:x.update(remaining_native_checks_completed=True),lambda x:x['user_acceptance'].update(new_model_wait_limit=True)]:
   with self.subTest(mutate=mutate),tempfile.TemporaryDirectory() as d:
    x=json.loads(self.acceptance.read_text());mutate(x);f=Path(d)/'accepted.json';f.write_text(json.dumps(x))
    with self.assertRaises(AssertionError):self.report(acceptance=f)
 def test_modified_original_artifact_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'artifact.zip';f.write_bytes(self.artifact.read_bytes()+b'changed')
   with self.assertRaises(AssertionError):self.report(artifact=f)
 def test_embedded_exact_stamp_only(self):
  stamp=self.report()['explicit_health_acceptance'];gate.validate_embedded(stamp,'macos-arm64',self.batch)
  for key,value in [('original_health_max_seconds',5.249),('target','windows-x64'),('model_wait_exception',True),('original_health_gate_passed',True),('attachment_scenario_rerun_in_new_profile',True)]:
   s=copy.deepcopy(stamp);s[key]=value
   with self.subTest(key=key),self.assertRaises(AssertionError):gate.validate_embedded(s,'macos-arm64',self.batch)
 def release(self):
  return {'id':449810016,'tag_name':gate.TAG,'prerelease':True,'draft':False,'assets':[{'name':x['name'],'id':x['id'],'size':x['bytes'],'digest':'sha256:'+x['sha256']} for x in self.lock['reuse_existing_native']['original_installer_assets']['macos-arm64']]}
 def test_exact_four_installer_assets_reused(self):gate.validate_reuse(self.lock,self.batch,self.release(),'macos-arm64')
 def test_wrong_installer_id_or_digest_rejected(self):
  for field,value in [('id',1),('digest','sha256:'+'0'*64)]:
   r=self.release();r['assets'][0][field]=value
   with self.subTest(field=field),self.assertRaises(AssertionError):gate.validate_reuse(self.lock,self.batch,r,'macos-arm64')
 def test_existing_stage_never_overwritten(self):
  r=self.release();r['assets'].append({'name':'attachment-stage-macos-arm64.json'})
  with self.assertRaises(AssertionError):gate.validate_reuse(self.lock,self.batch,r,'macos-arm64')
 def test_unfrozen_or_other_target_rejected(self):
  lock=copy.deepcopy(self.lock);lock['execution_frozen']=False
  with self.assertRaises(AssertionError):gate.validate_reuse(lock,self.batch,self.release(),'macos-arm64')
  with self.assertRaises(AssertionError):gate.validate_reuse(self.lock,self.batch,self.release(),'windows-x64')
 def test_real_original_job_is_failed_not_success(self):
  r={'id':gate.RUN,'head_sha':gate.HEAD};j={'id':gate.JOB,'run_id':gate.RUN,'head_sha':gate.HEAD,'status':'completed','conclusion':'failure','name':'native (macos-arm64, macos-15)'};a={'id':14419846998,'size_in_bytes':10539,'digest':'sha256:'+gate.ARTIFACT_SHA};gate.verify_remote_identity(r,j,a);j['conclusion']='success'
  with self.assertRaises(AssertionError):gate.verify_remote_identity(r,j,a)
if __name__=='__main__':unittest.main()
