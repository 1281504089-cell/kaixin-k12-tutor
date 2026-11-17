import ast,unittest
from pathlib import Path
source=Path(__file__).with_name('ci-promote-attachments.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='recheck_lock_for_target')
namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'<publication-lock-guard>','exec'),namespace);choose=namespace['recheck_lock_for_target']
class NativeRecheckLockTest(unittest.TestCase):
 def test_exact_five_intel_selection_and_legacy_fallback(self):
  b={'tag':'student-20261117-k12-5','native_rechecks':{'macos-x64':{'lock_file':'intel-k12-5-reuse-lock.json'}}}
  self.assertEqual(choose(b,'macos-x64'),'intel-k12-5-reuse-lock.json');self.assertEqual(choose(b,'windows-x64'),'windows-k12-4-reuse-lock.json')
 def test_wrong_tag_platform_or_path_rejected(self):
  for tag,target,name in [('student-20261117-k12-4','macos-x64','intel-k12-5-reuse-lock.json'),('student-20261117-k12-5','macos-arm64','intel-k12-5-reuse-lock.json'),('student-20261117-k12-5','macos-x64','../intel-k12-5-reuse-lock.json')]:
   with self.assertRaises(AssertionError):choose({'tag':tag,'native_rechecks':{target:{'lock_file':name}}},target)
 def test_unknown_platform_rejected(self):
  with self.assertRaises(KeyError):choose({'tag':'student-20261117-k12-5'},'linux-x64')
