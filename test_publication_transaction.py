import copy
import ast
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlparse
from urllib.request import Request

from publication_transaction import PublicationIncomplete, publish_transaction


class FakeGitHub:
    def __init__(self, fault=None):
        self.releases = {
            'old': dict(id=1, name='old', body='old notes', prerelease=False, draft=False),
            'new': dict(id=2, name='candidate', body='candidate notes', prerelease=True, draft=False),
        }
        self.latest_id = 1
        self.ref = 'old-tag-object'
        self.assets = {('core-updates', 'a.json'): b'old a', ('core-updates', 'b.json'): b'old b'}
        self.fault = fault or {}
        self.calls = []

    def release(self, tag):
        return copy.deepcopy(self.releases[tag])

    def latest(self):
        return copy.deepcopy(next(r for r in self.releases.values() if r['id'] == self.latest_id))

    def tag_sha(self, tag):
        return self.ref

    def asset_bytes(self, tag, name):
        return self.assets.get((tag, name))

    def mutate(self, label, write, delete=None):
        self.calls.append(label)
        mode = self.fault.pop(label, None)
        if mode == 'before':
            raise TimeoutError(label)
        if mode == 'deleted':
            delete()
            raise TimeoutError(label)
        write()
        if mode == 'after':
            raise TimeoutError(label)

    def upload_bytes(self, tag, name, raw):
        label = 'upload:' + name + ':' + ('old' if raw.startswith(b'old') else 'new')
        def write():
            self.assets[tag, name] = raw
            if self.fault.pop(label + ':corrupt', False):
                self.assets[tag, name] = b'corrupt readback'
        self.mutate(label, write, lambda: self.assets.pop((tag, name), None))

    def delete_asset(self, tag, name):
        self.mutate('delete:' + name, lambda: self.assets.pop((tag, name), None))

    def set_tag(self, tag, commit):
        self.mutate('tag:' + commit, lambda: setattr(self, 'ref', commit))

    def edit_release(self, release_id, fields, latest):
        def write():
            row = next(r for r in self.releases.values() if r['id'] == release_id)
            row.update(fields)
            if latest:
                self.latest_id = release_id
        self.mutate('latest:' + str(release_id) + ':' + str(fields['prerelease']), write)


