import ast,copy,unittest
from pathlib import Path

source=Path(__file__).with_name('ci-promote-attachments.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='verify_complete_native_source')
namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'<complete-native-publication>','exec'),namespace)
verify=namespace['verify_complete_native_source']

class CompleteNativePublicationTest(unittest.TestCase):
 def fixture(self):
  entries={key:{'source':key,'preserved':True} for key in ['update_entry','oldest_launcher_entry','materials_launcher_entry','materials_oldest_launcher_entry']}
  completed={'entries':entries,'smoke':{'source':'native7'},'fresh_picture_ui':{'native_pages':True},'network':{'proxy_connections':3},'launcher_tests':{'tests':83,'fail':0}}
  report={**copy.deepcopy(entries),'native_smoke':copy.deepcopy(completed['smoke']),'fresh_picture_ui':copy.deepcopy(completed['fresh_picture_ui']),'network':copy.deepcopy(completed['network']),'launcher_tests':copy.deepcopy(completed['launcher_tests']),
   'native_postflight':dict(passed=True,source_artifact_sha256='a'*64,signed_stage_sha256='b'*64,production_launcher_files_verified=24,production_codesign_deep_strict_passed=True,immutable_assets_verified=76,public_installer_files_verified=5,signed_runtime_manifests_verified=45)}
  return report,completed,{'sha256':'a'*64},'b'*64
 def test_all_four_complete_entries_and_actual_postchecks_are_bound(self):verify(*self.fixture())
 def test_any_changed_native_body_is_rejected(self):
  for key in ['update_entry','oldest_launcher_entry','materials_launcher_entry','materials_oldest_launcher_entry','native_smoke','fresh_picture_ui','network','launcher_tests']:
   args=self.fixture();args[0][key]['tampered']=True
   with self.subTest(key=key),self.assertRaises(AssertionError):verify(*args)
 def test_partial_or_extra_entry_cannot_become_complete(self):
  for changed in ['missing','extra']:
   args=self.fixture()
   if changed=='missing':del args[1]['entries']['materials_oldest_launcher_entry']
   else:args[1]['entries']['unexecuted_entry']={}
   with self.subTest(changed=changed),self.assertRaises(AssertionError):verify(*args)
 def test_unexecuted_or_foreign_postchecks_are_rejected(self):
  for key,value in [('passed',False),('source_artifact_sha256','0'*64),('signed_stage_sha256','0'*64),('production_launcher_files_verified',23),('production_codesign_deep_strict_passed',False),('immutable_assets_verified',75),('public_installer_files_verified',4),('signed_runtime_manifests_verified',44)]:
   args=self.fixture();args[0]['native_postflight'][key]=value
   with self.subTest(key=key),self.assertRaises(AssertionError):verify(*args)

if __name__=='__main__':unittest.main()
