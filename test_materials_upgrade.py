import hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ci_update_probe import materials_baseline

class PublicResponse(io.BytesIO):
 def geturl(self):return 'https://release-assets.githubusercontent.com/fixture'

class MaterialsBaselineTests(unittest.TestCase):
 def fixture(self,root,corrupt=False):
  data=b'signed archive fixture'
  asset={'url':'https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/core-updates/fixture.tar.gz','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
  if corrupt:asset['sha256']='0'*64
  manifest={'runtimeId':'1.7.1-kaixin-20261114-materials-macos-arm64-universal','archive':'fixture.tar.gz'}
  (root/'materials-upgrade-lock.json').write_text(json.dumps({'launcher_build':'20261114-unified','targets':{'macos-arm64':{'asset':asset,'manifest':manifest}}}))
  return data,manifest
 def test_public_archive_is_hash_checked_and_retains_exact_runtime_identity(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);evidence=root/'evidence';evidence.mkdir();data,expected=self.fixture(root)
   with patch('ci_update_probe.urlopen',return_value=PublicResponse(data)) as fetch:
    actual=materials_baseline(root,'macos-arm64',evidence)
    (actual.parent/expected['archive']).unlink()
    self.assertEqual(materials_baseline(root,'macos-arm64',evidence),actual)
    self.assertEqual(fetch.call_count,1)
   self.assertEqual(json.loads(actual.read_text()),expected)
   self.assertIsNone(fetch.call_args.args[0].get_header('Authorization'))
   proof=json.loads((evidence/'materials-baseline-download.json').read_text())
   self.assertTrue(proof['full_archive_verified']);self.assertTrue(proof['anonymous_download'])
 def test_corrupt_archive_never_produces_an_install_manifest(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);evidence=root/'evidence';evidence.mkdir();data,_=self.fixture(root,corrupt=True)
   with patch('ci_update_probe.urlopen',return_value=PublicResponse(data)):
    with self.assertRaises(AssertionError):materials_baseline(root,'macos-arm64',evidence)
   self.assertFalse((root/'materials-baseline/runtime.json').exists())

if __name__=='__main__':unittest.main()
