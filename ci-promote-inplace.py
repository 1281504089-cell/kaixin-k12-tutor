"""Promote only a locally signed and fully native-validated batch."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path.cwd()
TAG = 'student-20261113-sync2'
BATCH = json.loads((ROOT / 'online-update-manifests.json').read_text())


def run(argv, cwd=ROOT):
    subprocess.run([str(x) for x in argv], cwd=cwd, check=True)


def sha(file):
    result = hashlib.sha256()
    with Path(file).open('rb') as stream:
        while data := stream.read(8 * 1024 ** 2):
            result.update(data)
    return result.hexdigest()


workflow = json.loads(subprocess.check_output(['gh', 'api', f'repos/1281504089-cell/kaixin-k12-tutor/actions/runs/{BATCH["validation_run_id"]}']))
assert workflow['status'] == 'completed' and workflow['conclusion'] == 'success'
assert workflow['head_sha'] == BATCH['validation_head_sha']
run(['python', 'bootstrap_source.py', '--with-updates'])
source = ROOT / 'student-source'
run(['git', 'apply', '--check', ROOT / 'desktop-inplace-sync2.patch'], source)
run(['git', 'apply', ROOT / 'desktop-inplace-sync2.patch'], source)
promotion = ROOT / 'promotion'
native = ROOT / 'native-results'
offline = ROOT / 'release-r2'
for directory in (promotion, native, offline):
    directory.mkdir()
previous = ROOT / 'current-feeds'
previous.mkdir()
for target in BATCH['reports']:
    run(['gh', 'release', 'download', 'core-updates', '--dir', previous, '--pattern', f'runtime-{target}.json'])
for name, manifest in BATCH['manifests'].items():
    (promotion / name).write_text(json.dumps(manifest, indent=2) + '\n')
    if name.count('-') == 2:  # Fixed feeds are named runtime-<platform>-<arch>.json.
        run(['gh', 'release', 'download', TAG, '--dir', promotion, '--pattern', manifest['archive']])
for target, expected in BATCH['reports'].items():
    run(['gh', 'release', 'download', TAG, '--dir', native, '--pattern', f'verification-{target}.json'])
    assert json.loads((native / f'verification-{target}.json').read_text()) == expected
core = json.loads((ROOT / 'ci-core-release.json').read_text())['core']
run(['gh', 'release', 'download', 'core-updates', '--dir', promotion, '--pattern', core['archive']])
assert sha(promotion / core['archive']) == core['sha256']
run(['node', 'ci-verify-promotion.mjs'])
backups = []
for target in BATCH['reports']:
    file = previous / f'previous-runtime-{target}.json'
    shutil.copyfile(previous / f'runtime-{target}.json', file)
    backups.append(file)
shutil.copyfile(promotion / core['archive'], offline / core['archive'])
for target in BATCH['reports']:
    shutil.copyfile(promotion / f'runtime-{target}-20261112.json', offline / f'runtime-{target}.json')
    shutil.copyfile(promotion / f'runtime-{target}-early.json', offline / f'runtime-{target}-early.json')
run(['python', 'package_offline.py'])
small_updates = list((ROOT / '本地更新包').glob('*.zip'))
assert len(small_updates) == 3
downloads = ROOT / 'release-downloads'
downloads.mkdir()
labels = {'windows-x64': 'Windows', 'macos-x64': 'Mac-Intel', 'macos-arm64': 'Mac-Apple'}
for row in json.loads((ROOT / 'OFFLINE_PACKAGES.json').read_text()):
    shutil.copyfile(row['path'], downloads / f'Kaixin-{labels[row["target"]]}-Update-20261113.zip')
shutil.copyfile(ROOT / '本地更新包/先看更新步骤.txt', downloads / 'OFFLINE-UPDATE-20261113.txt')
shutil.copyfile(ROOT / '安装步骤.txt', downloads / 'INSTALL-20261113.txt')
run(['gh', 'release', 'upload', TAG, *downloads.iterdir(), *backups, '--clobber'])
archives = [promotion / m['archive'] for m in BATCH['manifests'].values()]
qualified = [promotion / name for name in BATCH['manifests'] if name not in {f'runtime-{t}.json' for t in BATCH['reports']}]
run(['gh', 'release', 'upload', 'core-updates', *sorted(set(archives)), *qualified, '--clobber'])
for target in BATCH['reports']:
    run(['gh', 'release', 'upload', 'core-updates', promotion / f'runtime-{target}.json', '--clobber'])
run(['gh', 'release', 'edit', TAG, '--prerelease=false', '--latest', '--title', '开心动力超级学霸 · 三系统完整安装与原地更新 · 2026-11-13', '--notes-file', ROOT / '安装步骤.txt'])
print('PASS: validated full installers and all three matching production update feeds published.')
