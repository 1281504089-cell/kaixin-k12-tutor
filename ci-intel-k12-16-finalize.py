"""Bind the four actual Intel upgrade receipts to the one frozen candidate."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

REPO = '1281504089-cell/kaixin-k12-tutor'
TARGET = 'macos-x64'
TAG = 'student-20261117-k12-16'
PREFIX = 'codex/k12-intel-reverify-20261117-16-'
NATIVE_LOCK = 'fresh-install-lock.json'
SCENE_LOCK = 'intel-k12-16-scene-lock.json'
SCENES = {
    'oldest': ('oldest_launcher_entry', 'oldest-update-entry.json'),
    'current': ('update_entry', 'update-entry.json'),
    'materials': ('materials_launcher_entry', 'materials-update-entry.json'),
    'materials-oldest': ('materials_oldest_launcher_entry', 'materials-oldest-update-entry.json'),
}
SIDECARS = {
    'library-bulk.json': 'library_bulk_upload', 'chat-audio.json': 'chat_audio',
    'native-science.json': 'science_formulas', 'quick-preview.json': 'quick_preview',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)])


def api(path):
    return json.loads(gh('api', f'repos/{REPO}/{path}'))


def read_scene(scene, source, native_hash, batch):
    run = api(f'actions/runs/{source["run_id"]}')
    job = api(f'actions/jobs/{source["job_id"]}')
    asset = api(f'actions/artifacts/{source["artifact_id"]}')
    reused = scene == 'oldest'
    branch = 'codex/k12-mac-reverify-20261117-16-viewport' if reused else PREFIX + scene
    assert run['status'] == job['status'] == 'completed'
    assert run['head_branch'] == branch and run['head_sha'] == job['head_sha'] == source['workflow_commit']
    assert job['run_id'] == source['run_id'] and job['name'].startswith('native (macos-x64,')
    assert job['conclusion'] == ('failure' if reused else 'success')
    assert asset['name'] == 'attachments-macos-x64' and not asset['expired']
    assert asset['workflow_run']['id'] == source['run_id']
    assert asset['size_in_bytes'] == source['artifact_bytes'] and asset['digest'] == 'sha256:' + source['artifact_sha256']
    raw = gh('api', f'repos/{REPO}/actions/artifacts/{asset["id"]}/zip')
    assert len(raw) == source['artifact_bytes'] and sha(raw) == source['artifact_sha256']
    archive = ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    assert len(names) == len(set(names))
    if not reused:
        assert json.loads(archive.read('scene-verified.json')) == {
            'passed': True, 'scene': scene, 'target': TARGET, 'tag': TAG, 'core_commit': batch['core_commit'],
            'launcher_build': batch['launcher_build'], 'verification_run': source['run_id'],
            'workflow_commit': source['workflow_commit'], 'reuse_lock_sha256': native_hash,
            'production_launcher_unchanged': True,
        }
    field, filename = SCENES[scene]
    raw_entry = archive.read(filename)
    assert source['entry_sha256'] == sha(raw_entry)
    entry = json.loads(raw_entry)
    assert entry['native_platform'] == 'darwin' and entry['native_arch'] == 'x64'
    assert entry['to_launcher'] == batch['launcher_build'] and '-k12-16-' in entry['to_runtime']
    assert entry['actual_download_install_backup_restart'] == 'passed' and entry['check_again_current']
    if scene in ('oldest', 'materials-oldest'):
        assert entry['selected_archive'] == 'kaixin-bridge-20261117-k12-16-macos-x64.tar.gz'
        assert entry['selected_base_runtime'] is None and entry['signed_launcher_restarted']
    else:
        assert entry['selected_archive'] == 'kaixin-core-20261117-k12-16.tar.gz'
        assert entry['selected_base_runtime'], 'The matching installed native base was not used'
    assert all(entry[key] for key in ('chat_preserved', 'task_preserved', 'saved_key_preserved'))
    assert entry['k12_library']['passed'] and entry['quick_preview']['passed'] and entry['science_formulas']['passed']
    return archive, field, raw_entry


def main():
    root = Path.cwd()
    assert os.environ['GITHUB_REF_NAME'] == PREFIX + 'finalize'
    assert api('releases/latest')['id'] == 451537387
    candidate = api('releases/tags/' + TAG)
    assert candidate['id'] == 452304274 and candidate['prerelease'] and not candidate['draft']
    batch = json.loads((root/'attachment-batch.json').read_bytes())
    native_raw = (root/NATIVE_LOCK).read_bytes()
    freeze = json.loads(native_raw)
    raw = (root/SCENE_LOCK).read_bytes()
    lock = json.loads(raw)
    native_hash = sha(native_raw)
    assert lock['tag'] == freeze['tag'] == batch['tag'] == TAG
    assert lock['source_commit'] == freeze['core_commit'] == batch['core_commit']
    assert lock['native_lock_sha256'] == native_hash
    assert set(lock['sources']) == set(SCENES)
    assert len({r['run_id'] for r in lock['sources'].values()}) == len(SCENES)
    from ci_repackage import validate_reuse_lock
    validate_reuse_lock(freeze, batch, candidate, TARGET)
    with ThreadPoolExecutor(max_workers=4) as pool:
        archives = dict(zip(SCENES, pool.map(lambda scene: read_scene(scene, lock['sources'][scene], native_hash, batch), SCENES)))
    final_archive = archives['materials-oldest'][0]
    evidence = root/'fresh-evidence'/TARGET
    evidence.mkdir(parents=True)
    common = ['app.json', 'attachments.json', 'downloads.json', 'network.json', 'launcher-tests.json', 'picture-fresh-ui.json']
    screenshots = ['quick-preview-'+view+'.png' for view in ('390x844', '844x390', '1366x900', '1920x1080')]
    for name in common + screenshots + list(SIDECARS):
        (evidence/name).write_bytes(final_archive.read(name))
    entries = {}
    for scene, (_, field, raw_entry) in archives.items():
        (evidence/SCENES[scene][1]).write_bytes(raw_entry)
        entries[field] = json.loads(raw_entry)
    for name, key in SIDECARS.items():
        assert json.loads(final_archive.read(name)) == entries['materials_oldest_launcher_entry'][key]
    (evidence/SCENE_LOCK).write_bytes(raw)
    fresh = json.loads(final_archive.read('picture-fresh-ui.json'))
    assert fresh['desktop_citation']['passed'] and fresh['desktop_citation']['pdf']['initialPage'] == 3
    reused = freeze['reuse_existing_native']
    report = {
        'target': TARGET, 'input_release': TAG, 'input_release_id': candidate['id'], 'release': TAG,
        'launcher_build': batch['launcher_build'], 'core_commit': batch['core_commit'],
        'downloaded_from_public_github': True, 'download_files': json.loads(final_archive.read('downloads.json')),
        'native_install': 'passed', 'native_smoke': json.loads(final_archive.read('app.json')),
        'network': json.loads(final_archive.read('network.json')), 'launcher_tests': json.loads(final_archive.read('launcher-tests.json')),
        'fresh_picture_ui': fresh, **entries, 'shell_files': batch['shell_files'],
        'launcher_migration': {'from_published_launcher': TAG, 'signed_core_carrier': entries['oldest_launcher_entry']['signed_launcher_restarted']},
        'full_files': sorted([{'file': row['name'], 'bytes': row['bytes'], 'sha256': row['sha256']} for row in freeze['targets'][TARGET]['files']], key=lambda row: row['file']),
        'installer_reuse': {'enabled': True, 'original_packaging_run': reused['original_native_run'], 'installers_repackaged': False, 'existing_installer_assets_overwritten': False},
        'real_keys_used': False, 'real_learning_records_modified': False,
        'provenance': {
            'reuse_lock_file': NATIVE_LOCK, 'reuse_lock_sha256': native_hash,
            'original_stage_run': reused['original_native_run'], 'original_stage_workflow_commit': reused['original_native_workflow_commit'],
            'original_native_job': reused['original_jobs'][TARGET], 'frozen_stage_sha256': reused['frozen_stage_sha256'],
            'verification_run': int(os.environ['GITHUB_RUN_ID']), 'workflow_commit': os.environ['GITHUB_SHA'],
            'bridge_rebuilt': False, 'installers_repackaged': False, 'existing_assets_overwritten': False,
            'fresh_smoke_rerun': True, 'proxy_smoke_rerun': True, 'oldest_and_current_ipc_rerun': False,
            'materials_both_variants_rerun': True, 'fresh_picture_ui_rerun': True,
            'intel_scene_lock_sha256': sha(raw), 'intel_scene_sources': lock['sources'],
        },
    }
    raw_report = json.dumps(report, ensure_ascii=False, indent=2)
    (evidence/'verified.json').write_text(raw_report)
    public = evidence/f'verification-{TARGET}.json'
    public.write_text(raw_report)
    gh('release', 'upload', TAG, public)
    print('PASS: exact Intel fresh installation and all four real upgrade receipts')


if __name__ == '__main__':
    main()
