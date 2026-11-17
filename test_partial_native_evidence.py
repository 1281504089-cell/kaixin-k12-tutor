import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
import partial_native_evidence as partial
ROOT=Path(__file__).resolve().parent
class CompletedEntrySourceTest(unittest.TestCase):
 def setUp(self):
  self.lock=json.loads((ROOT/'intel-k12-5-reuse-lock.json').read_text())
  self.files={name:(ROOT/'partial-entry-fixtures'/name).read_bytes() for name in ['oldest-update-entry.json','update-entry.json','reuse-lock.json']}
 def test_real_completed_source_receipts_retain_all_native_guards(self):
  result=partial.validate_completed_entries(self.lock,self.files)
  self.assertEqual(set(result),{'oldest_launcher_entry','update_entry'})
  self.assertTrue(all(len(r['k12_library']['views'])==4 for r in result.values()))
 def test_failed_remaining_path_cannot_be_claimed_reused(self):
  d=copy.deepcopy(self.lock);d['reused_complete_entries']['materials_launcher_entry']=d['reused_complete_entries']['update_entry']
  with self.assertRaises(AssertionError):partial.validate_completed_entries(d,self.files)
 def test_changed_receipt_or_parent_lock_rejected(self):
  for name in self.files:
   files=dict(self.files);files[name]+=b' '
   with self.subTest(name=name),self.assertRaises(AssertionError):partial.validate_completed_entries(self.lock,files)
 def test_different_core_or_pdf_scope_rejected(self):
  for key in ['core_asset','native_pages']:
   d=copy.deepcopy(self.lock)
   if key=='core_asset':d[key]['sha256']='0'*64
   else:d[key]['manifest_sha256']='0'*64
   with self.assertRaises(AssertionError):partial.validate_completed_entries(d,self.files)
 def test_other_run_or_archive_cannot_substitute(self):
  for key in ['run_id','id','sha256','source_lock_sha256']:
   d=copy.deepcopy(self.lock);v=d['resume_artifact'][key];d['resume_artifact'][key]=v+1 if isinstance(v,int) else '0'*64
   with self.assertRaises(AssertionError):partial.validate_partial_lock(d)
  with self.assertRaises(AssertionError):partial.validate_partial_archive(self.lock,b'not the pinned ZIP')
 def metadata(self):
  a=partial.ARTIFACT
  return [{'id':a['id'],'size_in_bytes':a['bytes'],'digest':'sha256:'+a['sha256'],'expired':False},{'status':'completed','conclusion':'failure','head_sha':a['workflow_commit']},{'jobs':[{'id':a['job_id'],'conclusion':'failure'}]}]
 def test_transport_checks_actual_failed_source_run_before_reading_bytes(self):
  with patch.object(partial,'validate_partial_archive',return_value={'verified':'fixture'}) as validate:
   values=iter(self.metadata());result=partial.fetch_partial_archive(self.lock,lambda _p:next(values),lambda *_a:b'passed to full verifier')
   self.assertEqual(result,{'verified':'fixture'});validate.assert_called_once_with(self.lock,b'passed to full verifier')
 def test_source_expiry_head_or_job_change_fails_before_download(self):
  for i in range(3):
   values=self.metadata()
   if i==0:values[0]['expired']=True
   elif i==1:values[1]['head_sha']='0'*40
   else:values[2]['jobs'][0]['conclusion']='success'
   it=iter(values)
   with self.assertRaises(AssertionError):partial.fetch_partial_archive(self.lock,lambda _p:next(it),lambda *_a:self.fail('Invalid source was downloaded'))
if __name__=='__main__':unittest.main()
