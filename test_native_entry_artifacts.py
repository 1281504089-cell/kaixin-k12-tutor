import ast, copy, json, tempfile, unittest
from pathlib import Path

tree=ast.parse(Path(__file__).with_name('ci-promote-attachments.py').read_text())
function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='verify_native_entry_artifacts')
scope={'json':json};exec(compile(ast.Module(body=[function],type_ignores=[]),'<native artifact binding>','exec'),scope)
verify=scope['verify_native_entry_artifacts']
ENTRIES={'update_entry':'update-entry','oldest_launcher_entry':'oldest-update-entry','materials_launcher_entry':'materials-update-entry','materials_oldest_launcher_entry':'materials-oldest-update-entry'}
SIDECARS={'library-bulk.json':'library_bulk_upload','chat-audio.json':'chat_audio','native-science.json':'science_formulas','quick-preview.json':'quick_preview'}

class NativeArtifactBinding(unittest.TestCase):
 def fixture(self,root):
  report={key:{field:{'entry':key,'passed':True} for field in SIDECARS.values()} for key in ENTRIES}
  for key,name in ENTRIES.items():(root/(name+'.json')).write_text(json.dumps(report[key]))
  for name,key in SIDECARS.items():(root/name).write_text(json.dumps(report['materials_oldest_launcher_entry'][key]))
  return report
 def test_checks_all_four_receipts_and_the_actual_last_sidecars(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);report=self.fixture(root)
   self.assertEqual(verify(report,root),{'per_entry_receipts_verified':4,'shared_sidecars_from':'materials_oldest_launcher_entry'})
 def test_a_different_current_entry_cannot_pass_via_good_last_sidecars(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);report=self.fixture(root);changed=copy.deepcopy(report);changed['update_entry']['chat_audio']['passed']=False
   with self.assertRaises(AssertionError):verify(changed,root)
 def test_stale_earlier_or_corrupted_shared_sidecars_are_rejected(self):
  for old in [True,False]:
   with self.subTest(earlier=old),tempfile.TemporaryDirectory() as folder:
    root=Path(folder);report=self.fixture(root)
    (root/'chat-audio.json').write_text(json.dumps(report['update_entry']['chat_audio'] if old else {'passed':False}))
    with self.assertRaises(AssertionError):verify(report,root)

if __name__=='__main__':unittest.main()
