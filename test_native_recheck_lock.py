import ast,re,unittest
from pathlib import Path
source=Path(__file__).with_name('ci-promote-attachments.py').read_text()
nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in {'stage_run_for_target','recheck_lock_for_target'}]
namespace={'re':re};exec(compile(ast.Module(body=nodes,type_ignores=[]),'<publication-lock-guard>','exec'),namespace);choose=namespace['recheck_lock_for_target']
class NativeRecheckLockTest(unittest.TestCase):
 def seven(self):
  return {'tag':'student-20261117-k12-7','core_commit':'fbb301fd21cf2169f834e0b548d56d201cc98365','native_staging_run':44230306905,'native_staging_workflow_commit':'0738e1ac8cfbfddb9123d097bc90598abf5827fb','native_rechecks':{'macos-x64':{'lock_file':'intel-k12-7-reuse-lock.json'}}}
 def test_seven_selects_only_exact_original_intel_source_stage_and_lock(self):
  self.assertEqual(choose(self.seven(),'macos-x64'),'intel-k12-7-reuse-lock.json')
  for key,value in [('core_commit','0'*40),('native_staging_run',44202602948),('native_staging_workflow_commit','0'*40)]:
   b=self.seven();b[key]=value
   with self.assertRaises(AssertionError):choose(b,'macos-x64')
  for target,name in [('macos-arm64','intel-k12-7-reuse-lock.json'),('macos-x64','intel-k12-5-reuse-lock.json'),('macos-x64','../intel-k12-7-reuse-lock.json')]:
   b=self.seven();b['native_rechecks']={target:{'lock_file':name}}
   with self.assertRaises(AssertionError):choose(b,target)
 def six(self):
  return {'tag':'student-20261117-k12-6','core_commit':'4a61cd7edcd27c6bc6f6bb9305a5a4f3af8851e2','native_staging_run':44202602948,'native_staging_workflow_commit':'a61f75e11a4d8a7f99cda009e3eb76e6654eb5a0','native_rechecks':{'windows-x64':{'lock_file':'windows-k12-6-reuse-lock.json'}}}
 def test_exact_six_windows_selection(self):
  self.assertEqual(choose(self.six(),'windows-x64'),'windows-k12-6-reuse-lock.json')
 def test_six_rejects_wrong_source_original_run_target_or_old_lock(self):
  for key,value in [('core_commit','0'*40),('native_staging_run',44132557405),('native_staging_workflow_commit','0'*40)]:
   b=self.six();b[key]=value
   with self.assertRaises(AssertionError):choose(b,'windows-x64')
  for target,name in [('macos-x64','windows-k12-6-reuse-lock.json'),('windows-x64','windows-k12-4-reuse-lock.json'),('windows-x64','../windows-k12-6-reuse-lock.json')]:
   b=self.six();b['native_rechecks']={target:{'lock_file':name}}
   with self.assertRaises(AssertionError):choose(b,target)
 def test_exact_five_intel_selection_and_legacy_fallback(self):
  b={'tag':'student-20261117-k12-5','native_rechecks':{'macos-x64':{'lock_file':'intel-k12-5-reuse-lock.json'}}}
  self.assertEqual(choose(b,'macos-x64'),'intel-k12-5-reuse-lock.json');self.assertEqual(choose(b,'windows-x64'),'windows-k12-4-reuse-lock.json')
 def test_wrong_tag_platform_or_path_rejected(self):
  for tag,target,name in [('student-20261117-k12-4','macos-x64','intel-k12-5-reuse-lock.json'),('student-20261117-k12-5','macos-arm64','intel-k12-5-reuse-lock.json'),('student-20261117-k12-5','macos-x64','../intel-k12-5-reuse-lock.json')]:
   with self.assertRaises(AssertionError):choose({'tag':tag,'native_rechecks':{target:{'lock_file':name}}},target)
 def test_unknown_platform_rejected(self):
  with self.assertRaises(KeyError):choose({'tag':'student-20261117-k12-5'},'linux-x64')
