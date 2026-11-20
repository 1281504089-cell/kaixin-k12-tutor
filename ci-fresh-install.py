"""Stage a rebuilt new-install candidate and test its actual packaged app."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ci_repackage import install_native, prepare_candidate, read, replace_included_core, run, write


REPO = '1281504089-cell/kaixin-k12-tutor'
API = 'https://api.github.com/repos/' + REPO
DOWNLOAD = 'https://github.com/' + REPO + '/releases/download/'
HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com', 'api.github.com'}
MACHINES = {'macos-x64': 'x86_64', 'macos-arm64': 'arm64', 'windows-x64': 'AMD64'}


def checked_url(url):
    parsed = urlsplit(url)
    assert parsed.scheme == 'https' and parsed.hostname in HOSTS
    assert parsed.username is None and parsed.password is None
    return url


class TrustedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, checked_url(newurl))


opener = build_opener(TrustedRedirects())


def digest(file):
    with file.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def fetch(url, accept):
    return opener.open(Request(checked_url(url), headers={
        'User-Agent': 'Kaixin-Fresh-Install-Verification', 'Accept': accept,
    }), timeout=75)


def metadata(tag):
    relative = 'releases/tags/' + quote(tag, safe='')
    if os.environ.get('GH_TOKEN'):
        return json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPO}/{relative}']))
    with fetch(API + '/' + relative, 'application/vnd.github+json') as response:
        return json.load(response)


def locate(release, row):
    asset, = (asset for asset in release['assets'] if asset['name'] == row['name'])
    assert asset['state'] == 'uploaded'
    assert asset['id'] == row['id'] and asset['size'] == row['bytes']
    assert asset['digest'] == 'sha256:' + row['sha256']
    assert asset['browser_download_url'] == DOWNLOAD + release['tag_name'] + '/' + quote(row['name'], safe='')
    assert asset['url'] == API + '/releases/assets/' + str(row['id'])
    return asset


def download(release, row, path):
    asset = locate(release, row)
    temp = path.with_suffix(path.suffix + '.partial')
    failures = []
    started = time.monotonic()
    for url in (asset['browser_download_url'], asset['browser_download_url'], asset['url']):
        try:
            total = 0
            digest = hashlib.sha256()
            with fetch(url + '?fresh=' + str(time.time_ns()), 'application/octet-stream') as response, temp.open('xb') as out:
                assert response.status == 200 and checked_url(response.url)
                while chunk := response.read(4 * 1024 * 1024):
                    total += len(chunk)
                    assert total <= row['bytes']
                    digest.update(chunk)
                    out.write(chunk)
            assert total == row['bytes'] and digest.hexdigest() == row['sha256']
            temp.rename(path)
            print(f'Verified public download: {path.name} ({total} bytes, {time.monotonic() - started:.1f} s)', flush=True)
            return {**row, 'anonymous_download': True, 'sha256_verified': True,
                    'seconds': round(time.monotonic() - started, 3)}
        except (OSError, ValueError, AssertionError) as error:
            temp.unlink(missing_ok=True)
            failures.append(type(error).__name__ + ': ' + str(error).split('?')[0])
    raise RuntimeError(f'Public download failed: {row["name"]}: ' + '; '.join(failures))


def verify_signature(resources, manifest, descriptor):
    script = r'''
import assert from 'node:assert/strict';
import { verify } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const [directory, manifestJson, launcherJson] = process.argv.slice(1);
const { verifyManifest, canonicalManifest } = await import(pathToFileURL(path.join(directory, 'app/src/bundles.mjs')));
const key = readFileSync(path.join(directory, 'app/assets/runtime-public.pem'));
verifyManifest(JSON.parse(readFileSync(path.join(directory, 'seed/runtime.json'))), key);
verifyManifest(JSON.parse(manifestJson), key);
const launcher = JSON.parse(launcherJson);
assert(verify(null, Buffer.from(canonicalManifest(launcher)), key, Buffer.from(launcher.signature, 'base64')));
'''
    run('node', '--input-type=module', '-e', script, resources,
        json.dumps(manifest), json.dumps(descriptor), timeout=60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=MACHINES, required=True)
    parser.add_argument('--inputs', type=Path, default=Path('.'))
    parser.add_argument('--work', type=Path, default=Path('native-work'))
    args = parser.parse_args()
    target = args.target
    assert platform.machine() == MACHINES[target], 'Not a native runner for ' + target
    recipe = Path(__file__).resolve().parent
    inputs = args.inputs.resolve()
    work = args.work.resolve()
    baseline = read(recipe / 'installer-baseline.json')
    batch = read(inputs / 'attachment-batch.json')
    stage = read(inputs / 'online-stage.json')
    descriptor = read(inputs / 'launcher-manifest.json')
    old = baseline['targets'][target]
    manifest = batch['manifests'][target]
    core = batch['core_asset']
    assert baseline['tag'] == 'student-20261117-k12-16'
    assert batch['tag'] == 'student-20261117-k12-18'
    assert batch['launcher_build'] == descriptor['buildId'] == '20261121-updater-8'
    assert stage['proof']['source_commit'] == batch['core_commit'] == descriptor['coreCommit'] == manifest['commit']
    assert manifest['archive'] == core['name']
    assert manifest['sha256'] == core['digest'].removeprefix('sha256:')
    assert manifest['baseRuntimeId'] == old['base_runtime_id'] and manifest['runtimeId'] != old['runtime_id']
    assert (manifest['platform'], manifest['arch']) == (old['platform'], old['arch'])
    pinned_core = {'name': core['name'], 'id': core['id'], 'bytes': core['size'], 'sha256': manifest['sha256']}

    previous = metadata(baseline['tag'])
    assert previous['id'] == baseline['release_id'] and previous['tag_name'] == baseline['tag']
    assert previous['draft'] is False
    candidate = metadata(batch['tag'])
    assert candidate['id'] == stage['release_id'] and candidate['tag_name'] == batch['tag']
    assert candidate['prerelease'] is True and candidate['draft'] is False

    files = work / 'public-baseline'
    evidence = work / 'evidence'
    files.mkdir(parents=True)
    evidence.mkdir()
    download_rows = [download(previous, row, files / row['name']) for row in old['files']]
    core_file = work / pinned_core['name']
    core_readback = download(candidate, pinned_core, core_file)
    write(evidence / 'downloads.json', {'installation': download_rows, 'core': core_readback})

    scratch = work / 'old install'
    resources, executable = install_native(target, files, scratch)
    old_manifest = read(resources / 'update/runtime.json')
    assert executable.is_file()
    assert old_manifest['commit'] == baseline['core_commit'] and old_manifest['sha256'] == baseline['core_sha256']
    assert old_manifest['runtimeId'] == old['runtime_id']
    assert read(resources / 'seed/runtime.json')['runtimeId'] == old['base_runtime_id']
    verify_signature(resources, manifest, descriptor)
    replace_included_core(resources, core_file, manifest, descriptor, batch['shell_files'])

    output = work / 'installers'
    candidate_files = prepare_candidate(target, batch['tag'], scratch, resources, files, old, output, recipe)
    fresh = work / 'fresh install'
    resources, executable = install_native(target, output, fresh)
    assert workload_valid(resources, executable, manifest, descriptor)
    environment = {**os.environ, 'KX_EXPECTED_PLATFORM': old['platform'], 'KX_EXPECTED_ARCH': old['arch']}
    run('node', recipe / 'ci-fresh-smoke.mjs', executable, resources,
        work / '全新学习目录', evidence, cwd=recipe, env=environment, timeout=1800)

    full_files = [{'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
                  for path in candidate_files]
    assert all(0 < row['bytes'] < 2_000_000_000 for row in full_files)
    if target == 'windows-x64':
        for row in [row for row in full_files if '-Runtime.' in row['file']]:
            expected = next(item for item in old['files'] if item['name'] == row['file'])
            assert (row['bytes'], row['sha256']) == (expected['bytes'], expected['sha256'])
    assert all(locate(metadata_after, row)
               for metadata_after in [metadata(baseline['tag'])]
               for row in old['files'])
    result = {
        'target': target, 'input_release': baseline['tag'], 'input_release_id': baseline['release_id'],
        'release': batch['tag'], 'launcher_build': descriptor['buildId'], 'core_commit': manifest['commit'],
        'core_sha256': manifest['sha256'], 'base_runtime_id': manifest['baseRuntimeId'],
        'native_install': 'passed', 'downloaded_from_public_github': True,
        'native_smoke': read(evidence / 'app.json'), 'download_files': download_rows,
        'full_files': full_files, 'real_keys_used': False, 'real_learning_records_modified': False,
        'installer_reuse': {'existing_installers_repackaged': True, 'native_seed_unchanged': True,
                            'windows_runtime_parts_reused': target == 'windows-x64'},
        'run_id': int(os.environ['GITHUB_RUN_ID']) if 'GITHUB_RUN_ID' in os.environ else None,
        'workflow_commit': os.environ.get('GITHUB_SHA'),
    }
    write(evidence / ('verification-' + target + '.json'), result)
    print('PASS: installed the rebuilt native full installer for ' + target, flush=True)


def workload_valid(resources, executable, manifest, descriptor):
    assert executable.is_file()
    assert read(resources / 'update/runtime.json') == manifest
    assert read(resources / 'seed/runtime.json')['runtimeId'] == manifest['baseRuntimeId']
    assert read(resources / 'app/package.json')['kaixinLauncherBuild'] == descriptor['buildId']
    assert digest(resources / 'update' / manifest['archive']) == manifest['sha256']
    for row in descriptor['files']:
        file = resources / 'app' / row['file']
        assert file.stat().st_size == row['bytes'] and digest(file) == row['sha256']
    verify_signature(resources, manifest, descriptor)
    return True


if __name__ == '__main__':
    main()
