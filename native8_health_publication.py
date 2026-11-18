"""Read-only publication binding for the single accepted original ARM8 health sample."""
import argparse
import json
import math
from pathlib import Path
import sys

import ci_native8_health_acceptance as health

ROOT = Path(__file__).resolve().parent
TARGETS = {'windows-x64', 'macos-x64', 'macos-arm64'}


def canonical(value):
    # Keep JSON types exact: False must not compare equal to the number zero.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate_health_publication(batch, target, report, attachments):
    """Check evidence only; never turn an unfinished native execution into a pass."""
    if sys.flags.optimize:
        raise RuntimeError('Publication health assertions must remain enabled')
    assert target in TARGETS and report.get('target') == target, 'Health evidence target mismatch'
    assert isinstance(attachments, dict) and isinstance(report.get('native_smoke'), dict)
    smoke = report['native_smoke']
    marked = ('explicit_health_acceptance' in attachments,
              'attachment_original_receipt_acceptance' in smoke,
              'qa_acceptance_exceptions' in report,
              'original_failed_native' in report)
    if not any(marked):
        if 'health_max_seconds' in attachments:
            metric = attachments['health_max_seconds']
            assert type(metric) in (int, float) and math.isfinite(metric) and 0 <= metric < 5, 'Unmarked original health exception'
        return None

    assert target == health.TARGET and all(marked), 'Unbound or non-ARM8 health exception'
    stamp = attachments['explicit_health_acceptance']
    assert isinstance(stamp, dict), 'Missing explicit health stamp'
    if batch.get('prepared') is True:
        native = json.loads((ROOT/'attachment-batch.json').read_bytes())
        assert all(native[key] == batch[key] for key in ['tag', 'core_commit', 'launcher_build', 'builtAt', 'shell_files']), 'Publication differs from native batch'
        manifest = native['manifests'][target]
        assert manifest in batch['manifests'].values(), 'Native core manifest missing from publication'
        archive = batch['archives'][manifest['archive']]
        assert (archive['source_tag'], archive['sha256'], archive['bytes']) == (native['tag'], native['core_asset']['digest'][7:], native['core_asset']['size']), 'Publication core archive differs from native batch'
        batch = native
    health.validate_embedded(stamp, target, batch)
    expected = health.validate_original(ROOT/'native8-arm-health-acceptance.json',
                                        ROOT/'native8-arm-health-original.zip', target,
                                        batch, batch['manifests'][target])
    assert canonical(attachments) == canonical(expected), 'Attachment evidence differs from the accepted original sample'
    assert canonical(smoke['attachment_original_receipt_acceptance']) == canonical(stamp), 'Native smoke health stamp differs'
    assert canonical(report['qa_acceptance_exceptions']) == canonical([stamp]), 'Native health exception list differs'
    failed = {'run_id':health.RUN, 'job_id':health.JOB, 'workflow_commit':health.HEAD,
              'conclusion':'failure', 'not_relabelled_as_success':True}
    assert canonical(report['original_failed_native']) == canonical(failed), 'Original failed native provenance changed'
    return stamp


def main():
    parser = argparse.ArgumentParser()
    for name in ['batch', 'report', 'attachments']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--target', required=True, choices=sorted(TARGETS))
    args = parser.parse_args()
    read = lambda path: json.loads(Path(path).read_bytes())
    stamp = validate_health_publication(read(args.batch), args.target, read(args.report), read(args.attachments))
    print(json.dumps({'target':args.target, 'explicit_original_health_acceptance_checked':stamp is not None}))


if __name__ == '__main__':
    main()
