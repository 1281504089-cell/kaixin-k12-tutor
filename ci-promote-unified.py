"""Promote one fully verified desktop batch; production signing happens locally."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path.cwd()
REPO = '1281504089-cell/kaixin-k12-tutor'
batch = json.loads((ROOT / 'unified-publication.json').read_text())
targets = ['windows-x64', 'macos-x64', 'macos-arm64']


def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)])


def api(path):
    return json.loads(gh('api', 'repos/' + REPO + '/' + path))


def digest(file):
    h = hashlib.sha256()
    with file.open('rb') as stream:
        while data := stream.read(8 * 1024**2):
            h.update(data)
    return h.hexdigest()


def public(asset):
    for url in [asset['browser_download_url'], asset['url'] + '?readback=' + str(time.time_ns())]:
        try:
            raw = urlopen(Request(url, headers={'User-Agent': 'Kaixin-Publication-Readback',
                          'Accept': 'application/octet-stream'}), timeout=60).read()
            assert hashlib.sha256(raw).hexdigest() == asset['digest'].split(':')[1]
            return raw
        except Exception as error:
            last = error
    raise last


for target, proof in batch['native_runs'].items():
    run = api('actions/runs/' + str(proof['run_id']))
    assert run['status'] == 'completed' and run['head_sha'] == proof['workflow_commit']
    jobs = api('actions/runs/' + str(proof['run_id']) + '/jobs')['jobs']
    assert any(j['conclusion'] == 'success' and j['name'].startswith('native (' + target + ',') for j in jobs)
assert set(batch['native_runs']) == set(targets)
upstream = api('actions/runs/' + str(batch['upstream_native_run']))
assert upstream['conclusion'] == 'success'
assert api('releases/latest')['id'] == batch['expected_latest_release_id']
candidate = api('releases/tags/' + batch['tag'])
assert candidate['prerelease'] and not candidate['draft']
assets = {a['name']: a for a in candidate['assets']}
proofs, full_files, migrations = {}, [], []
for target in targets:
    report = json.loads(public(assets['verification-' + target + '.json']))
    assert report['release'] == batch['tag'] and report['launcher_build'] == batch['launcher_build']
    assert report['core_commit'] == batch['core_commit'] and report['native_install'] == 'passed'
    assert report['shell_files'] == json.loads((ROOT / 'fetchfix-batch.json').read_text())['shell_files']
    assert report['network']['direct_fetch_failed'] and report['network']['proxy_connections'] > 0
    assert report['native_smoke']['current_core_included'] and report['native_smoke']['pdf']['pdf_files'] == 136
    assert len(report['native_smoke']['local_spoken_stt']) == 2
    assert all(row['spoken_audio_decoded'] for row in report['native_smoke']['local_spoken_stt'])
    update = report['update_entry']
    assert update['actual_download_install_backup_restart'] == 'passed' and update['check_again_current']
    assert all(update[k] for k in ['chat_preserved', 'task_preserved', 'saved_key_preserved'])
    migration = report['launcher_migration']
    assert migration['nativeMigration'] == 'passed' and migration['data_preservation']['passed']
    assert migration['originalSeedMetadataUnchanged'] and not migration['runtimeArchivesIncluded']
    for row in [*report['full_files'], {'file': migration['artifact'], 'bytes': migration['size'], 'sha256': migration['sha256']}]:
        actual = assets[row['file']]
        assert actual['digest'] == 'sha256:' + row['sha256'] and actual['size'] == row['bytes']
    proofs[target] = report
    full_files += report['full_files']
    migrations.append({'file': migration['artifact'], 'bytes': migration['size'], 'sha256': migration['sha256']})
assert len(full_files) == 13 and len(migrations) == 3

work = ROOT / 'publication-work'
work.mkdir()
stable = api('releases/tags/core-updates')
stable_assets = {a['name']: a for a in stable['assets']}
backups = work / 'previous'
backups.mkdir()
for name, expected in batch['expected_previous'].items():
    actual = stable_assets[name]
    assert actual['digest'] == 'sha256:' + expected, 'Live update feed changed: ' + name
    raw = public(actual)
    (backups / name).write_bytes(raw)
    retained = work / ('before-unified-' + name)
    retained.write_bytes(raw)
    gh('release', 'upload', batch['tag'], retained, '--clobber')

# Copy verified native bridge bytes before exposing any new default manifest.
for name, row in batch['archives'].items():
    if name in stable_assets:
        assert stable_assets[name]['digest'] == 'sha256:' + row['sha256']
        assert stable_assets[name]['size'] == row['bytes']
        continue
    gh('release', 'download', row['source_tag'], '--pattern', name, '--dir', work)
    file = work / name
    assert file.stat().st_size == row['bytes'] and digest(file) == row['sha256']
    gh('release', 'upload', 'core-updates', file)
    file.unlink()

manifest_dir = ROOT / 'signed-unified'
for name, manifest in batch['manifests'].items():
    assert json.loads((manifest_dir / name).read_text()) == manifest
    if name not in batch['expected_previous']:
        if name in stable_assets:
            assert public(stable_assets[name]) == (manifest_dir / name).read_bytes()
            continue
        gh('release', 'upload', 'core-updates', manifest_dir / name)

switched = []
try:
    current = {a['name']: a for a in api('releases/tags/core-updates')['assets']}
    for name, expected in batch['expected_previous'].items():
        assert current[name]['digest'] == 'sha256:' + expected
        gh('release', 'upload', 'core-updates', manifest_dir / name, '--clobber')
        switched.append(name)
    readback = {a['name']: a for a in api('releases/tags/core-updates')['assets']}
    for name, manifest in batch['manifests'].items():
        assert public(readback[name]) == (manifest_dir / name).read_bytes()
    for name, row in batch['archives'].items():
        assert readback[name]['digest'] == 'sha256:' + row['sha256'] and readback[name]['size'] == row['bytes']
except Exception:
    for name in switched:
        gh('release', 'upload', 'core-updates', backups / name, '--clobber')
    raise

gh('release', 'upload', batch['tag'], ROOT / 'INSTALLATION.txt', '--clobber')
gh('api', '-X', 'PATCH', 'repos/' + REPO + '/git/refs/tags/' + batch['tag'],
   '-f', 'sha=' + os.environ['GITHUB_SHA'], '-F', 'force=true')
gh('release', 'edit', batch['tag'], '--prerelease=false', '--latest=true',
   '--title', '开心动力超级学霸 · 三系统整合版 2026-11-14', '--notes-file', ROOT / 'RELEASE-NOTES.md')
latest = api('releases/latest')
assert latest['tag_name'] == batch['tag'] and not latest['prerelease']
receipt = {**batch, 'published_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'release_repository_commit': os.environ['GITHUB_SHA'],
           'release_id': latest['id'], 'release_url': latest['html_url'],
           'full_files': full_files, 'launcher_migration_files': migrations,
           'previous_manifests': {name: json.loads((backups / name).read_text()) for name in batch['expected_previous']},
           'stable_manifests_read_back': list(batch['manifests']), 'proofs': proofs,
           'physical_user_devices_tested': False, 'private_key_uploaded': False}
receipt_file = ROOT / 'PUBLICATION-RECEIPT.json'
receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
gh('release', 'upload', batch['tag'], receipt_file, '--clobber')
print(json.dumps({'published': True, 'tag': batch['tag'], 'release_id': latest['id'], 'platforms': targets}))
