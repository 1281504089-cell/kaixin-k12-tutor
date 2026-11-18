import ast,copy,unittest
from pathlib import Path

tree=ast.parse(Path(__file__).with_name('ci-promote-attachments.py').read_text())
function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='verify_update_recovery')
scope={};exec(compile(ast.Module(body=[function],type_ignores=[]),'<publication recovery gate>','exec'),scope)
verify=scope['verify_update_recovery']

class RecoveryPublicationGate(unittest.TestCase):
 def fixture(self,target):
  batch={'tag':'student-20261117-k12-7','launcher_build':'20261118-updater-4','archives_core_name':'kaixin-core-20261117-k12-7.tar.gz'}
  runtime='1.7.1-kaixin-20261114-materials-'+target+'-universal'
  report={'launcher_tests':{'passed':True,'tests':83,'pass':79 if target=='windows-x64' else 83,'fail':0,'skipped':4 if target=='windows-x64' else 0},'network':{'interrupted_transport_fixture':{'faults':2,'recoveries':1,'verified_complete':True},'interrupted_direct_denied_api_fixture':{'mixedFaults':1,'apiDenials':1,'mixedRecoveries':1,'verified_complete':True,'anonymous_direct_download':True,'injected_api_denial':True}}}
  common={'from_runtime':runtime,'actual_download_install_backup_restart':'passed','check_again_current':True,'signed_launcher_restarted':True,'old_pid':100,'restarted_pid':200,'to_launcher':batch['launcher_build'],'chat_preserved':True,'task_preserved':True,'saved_key_preserved':True}
  report['materials_launcher_entry']={**common,'selected_base_runtime':runtime,'selected_archive':batch['archives_core_name']}
  report['materials_oldest_launcher_entry']={**common,'selected_base_runtime':None,'selected_archive':'kaixin-bridge-20261117-k12-7-'+target+'.tar.gz'}
  return report,batch
 def test_accepts_all_three_matching_targets(self):
  for target in ['windows-x64','macos-x64','macos-arm64']:
   report,batch=self.fixture(target);verify(report,batch,target)
 def test_rejects_missing_old_variant_or_failed_recovery_or_wrong_archive(self):
  original,batch=self.fixture('macos-arm64')
  for mutation in ['missing','network','archive','tests','records']:
   report=copy.deepcopy(original)
   if mutation=='missing':report.pop('materials_oldest_launcher_entry')
   elif mutation=='network':report['network']['interrupted_direct_denied_api_fixture']['apiDenials']=0
   elif mutation=='archive':report['materials_launcher_entry']['selected_archive']='unrelated.tar.gz'
   elif mutation=='tests':report['launcher_tests']['tests']=79
   else:report['materials_oldest_launcher_entry']['saved_key_preserved']=False
   with self.subTest(mutation=mutation),self.assertRaises((AssertionError,KeyError)):verify(report,batch,'macos-arm64')

 def test_rejects_stale_missing_or_wrong_platform_launcher_counts(self):
  for target in ['windows-x64','macos-x64','macos-arm64']:
   original,batch=self.fixture(target)
   counts=original['launcher_tests']
   for key,value in [('tests',82),('tests',84),('pass',counts['pass']-1),('skipped',counts['skipped']+1),('fail',1)]:
    report=copy.deepcopy(original);report['launcher_tests'][key]=value
    with self.subTest(target=target,key=key,value=value),self.assertRaises(AssertionError):verify(report,batch,target)
   for key in ['tests','pass','fail','skipped']:
    report=copy.deepcopy(original);report['launcher_tests'].pop(key)
    with self.subTest(target=target,missing=key),self.assertRaises(KeyError):verify(report,batch,target)

if __name__=='__main__':unittest.main()
