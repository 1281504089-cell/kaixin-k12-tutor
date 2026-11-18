import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

class StableSnapshotTests(unittest.TestCase):
    def check(self, frozen, actual, latest=448283800):
        function=next(n for n in ast.parse(Path('ci-fresh-install.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='release_metadata')
        replies=[{'id':latest},{'assets':[{'name':n,'digest':'sha256:'+d} for n,d in actual.items()]},{'id':448792391,'tag_name':'student-20261117-k12-5'}]
        gh=Mock(side_effect=[json.dumps(r).encode() for r in replies])
        scope={'json':json,'subprocess':SimpleNamespace(check_output=gh),'lock':{'tag':'student-20261117-k12-5','reuse_existing_native':{'baseline_latest_id':448283800,'baseline_feeds':frozen}}}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<stable feed guard>','exec'),scope)
        return scope['release_metadata'],gh
    def test_actual_stable_bytes_pass_and_same_json_release_attachment_bytes_do_not(self):
        value={'runtimeId':'fixture','signature':'same signed contents','note':'中文'}
        release=json.dumps(value,ensure_ascii=False,indent=2).encode()
        stable=(json.dumps(value,indent=2)+'\n').encode()
        self.assertEqual(json.loads(release),json.loads(stable));self.assertNotEqual(release,stable)
        name='runtime-windows-x64.json';actual={name:hashlib.sha256(stable).hexdigest()}
        run,gh=self.check(actual,actual);self.assertEqual(run()['id'],448792391);self.assertEqual(gh.call_count,3)
        run,gh=self.check({name:hashlib.sha256(release).hexdigest()},actual)
        with self.assertRaisesRegex(AssertionError,'Stable feed changed'):run()
        self.assertEqual(gh.call_count,2)
    def test_latest_release_change_stops_before_candidate_download(self):
        run,gh=self.check({}, {},latest=999)
        with self.assertRaisesRegex(AssertionError,'Stable release changed'):run()
        self.assertEqual(gh.call_count,1)
    def test_any_one_platform_feed_change_is_rejected(self):
        baseline={n:'a'*64 for n in ['runtime-windows-x64.json','runtime-macos-x64.json','runtime-macos-arm64.json']}
        for name in baseline:
            changed=copy.deepcopy(baseline);changed[name]='b'*64
            run,_=self.check(baseline,changed)
            with self.subTest(name=name),self.assertRaisesRegex(AssertionError,'Stable feed changed'):run()

if __name__=='__main__':unittest.main()
