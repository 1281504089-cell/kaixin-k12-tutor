"""Supplement final Intel7 byte/signature checks without repeating completed native routes."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

SOURCE_LOCK = 'intel-k12-7-reuse-lock.json'
FINALIZATION_LOCK = 'intel7-finalization-lock.json'
SOURCE_LOCK_SHA = '7116479c7e4b3ceba3e5222258f8e2ff91eaf6f4f8dac990cd127e26174bfe97'
COMPLETE_SOURCE = {
    'id':14407657263, 'bytes':13410126,
    'sha256':'dc967707d98461e1840c80447904446067c4125d7dcabdf95994b61155cc388b',
    'run_id':44248561243, 'workflow_commit':'7a7c7e0d26f1796f35f606afe42eaa8c31599db6',
    'job_id':134613361890, 'source_lock_sha256':SOURCE_LOCK_SHA,
}
BRANCH_PREFIX = 'codex/k12-intel7-postflight-20261118-'
ALLOWED_CHANGES = ['ci-mac-reuse.py', 'test_intel7_reuse.py', 'ci-promote-attachments.py']
NEW_INPUTS = {
    'ci-finalize-intel7.py', 'test_intel7_finalization.py',
    'intel7_complete_evidence.py', 'test_intel7_complete_evidence.py',
    'intel7-complete-members.json', 'intel7-complete-record-fixtures.json',
}
WORK = 'intel7-postflight-work'
EVIDENCE = 'fresh-evidence/macos-x64'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def preflight(root, env=None, native=True):
    """Read-only lock/input checks precede imports, network, evidence writes and mounting."""
    if sys.flags.optimize:
        raise RuntimeError('Intel7 postflight assertions must remain enabled')
    root = root.resolve()
    env = os.environ if env is None else env
    raw = (root/FINALIZATION_LOCK).read_bytes()
    expected = env.get('KX_FINALIZATION_LOCK_SHA256', '')
    assert re.fullmatch(r'[a-f0-9]{64}', expected) and hashlib.sha256(raw).hexdigest() == expected, 'Owner-frozen finalization raw SHA required'
    final = json.loads(raw)
    source_raw = (root/SOURCE_LOCK).read_bytes()
    assert hashlib.sha256(source_raw).hexdigest() == SOURCE_LOCK_SHA, 'Original source lock bytes changed'
    source = json.loads(source_raw)
    identity = dict(schema_version=1, frozen=True, target='macos-x64',
                    candidate_tag='student-20261117-k12-7',
                    source_commit='fbb301fd21cf2169f834e0b548d56d201cc98365',
                    launcher_build='20261118-updater-4', source_lock_file=SOURCE_LOCK,
                    source_lock_sha256=SOURCE_LOCK_SHA, complete_native_execution=COMPLETE_SOURCE,
                    frozen_stage=source['frozen_stage'], allowed_source_input_changes=ALLOWED_CHANGES,
                    workflow_branch_prefix=BRANCH_PREFIX)
    for key, value in identity.items():
        assert final.get(key) == value, 'Finalization identity changed: '+key
    assert final['frozen'] is True and source['execution_frozen'] is True
    original = source['recipe_inputs_sha256']
    inputs = final['postflight_inputs_sha256']
    assert len(original) == 145 and set(original) | NEW_INPUTS <= set(inputs), 'Missing original or finalization input'
    for name, digest in inputs.items():
        assert isinstance(name, str) and name and not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name
        assert name not in {SOURCE_LOCK, FINALIZATION_LOCK} and not name.startswith('.github/workflows/'), 'Freeze locks/workflow separately to avoid a self-hash cycle'
        assert isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest), 'Invalid input digest: '+name
        file = root/name
        assert file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(root), 'Input escapes frozen checkout: '+name
        if name in original and name not in ALLOWED_CHANGES:
            assert digest == original[name], 'Original execution input changed: '+name
        assert sha(file) == digest, 'Frozen postflight input changed: '+name
    assert hashlib.sha256((root/'attachment-final-manifests.json').read_bytes()).hexdigest() == source['frozen_stage']['sha256']
    assert len((root/'attachment-final-manifests.json').read_bytes()) == source['frozen_stage']['bytes']
    batch = json.loads((root/'attachment-batch.json').read_bytes())
    assert batch['tag'] == source['candidate_tag'] and batch['core_commit'] == source['source_commit'] and batch['launcher_build'] == source['launcher_build']
    assert batch['manifests']['macos-x64'] == source['included_manifest'] and len(batch['shell_files']) == 24
    run_id = int(env['GITHUB_RUN_ID'])
    assert run_id > 0 and run_id not in {COMPLETE_SOURCE['run_id'], source['original_native_run']}, 'A new postflight run is required'
    head = env['GITHUB_SHA']
    assert re.fullmatch(r'[a-f0-9]{40}', head) and head not in {COMPLETE_SOURCE['workflow_commit'], source['original_native_workflow_commit']}
    assert env.get('GITHUB_REF_NAME', '').startswith(BRANCH_PREFIX) and len(env['GITHUB_REF_NAME']) > len(BRANCH_PREFIX)
    if native:
        assert sys.platform == 'darwin' and platform.machine() == 'x86_64', 'Actual Intel macOS runner required'
    for name in [WORK, EVIDENCE, 'macos-x64-reuse-work', 'prior-update', 'materials-baseline', 'student-source', 'launcher-tests-macos-x64']:
        assert not (root/name).exists(), 'Use a clean disposable checkout; do not resume: '+name
    return source, final, batch


def load_module(root, name, module_name):
    spec = importlib.util.spec_from_file_location(module_name, root/name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def asset_snapshot(release, lock):
    names = {row['name'] for row in lock['immutable_existing_assets']}
    rows = sorted([{k:a[k] for k in ('name', 'id', 'size', 'digest')} for a in release['assets'] if a['name'] in names], key=lambda r:r['name'])
    assert len(rows) == 76 and len({r['id'] for r in rows}) == 76
    return rows


def verify_installed(root, app, lock, batch, signed, reuse):
    resources = app/'Contents/Resources'
    included = json.loads((resources/'update/runtime.json').read_bytes())
    assert included == lock['included_manifest'], 'Included runtime changed'
    assert json.loads((resources/'seed/runtime.json').read_bytes())['runtimeId'] == included['baseRuntimeId'], 'Base runtime changed'
    core = resources/'update'/included['archive']
    assert core.stat().st_size == lock['core_asset']['bytes'] and sha(core) == lock['core_asset']['sha256'], 'Included core bytes changed'
    for name, row in batch['shell_files'].items():
        assert sha(resources/'app'/name) == row['sha256'], 'Production launcher changed: '+name
    assert {p.name for p in (resources/'app/src').iterdir()} == {Path(name).name for name in batch['shell_files']}, 'Unexpected launcher source file'
    reuse.verify_signatures(root, resources, lock, signed)
    return resources


def install_intel(work, downloads, reuse):
    install = work/'installed'; install.mkdir()
    mount = work/'mount'; mount.mkdir()
    images = list(downloads.glob('*-part.dmg'))
    assert len(images) == 1, 'Exactly one frozen Intel split-image head required'
    reuse.run(['/usr/bin/hdiutil', 'verify', images[0]], timeout=300)
    attached = False
    app = install/'开心动力超级学霸.app'
    try:
        reuse.run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', mount, images[0]], timeout=300)
        attached = True
        reuse.run(['/usr/bin/ditto', mount/app.name, app], timeout=600)
    finally:
        if attached:
            reuse.run(['/usr/bin/hdiutil', 'detach', mount], timeout=120)
    architectures = reuse.run(['/usr/bin/lipo', '-archs', app/'Contents/MacOS/开心动力超级学霸'], capture_output=True, text=True, timeout=60)
    assert 'x86_64' in architectures.stdout.split(), 'Installed executable has no Intel architecture'
    return app


def finalize(root, env=None):
    env = os.environ if env is None else env
    source, final, batch = preflight(root, env)
    reuse = load_module(root, 'ci-mac-reuse.py', 'intel7_postflight_reuse')
    complete = load_module(root, 'intel7_complete_evidence.py', 'intel7_postflight_complete')
    complete.validate_source_lock(source)
    reuse.validate_lock(source, (root/'attachment-final-manifests.json').read_bytes())
    proof = complete.fetch_complete_archive(source, reuse.api, reuse.gh)
    entries = proof['entries']
    reuse.validate_native_proofs(proof['smoke'], proof['fresh_picture_ui'], entries['update_entry'], entries['oldest_launcher_entry'], source, entries['materials_launcher_entry'], entries['materials_oldest_launcher_entry'])
    release = reuse.verify_metadata(source)
    assert not any(a['name'] == 'verification-macos-x64.json' for a in release['assets']), 'Final verification already exists; never overwrite'
    before = asset_snapshot(release, source)
    assert json.loads(proof['files']['immutable-assets-before.json']) == before, 'Original immutable asset baseline changed'
    evidence = root/EVIDENCE; evidence.mkdir(parents=True)
    for name, raw in proof['files'].items():
        destination = evidence/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(raw)
    write_json(evidence/'postflight-immutable-assets-before.json', before)
    with (evidence/FINALIZATION_LOCK).open('xb') as stream:
        stream.write((root/FINALIZATION_LOCK).read_bytes())
    run_id, head = int(env['GITHUB_RUN_ID']), env['GITHUB_SHA']
    marker = evidence/('native-reverify-run-macos-x64-'+str(run_id)+'.json')
    write_json(marker, dict(target='macos-x64', run_id=run_id, workflow_commit=head,
                           source_commit=source['source_commit'], mode='complete-native-final-postchecks',
                           complete_native_execution=COMPLETE_SOURCE, reuse_lock_file=SOURCE_LOCK,
                           reuse_lock_sha256=SOURCE_LOCK_SHA, finalization_lock_file=FINALIZATION_LOCK,
                           finalization_lock_sha256=sha(root/FINALIZATION_LOCK), frozen_stage_sha256=source['frozen_stage']['sha256']))
    reuse.upload_new(source['candidate_tag'], marker, 'macos-x64')
    work = root/WORK; work.mkdir()
    signed = work/'signed-manifests'; signed.mkdir()
    signed_receipts = [reuse.download(row, signed) for row in source['signed_runtime_assets']]
    downloads = work/'downloads'; downloads.mkdir()
    receipts = [reuse.download(row, downloads) for row in source['candidate_files']]
    assert len(receipts) == 5 and len(signed_receipts) == 45
    write_json(evidence/'postflight-downloads.json', receipts)
    write_json(evidence/'postflight-signed-manifests.json', signed_receipts)
    app = install_intel(work, downloads, reuse)
    verify_installed(root, app, source, batch, signed, reuse)
    # The original four native scenarios are revalidated, never replayed or relabeled as reruns.
    reuse.validate_native_proofs(proof['smoke'], proof['fresh_picture_ui'], entries['update_entry'], entries['oldest_launcher_entry'], source, entries['materials_launcher_entry'], entries['materials_oldest_launcher_entry'])
    for name, row in batch['shell_files'].items():
        assert sha(app/'Contents/Resources/app'/name) == row['sha256'], 'Final production launcher changed: '+name
    assert sha(root/'attachment-final-manifests.json') == source['frozen_stage']['sha256']
    reuse.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], timeout=300)
    after = asset_snapshot(reuse.verify_metadata(source), source)
    assert before == after, 'Existing candidate metadata changed during postflight'
    write_json(evidence/'immutable-assets-after.json', after)
    for name, raw in proof['files'].items():
        assert (evidence/name).read_bytes() == raw, 'Original native evidence changed: '+name
    postflight = dict(passed=True, source_artifact_sha256=COMPLETE_SOURCE['sha256'],
                      signed_stage_sha256=source['frozen_stage']['sha256'], production_launcher_files_verified=24,
                      production_codesign_deep_strict_passed=True, immutable_assets_verified=76,
                      public_installer_files_verified=5, signed_runtime_manifests_verified=45,
                      installation_scope='Anonymous final Intel7 split-image bytes mounted and copied into a new temporary App; completed native scenarios were not rerun')
    provenance = dict(verification_run=run_id, workflow_commit=head,
                      source_native_run=COMPLETE_SOURCE['run_id'], source_native_job=COMPLETE_SOURCE['job_id'],
                      source_native_workflow_commit=COMPLETE_SOURCE['workflow_commit'], postcheck_run=run_id,
                      postcheck_workflow_commit=head, complete_native_execution=COMPLETE_SOURCE,
                      original_failed_run=source['original_native_run'], original_failed_job=source['original_failed_job'],
                      original_stage_run=source['original_native_run'], original_stage_workflow_commit=source['original_native_workflow_commit'],
                      frozen_stage_sha256=source['frozen_stage']['sha256'], reuse_lock_file=SOURCE_LOCK,
                      reuse_lock_sha256=SOURCE_LOCK_SHA, finalization_lock_file=FINALIZATION_LOCK,
                      finalization_lock_sha256=sha(root/FINALIZATION_LOCK), bridge_rebuilt=False,
                      installers_repackaged=False, existing_assets_overwritten=False, fresh_smoke_rerun=False,
                      proxy_smoke_rerun=False, oldest_and_current_ipc_rerun=False, fresh_picture_ui_rerun=False,
                      materials_both_variants_rerun=False, complete_native_records_reverified=True,
                      production_launcher_byte_identical=True, existing_asset_metadata_before_after_unchanged=True,
                      final_postchecks_completed=True)
    complete.validate_finalized_provenance(source, provenance, final)
    preparation = [dict(file=name, **{k:value[k] for k in ['elapsed_ms', 'within_original_5s', 'total_preparation_ms']})
                   for name, raw in proof['files'].items() if name.endswith('.math-before.json')
                   for value in [json.loads(raw)]]
    assert len(preparation) == 4
    report = dict(target='macos-x64', input_release=source['candidate_tag'], input_release_id=release['id'],
                  release=batch['tag'], launcher_build=batch['launcher_build'], core_commit=source['source_commit'],
                  downloaded_from_public_github=True, download_files=receipts, native_install='passed',
                  native_smoke=proof['smoke'], fresh_picture_ui=proof['fresh_picture_ui'], network=proof['network'],
                  launcher_tests=proof['launcher_tests'], **entries,
                  launcher_migration=dict(from_published_launcher='oldest-launcher-src frozen on original candidate branch', signed_core_carrier=entries['oldest_launcher_entry']['signed_launcher_restarted']),
                  shell_files=batch['shell_files'], full_files=[dict(file=r['name'], bytes=r['bytes'], sha256=r['sha256']) for r in source['candidate_files']],
                  real_keys_used=False, real_learning_records_modified=False, provenance=provenance, native_postflight=postflight,
                  pre_update_read_only_math_preparation=preparation, model_answer_speed_tested=False)
    write_json(evidence/'postflight-checks.json', postflight)
    write_json(evidence/'verified.json', report)
    public = evidence/'verification-macos-x64.json'; write_json(public, report)
    reuse.upload_new(source['candidate_tag'], public, 'macos-x64')
    print('PASS: exact completed Intel7 native evidence revalidated and missing final postchecks performed; no native scenarios repeated')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    root = Path.cwd()
    if args.validate_only:
        preflight(root)
        print('PASS: owner-frozen Intel7 postflight inputs; no network, mounting or writes performed')
    else:
        finalize(root)


if __name__ == '__main__':
    main()
