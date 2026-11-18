import copy
import ast
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


class PublicationSourceBindingTests(unittest.TestCase):
    def check_producer(self, publication, release):
        nodes = ast.parse(Path('ci-promote-attachments.py').read_text()).body
        selected = []
        for node in nodes:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {'batch', 'release_config'} for target in node.targets):
                selected.append(node)
            elif isinstance(node, ast.Assert):
                selected.append(node)
                break
        self.assertEqual(len(selected), 3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'attachment-publication.json').write_text(json.dumps(publication))
            (root / 'attachment-release.json').write_text(json.dumps(release))
            try:
                exec(compile(ast.Module(body=selected, type_ignores=[]), '<publication source guard>', 'exec'), {'root': root, 'json': json})
                return True
            except AssertionError:
                return False

    def check_binding(self, publication, release):
        workflow = Path('.github/workflows/attachment-publish.yml').read_text()
        line = next(line.strip() for line in workflow.splitlines() if 'publication-run.json' in line)
        arguments = shlex.split(line)
        self.assertEqual(arguments[:2], ['python', '-c'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'attachment-publication.json').write_text(json.dumps(publication))
            (root / 'attachment-release.json').write_text(json.dumps(release))
            result = subprocess.run([sys.executable, '-c', arguments[2]], cwd=root,
                                    env={**os.environ, 'GITHUB_RUN_ID': '1', 'GITHUB_SHA': 'a' * 40},
                                    capture_output=True)
            return result.returncode, (root / 'publication-run.json').exists()

    def test_coherent_next_batch_and_all_mismatches(self):
        for tag in ['student-20261117-k12-8', 'student-20261117-k12-9']:
            publication = {'prepared': True, 'tag': tag, 'core_commit': 'b' * 40}
            release = {'prepared': True, 'tag': tag, 'source_commit': 'b' * 40}
            self.assertEqual(self.check_binding(publication, release), (0, True))
            self.assertTrue(self.check_producer(publication, release))
            for field, value in [('prepared', False), ('tag', 'student-20261117-k12-7'), ('core_commit', 'c' * 40)]:
                changed = copy.deepcopy(publication)
                changed[field] = value
                code, exists = self.check_binding(changed, release)
                self.assertNotEqual(code, 0)
                self.assertFalse(exists)
                self.assertFalse(self.check_producer(changed, release))
            release['prepared'] = False
            code, exists = self.check_binding(publication, release)
            self.assertNotEqual(code, 0)
            self.assertFalse(exists)
            self.assertFalse(self.check_producer(publication, release))


if __name__ == '__main__':
    unittest.main()
