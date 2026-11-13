"""Verify anonymous GitHub downloads and a fresh native installation of the pinned release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--target', required=True, choices=['macos-x64', 'macos-arm64', 'windows-x64'])
args = parser.parse_args()
root = Path.cwd()
lock = json.loads((root / 'fresh-install-lock.json').read_text())
target = args.target
expected = lock['targets'][target]
work = root / ('fresh-' + target)
downloads = work / 'downloads'
evidence = root / 'fresh-evidence' / target
downloads.mkdir(parents=True)
evidence.mkdir(parents=True)


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, **kwargs)


def sha(file):
    digest = hashlib.sha256()
    with file.open('rb') as stream:
        while chunk := stream.read(8 * 1024**2):
            digest.update(chunk)
    return digest.hexdigest()


def release_metadata():
    return json.loads(subprocess.check_output([
        'gh', 'api', 'repos/1281504089-cell/kaixin-k12-tutor/releases/latest'
    ]))


release = release_metadata()
assert release['id'] == lock['release_id'] and release['tag_name'] == lock['tag']
assert release['draft'] is False and release['prerelease'] is False
assets = {row['name']: row for row in release['assets']}
download_rows = []
for file in expected['files']:
    asset = assets[file['name']]
    assert asset['size'] == file['bytes'] and asset['digest'] == 'sha256:' + file['sha256']
    destination = downloads / file['name']
    # Do not send a GitHub token: new users must be able to download publicly.
    routes = [asset['browser_download_url'], asset['url'] + '?verify=' + str(time.time_ns())]
    errors = []
    for url in routes:
        temporary = destination.with_name(destination.name + '.partial')
        try:
            request = Request(url, headers={'User-Agent': 'Kaixin-Fresh-Install-Verification',
                                           'Accept': 'application/octet-stream'})
            with urlopen(request, timeout=60) as response, temporary.open('xb') as output:
                assert response.geturl().startswith(('https://github.com/', 'https://release-assets.githubusercontent.com/',
                                                     'https://objects.githubusercontent.com/', 'https://api.github.com/'))
                shutil.copyfileobj(response, output, 8 * 1024**2)
            assert temporary.stat().st_size == file['bytes'] and sha(temporary) == file['sha256']
            temporary.rename(destination)
            download_rows.append({**file, 'anonymous_download': True, 'sha256_verified': True})
            print('Verified public download: ' + file['name'], flush=True)
            break
        except Exception as error:
            temporary.unlink(missing_ok=True)
            errors.append(type(error).__name__ + ': ' + str(error))
    else:
        raise RuntimeError('Both public download routes failed for ' + file['name'] + ': ' + '; '.join(errors))

(evidence / 'downloads.json').write_text(json.dumps(download_rows, indent=2))
install = work / 'installed app'
install.mkdir()
if target.startswith('macos-'):
    image = next(downloads.glob('*-part.dmg'))
    run(['/usr/bin/hdiutil', 'verify', image], timeout=300)
    mount = work / 'mount'
    mount.mkdir()
    attached = False
    try:
        run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen',
             '-mountpoint', mount, image], timeout=300)
        attached = True
        app = install / '开心动力超级学霸.app'
        run(['/usr/bin/ditto', mount / app.name, app])
    finally:
        if attached:
            run(['/usr/bin/hdiutil', 'detach', mount])
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    resources = app / 'Contents/Resources'
    executable = app / 'Contents/MacOS/开心动力超级学霸'
else:
    installer = next(downloads.glob('*-Setup.exe'))
    # NSIS requires its final /D argument to stay unquoted, including spaces.
    setup = subprocess.run('"' + str(installer) + '" /S /D=' + str(install), timeout=900)
    assert setup.returncode == 0, 'Windows installer failed'
    resources = install / 'resources'
    executable = install / '开心动力超级学霸.exe'

assert executable.is_file()
base = json.loads((resources / 'seed/runtime.json').read_text())
included = json.loads((resources / 'update/runtime.json').read_text())
assert base['runtimeId'] == expected['base_runtime_id']
assert included['runtimeId'] == expected['runtime_id']
assert included['baseRuntimeId'] == base['runtimeId']
assert included['commit'] == lock['core_commit'] and included['sha256'] == lock['core_sha256']
from ci_repackage import prepare_candidate
candidate_out, batch = prepare_candidate(root, target, install, resources, downloads, evidence, lock)
included = json.loads((resources / 'update/runtime.json').read_text())
assert included == batch['manifests'][target]
environment = {**os.environ, 'KX_EXPECTED_PLATFORM': expected['platform'], 'KX_EXPECTED_ARCH': expected['arch']}
run(['node', 'ci-fresh-smoke.mjs', executable, resources, work / '全新学习目录', evidence], env=environment, timeout=1100)
after = release_metadata()
assert after['id'] == lock['release_id'], 'Latest release changed during validation'
for file in expected['files']:
    actual = next(row for row in after['assets'] if row['name'] == file['name'])
    assert actual['digest'] == 'sha256:' + file['sha256'] and actual['size'] == file['bytes']
report = {'target': target, 'input_release': lock['tag'], 'input_release_id': lock['release_id'],
          'release': batch['tag'], 'launcher_build': batch['launcher_build'],
          'core_commit': batch['core_commit'], 'downloaded_from_public_github': True,
          'download_files': download_rows, 'native_install': 'passed',
          'native_smoke': json.loads((evidence / 'app.json').read_text()),
          'network': json.loads((evidence / 'network.json').read_text()),
          'shell_files': batch['shell_files'],
          'full_files': [{'file': file.name, 'bytes': file.stat().st_size, 'sha256': sha(file)} for file in sorted(candidate_out.iterdir())],
          'real_keys_used': False, 'real_learning_records_modified': False}
(evidence / 'verified.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
report_file = evidence / ('verification-' + target + '.json')
report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2))
run(['gh', 'release', 'upload', batch['tag'], report_file, *candidate_out.iterdir(), '--clobber'])
print('PASS: public download, native fresh install and included latest core: ' + target, flush=True)
