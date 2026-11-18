"""Offline positive/negative controls for both publication callers; no native reruns."""
import ast
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import ci_native8_health_acceptance as health
import native8_health_publication as publication

ROOT = Path(__file__).resolve().parent


class HealthPublication(unittest.TestCase):
    def setUp(self):
        # Only the policy fields used here are synthetic. Keep this historical8 control
        # independent of later active publication batches and their signed metadata.
        self.batch = {'tag':health.TAG, 'core_commit':health.SOURCE,
                      'core_asset':{'digest':'sha256:'+health.CORE},
                      'manifests':{health.TARGET:{'commit':health.SOURCE, 'sha256':health.CORE}}}
        self.attachment = health.validate_original(ROOT/'native8-arm-health-acceptance.json',
                            ROOT/'native8-arm-health-original.zip', health.TARGET,
                            self.batch, self.batch['manifests'][health.TARGET])
        stamp = self.attachment['explicit_health_acceptance']
        self.report = {'target':health.TARGET,
                       'native_smoke':{'attachment_original_receipt_acceptance':copy.deepcopy(stamp)},
                       'qa_acceptance_exceptions':[copy.deepcopy(stamp)],
                       'original_failed_native':{'run_id':health.RUN, 'job_id':health.JOB,
                           'workflow_commit':health.HEAD, 'conclusion':'failure', 'not_relabelled_as_success':True}}

    def validate(self):
        return publication.validate_health_publication(self.batch, health.TARGET, self.report, self.attachment)

    def test_exact_original_acceptance_passes_without_changing_evidence(self):
        before = publication.canonical([self.batch, self.report, self.attachment])
        self.assertEqual(self.validate(), self.attachment['explicit_health_acceptance'])
        self.assertEqual(before, publication.canonical([self.batch, self.report, self.attachment]))

    def test_ordinary_three_targets_and_historical_batch_have_no_exception(self):
        for target in publication.TARGETS:
            with self.subTest(target=target):
                self.assertIsNone(publication.validate_health_publication({'tag':'student-20261117-k12-7'}, target,
                    {'target':target, 'native_smoke':{}}, {'health_max_seconds':0.5}))

    def test_every_exception_copy_and_failed_provenance_are_required(self):
        changes = [lambda r,a:a.pop('explicit_health_acceptance'),
                   lambda r,a:r['native_smoke'].pop('attachment_original_receipt_acceptance'),
                   lambda r,a:r.pop('qa_acceptance_exceptions'),
                   lambda r,a:r.pop('original_failed_native')]
        for change in changes:
            report, attachment = copy.deepcopy(self.report), copy.deepcopy(self.attachment)
            change(report, attachment)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                publication.validate_health_publication(self.batch, health.TARGET, report, attachment)

    def test_non_arm_exception_is_rejected(self):
        for target in ['windows-x64', 'macos-x64']:
            report = copy.deepcopy(self.report); report['target'] = target
            with self.subTest(target=target), self.assertRaises(AssertionError):
                publication.validate_health_publication(self.batch, target, report, self.attachment)

    def test_three_stamps_must_be_identical_and_not_broader(self):
        for change in [lambda r:r['native_smoke']['attachment_original_receipt_acceptance'].update(original_health_max_seconds=5.249),
                       lambda r:r.update(qa_acceptance_exceptions=[]),
                       lambda r:r['qa_acceptance_exceptions'].append(copy.deepcopy(r['qa_acceptance_exceptions'][0]))]:
            report = copy.deepcopy(self.report); change(report)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                publication.validate_health_publication(self.batch, health.TARGET, report, self.attachment)

    def test_original_failure_cannot_be_relabelled_or_substituted(self):
        for key, value in [('run_id',1), ('job_id',1), ('workflow_commit','0'*40),
                           ('conclusion','success'), ('not_relabelled_as_success',False)]:
            report = copy.deepcopy(self.report); report['original_failed_native'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                publication.validate_health_publication(self.batch, health.TARGET, report, self.attachment)

    def test_wrong_source_core_or_tag_rejected(self):
        for change in [lambda b:b.update(core_commit='0'*40), lambda b:b.update(tag='student-20261117-k12-7'),
                       lambda b:b['core_asset'].update(digest='sha256:'+'0'*64)]:
            batch = copy.deepcopy(self.batch); change(batch)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                publication.validate_health_publication(batch, health.TARGET, self.report, self.attachment)

    def test_original_metrics_and_boolean_json_types_cannot_change(self):
        for change in [lambda a:a.update(health_max_seconds=5.249),
                       lambda a:a['explicit_health_acceptance'].update(original_health_gate_passed=0),
                       lambda a:a.update(scanned_pdf_retrievable=False)]:
            attachment = copy.deepcopy(self.attachment); change(attachment)
            report = copy.deepcopy(self.report)
            report['native_smoke']['attachment_original_receipt_acceptance'] = copy.deepcopy(attachment['explicit_health_acceptance'])
            report['qa_acceptance_exceptions'] = [copy.deepcopy(attachment['explicit_health_acceptance'])]
            with self.subTest(change=change), self.assertRaises(AssertionError):
                publication.validate_health_publication(self.batch, health.TARGET, report, attachment)

    def test_unmarked_slow_health_or_exception_fields_are_rejected(self):
        for metric in [5, 5.248, True, float('nan')]:
            with self.subTest(metric=metric), self.assertRaises(AssertionError):
                publication.validate_health_publication(self.batch, health.TARGET,
                    {'target':health.TARGET, 'native_smoke':{}}, {'health_max_seconds':metric})
        with self.assertRaises(AssertionError):
            publication.validate_health_publication(self.batch, health.TARGET,
                {'target':health.TARGET, 'native_smoke':{}, 'qa_acceptance_exceptions':[]}, {'health_max_seconds':1})

    def test_actual_publisher_call_uses_the_shared_guard(self):
        source = ast.parse((ROOT/'ci-promote-attachments.py').read_text())
        imports = [n for n in ast.walk(source) if isinstance(n, ast.ImportFrom) and n.module == 'native8_health_publication']
        calls = [n for n in ast.walk(source) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Name) and n.value.func.id == 'validate_health_publication']
        self.assertEqual((len(imports), len(calls)), (1,1))
        code = compile(ast.Module(body=[*imports, *calls], type_ignores=[]), 'actual-publisher-health-call', 'exec')
        namespace = dict(batch=self.batch, target=health.TARGET, report=self.report, attachment=self.attachment)
        exec(code, namespace)
        namespace['report'] = copy.deepcopy(self.report); namespace['report'].pop('qa_acceptance_exceptions')
        with self.assertRaises(AssertionError): exec(code, namespace)

    def test_real_node_cli_invocation_rejects_bad_proof(self):
        # The owner runner is local-only. Exercise its shared CLI without depending
        # on a file above the GitHub checkout; the actual owner statement is checked
        # separately by the local owner verification receipt.
        script = """import {execFileSync} from 'node:child_process';
execFileSync('python3',['recipe/native8_health_publication.py','--batch','recipe/attachment-batch.json',
 '--target','macos-arm64','--report','evidence/native-stage/verification-macos-arm64.json',
 '--attachments','evidence/native-stage/attachments-macos-arm64.json'],{encoding:'utf8',timeout:20000});"""
        with tempfile.TemporaryDirectory(prefix='health-publication-') as temporary:
            root = Path(temporary); (root/'recipe').mkdir(); stage = root/'evidence/native-stage'; stage.mkdir(parents=True)
            for name in ['native8_health_publication.py', 'ci_native8_health_acceptance.py',
                         'native8-arm-health-acceptance.json', 'native8-arm-health-original.zip']:
                shutil.copyfile(ROOT/name, root/'recipe'/name)
            (root/'recipe/attachment-batch.json').write_text(json.dumps(self.batch))
            proof = stage/'verification-macos-arm64.json'; proof.write_text(json.dumps(self.report))
            (stage/'attachments-macos-arm64.json').write_text(json.dumps(self.attachment))
            command = ['node', '--input-type=module', '-e', script]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            bad = copy.deepcopy(self.report); bad['original_failed_native']['conclusion'] = 'success'
            proof.write_text(json.dumps(bad))
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Original failed native provenance changed', result.stderr)

    def test_optimized_python_is_rejected(self):
        code = "import native8_health_publication as p;p.validate_health_publication({},'macos-arm64',{}, {})"
        result = subprocess.run([sys.executable, '-B', '-O', '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('assertions must remain enabled', result.stderr)


if __name__ == '__main__':
    unittest.main()