class PublicationTransactionTest(unittest.TestCase):
    def run_case(self, backend):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        try:
            result = publish_transaction(
                backend, tag='new', commit='new-publication',
                pointers={'a.json': b'new a', 'b.json': b'new b'},
                previous={'a.json': b'old a', 'b.json': b'old b'},
                installation=b'new instructions', receipt_file=root / 'receipt.json',
                receipt_factory=lambda release: {'release_id': release['id'], 'published': True},
                journal_file=root / 'journal.json', title='new title', notes='new notes', expected_latest_id=1)
            error = None
        except PublicationIncomplete as caught:
            result, error = None, caught
        return result, error, json.loads((root / 'journal.json').read_text())

    def assert_old(self, backend):
        self.assertEqual(backend.assets['core-updates', 'a.json'], b'old a')
        self.assertEqual(backend.assets['core-updates', 'b.json'], b'old b')
        self.assertEqual(backend.ref, 'old-tag-object')
        self.assertEqual(backend.latest_id, 1)
        self.assertTrue(backend.releases['new']['prerelease'])

    def test_deleted_asset_failure_restores_every_attempted_pointer(self):
        backend = FakeGitHub({'upload:b.json:new': 'deleted'})
        _, error, journal = self.run_case(backend)
        self.assertIsNotNone(error)
        self.assert_old(backend)
        self.assertEqual(journal['status'], 'failed_and_previous_state_verified')
        self.assertEqual(len(journal['attempted']), 2)

    def test_clobber_response_loss_is_read_back_without_repeating_write(self):
        backend = FakeGitHub({'upload:a.json:new': 'after'})
        result, error, journal = self.run_case(backend)
        self.assertIsNone(error)
        self.assertTrue(result['published'])
        self.assertEqual(backend.calls.count('upload:a.json:new'), 1)
        self.assertEqual(journal['status'], 'published_and_receipt_verified')

    def test_tag_and_latest_response_loss_are_not_retried(self):
        backend = FakeGitHub({'tag:new-publication': 'after', 'latest:2:False': 'after'})
        _, error, _ = self.run_case(backend)
        self.assertIsNone(error)
        self.assertEqual(backend.calls.count('tag:new-publication'), 1)
        self.assertEqual(backend.calls.count('latest:2:False'), 1)

    def test_real_tag_failure_restores_defaults_and_installation(self):
        backend = FakeGitHub({'tag:new-publication': 'before'})
        _, error, journal = self.run_case(backend)
        self.assertIsNotNone(error)
        self.assert_old(backend)
        self.assertNotIn(('new', 'INSTALLATION.txt'), backend.assets)
        self.assertEqual(journal['status'], 'failed_and_previous_state_verified')

    def test_real_latest_failure_restores_tag_and_all_defaults(self):
        backend = FakeGitHub({'latest:2:False': 'before'})
        _, error, journal = self.run_case(backend)
        self.assertIsNotNone(error)
        self.assert_old(backend)
        self.assertEqual(journal['status'], 'failed_and_previous_state_verified')

    def test_receipt_failure_does_not_republish_or_undo_consistent_latest(self):
        backend = FakeGitHub({'upload:PUBLICATION-RECEIPT.json:new': 'before'})
        _, error, journal = self.run_case(backend)
        self.assertIsNotNone(error)
        self.assertEqual(journal['status'], 'published_but_receipt_incomplete')
        self.assertEqual(backend.latest_id, 2)
        self.assertEqual(backend.ref, 'new-publication')
        self.assertEqual(backend.calls.count('latest:2:False'), 1)
        self.assertEqual(journal['recovery'], [])

    def test_receipt_response_loss_confirms_success(self):
        backend = FakeGitHub({'upload:PUBLICATION-RECEIPT.json:new': 'after'})
        _, error, journal = self.run_case(backend)
        self.assertIsNone(error)
        self.assertEqual(journal['status'], 'published_and_receipt_verified')

    def test_rollback_response_loss_is_confirmed_from_old_bytes(self):
        backend = FakeGitHub({'latest:2:False': 'before', 'upload:a.json:old': 'after'})
        _, error, journal = self.run_case(backend)
        self.assertIsNotNone(error)
        self.assert_old(backend)
        self.assertEqual(journal['status'], 'failed_and_previous_state_verified')

    def test_wrong_rollback_readback_stays_owner_action_required(self):
        backend = FakeGitHub({'latest:2:False': 'before', 'upload:a.json:old:corrupt': True})
        _, error, journal = self.run_case(backend)
        self.assertIsNotNone(error)
        self.assertEqual(journal['status'], 'failed_recovery_requires_owner_readback')
        self.assertTrue(any(r.get('restored_and_read_back') is False for r in journal['recovery']))
        self.assertEqual(backend.calls.count('upload:a.json:old'), 1)

    def test_unknown_rollback_get_does_not_blindly_overwrite(self):
        backend = FakeGitHub({'latest:2:False': 'before'})
        read = backend.asset_bytes
        def unavailable(tag, name):
            if name == 'a.json' and 'latest:2:False' in backend.calls:
                raise TimeoutError('readback unavailable')
            return read(tag, name)
        backend.asset_bytes = unavailable
        _, error, journal = self.run_case(backend)
        self.assertIsNotNone(error)
        self.assertEqual(journal['status'], 'failed_recovery_requires_owner_readback')
        self.assertNotIn('upload:a.json:old', backend.calls)

    def test_workflow_first_step_only_writes_local_marker_and_exact_gate(self):
        source = Path(__file__).with_name('.github') / 'workflows' / 'attachment-publish.yml'
        text = source.read_text()
        first = text.split('- name: Record publication run', 1)[1].split('- name:', 1)[0]
        self.assertIn('b.get("prepared") is True', first)
        self.assertIn('b["tag"]=="student-20261117-k12-2"', first)
        self.assertNotIn('gh release', first)
        self.assertNotIn('codex/k12-publish-20261116', text)

    def test_changed_latest_after_early_checks_causes_zero_writes(self):
        backend = FakeGitHub()
        backend.latest_id = 2
        with self.assertRaisesRegex(AssertionError, 'Latest changed'):
            self.run_case(backend)
        self.assertEqual(backend.calls, [])

    def test_candidate_already_published_causes_zero_writes(self):
        backend = FakeGitHub()
        backend.releases['new']['prerelease'] = False
        with self.assertRaisesRegex(AssertionError, 'no longer'):
            self.run_case(backend)
        self.assertEqual(backend.calls, [])

class AnonymousArchiveTest(unittest.TestCase):
    def helper(self, response_url, data, requests):
        source=Path(__file__).with_name('ci-promote-attachments.py')
        tree=ast.parse(source.read_text());functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='download_public_archive']
        class Response(io.BytesIO):
            def geturl(self):return response_url
        def opened(request,**kwargs):
            requests.append(request)
            assert not any(k.lower()=='authorization' for k,v in request.header_items())
            return Response(data)
        namespace=dict(sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(),urlparse=urlparse,Request=Request,urlopen=opened,time=__import__('time'))
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(source),'exec'),namespace)
        return namespace['download_public_archive']

    def test_complete_public_archive_is_hash_verified_without_authorization(self):
        requests=[];download=self.helper('https://release-assets.githubusercontent.com/data',b'abc',requests)
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory)/'core.tar.gz';row=dict(browser_download_url='https://github.com/data',url='https://api.github.com/data',size=3,digest='sha256:'+hashlib.sha256(b'abc').hexdigest())
            result=download(row,destination)
            self.assertTrue(result['anonymous_download']);self.assertEqual(destination.read_bytes(),b'abc');self.assertEqual(len(requests),1)

    def test_insecure_or_oversized_public_archives_stop_and_clean_partial(self):
        for url,data in [('http://github.com/data',b'abc'),('https://github.com/data',b'abcd')]:
            requests=[];download=self.helper(url,data,requests)
            with self.subTest(url=url),tempfile.TemporaryDirectory() as directory:
                destination=Path(directory)/'core.tar.gz';row=dict(browser_download_url='https://github.com/data',url='https://api.github.com/data',size=3,digest='sha256:'+'0'*64)
                with self.assertRaises(AssertionError):download(row,destination)
                self.assertEqual(list(Path(directory).iterdir()),[]);self.assertEqual(len(requests),2)


if __name__ == '__main__':
    unittest.main()
