import ast
import copy
from pathlib import Path
import re
import unittest

source=Path('ci-promote-attachments.py').read_text()
function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='stage_run_for_target')
scope={'re':re};exec(compile(ast.Module(body=[function],type_ignores=[]),'<native stage map>','exec'),scope);stage=scope['stage_run_for_target']

class NativeStageBindingTests(unittest.TestCase):
 def setUp(self):
  self.batch={'native_staging_run':1,'native_staging_workflow_commit':'a'*40,'native_staging_runs':{t:{'run_id':2 if t=='macos-arm64' else 1,'workflow_commit':('b' if t=='macos-arm64' else 'a')*40} for t in ['windows-x64','macos-x64','macos-arm64']}}
 def test_target_run_is_explicit_and_other_platforms_stay_frozen(self):
  self.assertEqual(stage(self.batch,'macos-arm64')['run_id'],2);self.assertEqual(stage(self.batch,'windows-x64')['run_id'],1)
 def test_partial_maps_unknown_targets_and_invalid_ids_rejected(self):
  bad=copy.deepcopy(self.batch);bad['native_staging_runs'].pop('macos-arm64')
  with self.assertRaises(AssertionError):stage(bad,'windows-x64')
  with self.assertRaises(AssertionError):stage(self.batch,'other')
  for field,value in [('run_id',0),('run_id',True),('workflow_commit','invalid')]:
   bad=copy.deepcopy(self.batch);bad['native_staging_runs']['macos-arm64'][field]=value
   with self.subTest(field=field),self.assertRaises(AssertionError):stage(bad,'macos-arm64')
 def test_original_global_stage_binding_still_supported(self):
  self.batch.pop('native_staging_runs');self.assertEqual(stage(self.batch,'macos-arm64')['run_id'],1)

if __name__=='__main__':unittest.main()
