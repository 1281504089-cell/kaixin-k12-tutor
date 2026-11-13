"""Publish the candidate only after all native final-package checks passed."""
import json
from pathlib import Path
import subprocess

batch = json.loads(Path('fetchfix-batch.json').read_text())
repo = '1281504089-cell/kaixin-k12-tutor'
baseline = json.loads(Path('fresh-install-lock.json').read_text())
latest = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/releases/latest']))
assert latest['id'] == baseline['release_id'], 'Another full release became latest; review it before promotion'
release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/releases/tags/{batch["tag"]}']))
assert release['prerelease'] is True and release['draft'] is False
assets = {row['name']: row for row in release['assets']}
out = Path('promotion-proof')
out.mkdir()
for target, manifest in batch['manifests'].items():
    name = 'verification-' + target + '.json'
    subprocess.run(['gh', 'release', 'download', batch['tag'], '--dir', str(out), '--pattern', name], check=True)
    proof = json.loads((out / name).read_text())
    assert proof['core_commit'] == batch['core_commit'] and proof['shell_files'] == batch['shell_files']
    assert proof['native_install'] == 'passed' and proof['launcher_build'] == batch['launcher_build']
    smoke = proof['native_smoke']
    assert smoke['native_platform'] == manifest['platform'] and smoke['native_arch'] == manifest['arch']
    assert smoke['textbooks'] == 136 and smoke['pdf']['pdf_files'] == 136
    assert smoke['current_core_included'] is True and smoke['fresh_profile'] is True
    assert smoke['automatic_small_update_download'] == 'passed'
    assert smoke['compatibility_runtime_downloaded'] is False
    assert proof['network']['proxy_used'] is True and proof['network']['api_fallback_download'] == 'passed'
    assert proof['network']['direct_fetch_failed'] is True
    assert proof['real_keys_used'] is False and proof['real_learning_records_modified'] is False
    assert len(proof['full_files']) == (5 if target == 'windows-x64' else 4)
    for file in proof['full_files']:
        actual = assets[file['file']]
        assert actual['size'] == file['bytes'] and actual['digest'] == 'sha256:' + file['sha256']
subprocess.run(['gh', 'release', 'edit', batch['tag'], '--prerelease=false', '--latest',
                '--title', '开心动力超级学霸 · 三系统完整安装与下载修复 · 2026-11-14',
                '--notes-file', 'FETCHFIX-INSTALL.txt'], check=True)
print('PASS: all three final installers, 136 PDFs, proxy and fetch-failure fallback; latest release promoted.')
