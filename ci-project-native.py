"""Native validation and packaging; no production private signing key is available here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--target', required=True)
args = parser.parse_args()
ROOT = Path.cwd()
CONFIG = json.loads((ROOT / 'project-core-release.json').read_text())
TARGET = args.target
TAG = 'student-20261114-projects'


def run(argv, cwd=ROOT, env=None):
    command = [str(x) for x in argv]
    if os.name == 'nt' and command[0] == 'npm':
        command[0] = 'npm.cmd'
    subprocess.run(command, cwd=cwd, env=env, check=True)


def digest(file):
    value = hashlib.sha256()
    with Path(file).open('rb') as stream:
        while data := stream.read(8 * 1024 ** 2):
            value.update(data)
    return value.hexdigest()


run(['python', 'bootstrap_source.py', '--with-updates'])
SOURCE = ROOT / 'student-source'
DESKTOP = SOURCE / 'apps/desktop'
assert digest(ROOT / 'desktop-inplace-sync2.patch') == CONFIG['desktop_patch_sha256']
run(['git', 'init', '--quiet'], SOURCE)
run(['git', 'apply', '--check', ROOT / 'desktop-inplace-sync2.patch'], SOURCE)
run(['git', 'apply', ROOT / 'desktop-inplace-sync2.patch'], SOURCE)
assert digest(ROOT / 'project-history.patch') == CONFIG['project_patch_sha256']
run(['git', 'apply', '--check', ROOT / 'project-history.patch'], SOURCE)
run(['git', 'apply', ROOT / 'project-history.patch'], SOURCE)
shutil.copyfile(ROOT / 'delivery-runtime-public.pem', DESKTOP / 'assets/runtime-public.pem')
for name, expected in CONFIG['desktop_files'].items():
    assert digest(DESKTOP / name) == expected, 'Desktop source mismatch: ' + name
run(['npm', 'ci'], DESKTOP)
run(['npm', 'test'], DESKTOP)

local = DESKTOP / '.local' / TARGET
seed = local / 'seed'
update = local / 'update'
native = local / 'runtime'
inbox = ROOT / ('inputs-' + TARGET)
out = ROOT / ('validated-' + TARGET)
for directory in (seed, update, native, inbox, out):
    directory.mkdir(parents=True, exist_ok=True)
payload_tag = json.loads((ROOT / 'delivery-payloads.json').read_text())[TARGET]
run(['gh', 'release', 'download', payload_tag, '--dir', inbox, '--pattern', 'parts.json', '--pattern', '*.tar.gz.*'])
manifest = json.loads((ROOT / ('delivery-signed-' + TARGET + '.json')).read_text())
(seed / 'runtime.json').write_text(json.dumps(manifest))
run(['node', '--input-type=module', '-e', "import{readFile}from'node:fs/promises';import{verifyManifest}from'./src/bundles.mjs';verifyManifest(JSON.parse(await readFile(process.argv[1])),await readFile('assets/runtime-public.pem'));", seed / 'runtime.json'], DESKTOP)
parts = json.loads((inbox / 'parts.json').read_text())['parts']
base_archive = seed / manifest['archive']
with base_archive.open('wb') as output:
    for part in parts:
        file = inbox / part['file']
        assert file.stat().st_size == part['bytes'] and digest(file) == part['sha256']
        with file.open('rb') as stream:
            shutil.copyfileobj(stream, output, 8 * 1024 ** 2)
        file.unlink()
assert digest(base_archive) == manifest['sha256']
with tarfile.open(base_archive) as archive:
    archive.extractall(native, filter='data')
core = CONFIG['core']
run(['gh', 'release', 'download', 'core-updates', '--dir', update, '--pattern', core['archive']])
assert digest(update / core['archive']) == core['sha256']
(update / 'runtime.json').write_text(json.dumps(CONFIG['thin'][TARGET], indent=2))

home = ROOT / 'existing-student-test'
run(['node', 'ci-probe-runtime.mjs', 'seed', native, home, seed / 'runtime.json', out / 'before-update.json'])
shutil.rmtree(native / 'core')
deps = local / 'native-web-dependencies'
(native / 'web/node_modules').rename(deps)
shutil.rmtree(native / 'web')
with tarfile.open(update / core['archive']) as archive:
    archive.extractall(native, filter='data')
deps.rename(native / 'web/node_modules')
bridge_name = 'kaixin-bridge-20261114-projects-' + TARGET + '.tar.gz'
bridge = out / bridge_name
with tarfile.open(bridge, 'w:gz', compresslevel=6) as archive:
    for file in sorted(native.iterdir()):
        if file.name not in {'student-seed', 'SOURCE.tar.gz', 'installed.json'}:
            archive.add(file, arcname=file.name)
assert bridge.stat().st_size < 2 * 1024 ** 3, 'The existing updater cannot accept a bridge of 2GiB or larger'
unsigned = {'formatVersion': 1, 'protocolVersion': 1, 'platform': manifest['platform'], 'arch': manifest['arch'],
            'runtimeId': '1.7.1-kaixin-20261114-projects-' + TARGET + '-universal', 'coreVersion': '1.7.1',
            'commit': CONFIG['source_commit'], 'builtAt': CONFIG['builtAt'], 'archive': bridge_name,
            'sha256': digest(bridge), 'corePayloadSha256': core['sha256'],
            'compatibleBaseManifests': [
                {'baseRuntimeId': CONFIG['thin'][TARGET]['baseRuntimeId'], 'file': 'runtime-' + TARGET + '-20261112.json'},
                {'baseRuntimeId': CONFIG['legacy'][TARGET]['baseRuntimeId'], 'file': 'runtime-' + TARGET + '-early.json'},
                *CONFIG['additionalBases'][TARGET]]}
unsigned_file = out / ('runtime-' + TARGET + '.unsigned.json')
unsigned_file.write_text(json.dumps(unsigned, indent=2) + '\n')
run(['node', 'ci-probe-runtime.mjs', 'bridge', native, home, unsigned_file, out / 'bridge-native.json'])
shutil.rmtree(home)
shutil.rmtree(native)
run(['node', 'scripts/smoke.mjs', '--target', TARGET], DESKTOP)

electron = "import{downloadArtifact}from'@electron/get';import{readFile,mkdir,copyFile}from'node:fs/promises';import path from'node:path';const v=JSON.parse(await readFile('package.json')).devDependencies.electron;const z=await downloadArtifact({version:v,platform:process.platform,arch:process.arch,artifactName:'electron'});await mkdir('.local/tooling/downloads',{recursive:true});await copyFile(z,path.join('.local/tooling/downloads',`electron-v${v}-${process.platform}-${process.arch}.zip`));"
run(['node', '--input-type=module', '-e', electron], DESKTOP)
environment = {**os.environ, 'KX_CONSUME_CI_INPUTS': '1'}
run(['node', 'scripts/package.mjs', '--target', TARGET], DESKTOP, environment)
if TARGET == 'windows-x64':
    base_archive.unlink(missing_ok=True)
    run(['pwsh', '-NoProfile', '-NonInteractive', '-File', 'platforms/windows-x64/smoke-installer.ps1'], DESKTOP)
else:
    # The existing native app smoke starts the actual packaged app and checks 136 books and Chinese.
    run(['node', ROOT / 'ci-smoke-mac.mjs', '--target', TARGET], SOURCE)
full_files = [p for p in (DESKTOP / 'out').iterdir() if p.is_file() and
              (p.suffix in {'.dmg', '.dmgpart'} or p.name.endswith('-Setup.exe') or '-Runtime.' in p.name)]
assert full_files and all(p.stat().st_size < 2 * 1024 ** 3 for p in full_files)
report = {'target': TARGET, 'project_patch_sha256': CONFIG['project_patch_sha256'], 'core_source_commit': CONFIG['source_commit'], 'desktop_patch_sha256': CONFIG['desktop_patch_sha256'],
          'base_archive_sha256': manifest['sha256'], 'core_payload_sha256': core['sha256'],
          'bridge': {'file': bridge_name, 'sha256': unsigned['sha256'], 'bytes': bridge.stat().st_size},
          'native_bridge': json.loads((out / 'bridge-native.json').read_text()),
          'fresh_full_installer': 'passed', 'real_api_keys_used': False,
          'full_files': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in full_files]}
report_file = out / ('verification-' + TARGET + '.json')
report_file.write_text(json.dumps(report, indent=2) + '\n')
run(['gh', 'release', 'upload', TAG, bridge, unsigned_file, report_file, *full_files, '--clobber'])
print(json.dumps({'target': TARGET, 'native_validation': 'passed', 'full_installer': 'passed'}))
