"""Rebuild the self-contained bridge without dropping the platform's Next runtime."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parent
HOSTS = {'github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
TARGETS = ('macos-arm64', 'macos-x64', 'windows-x64')


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked(url):
    parsed = urlsplit(url)
    assert parsed.scheme == 'https' and parsed.hostname in HOSTS
    assert not parsed.username and not parsed.password
    return url


class TrustedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, checked(newurl))


def fetch(url, accept):
    return build_opener(TrustedRedirects()).open(
        Request(checked(url), headers={'User-Agent': 'Kaixin-Bridge-Verification', 'Accept': accept}), timeout=90)


def metadata(repository, tag):
    route = f'repos/{repository}/releases/tags/{tag}'
    if os.environ.get('GH_TOKEN'):
        return json.loads(subprocess.check_output(['gh', 'api', route]))
    with fetch('https://api.github.com/' + route, 'application/vnd.github+json') as source:
        return json.load(source)


def assert_release(document, pin, candidate):
    assert document['id'] == pin['release_id'] and document['tag_name'] == pin['tag']
    assert document['draft'] is False
    if candidate:
        assert document['prerelease'] is True


def locate(repository, release, row):
    asset, = (x for x in release['assets'] if x['name'] == row['name'])
    name, tag = row['name'], release['tag_name']
    assert asset['size'] == row['bytes'] and asset['id'] == row['id']
    assert asset['state'] == 'uploaded' and asset['digest'] == 'sha256:' + row['sha256']
    assert asset['url'] == f'https://api.github.com/repos/{repository}/releases/assets/{row["id"]}'
    assert asset['browser_download_url'] == f'https://github.com/{repository}/releases/download/{tag}/{name}'
    return asset


def verify_file(file, row):
    assert file.is_file() and file.stat().st_size == row['bytes'] and digest(file) == row['sha256'], row['name']
    return file


def download(asset, row, scratch):
    target = scratch / row['name']
    temp = target.with_suffix(target.suffix + '.partial')
    attempts = []
    for url in (asset['browser_download_url'], asset['browser_download_url'], asset['url']):
        try:
            state = hashlib.sha256()
            total = 0
            with fetch(url + '?bridge-r2=' + str(time.time_ns()), 'application/octet-stream') as source, temp.open('xb') as out:
                checked(source.url)
                while data := source.read(8 << 20):
                    total += len(data)
                    assert total <= row['bytes']
                    state.update(data)
                    out.write(data)
            assert total == row['bytes'] and state.hexdigest() == row['sha256']
            temp.rename(target)
            print(f'Downloaded and hashed {target.name}: {total} bytes', flush=True)
            return target
        except (OSError, AssertionError) as exc:
            temp.unlink(missing_ok=True)
            attempts.append(type(exc).__name__ + ': ' + str(exc).split('?')[0])
    raise RuntimeError(f'Unable to download {target.name}: ' + '; '.join(attempts))


def check_signatures(target, candidate):
    program = r'''
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { verify } from 'node:crypto';
const [publicKey, signed, platformName, expectedText] = process.argv.slice(1);
const expected = JSON.parse(expectedText);
const manifest = JSON.parse(readFileSync(signed))[platformName];
const { signature, ...fields } = manifest;
const payload = JSON.stringify(Object.fromEntries(Object.entries(fields).sort(([a], [b]) => a.localeCompare(b))));
assert(verify(null, Buffer.from(payload), readFileSync(publicKey), Buffer.from(signature, 'base64')));
assert.equal(manifest.archive, expected.core.name);
assert.equal(manifest.sha256, expected.core.sha256);
assert.equal(manifest.corePayloadSha256, expected.core.sha256);
assert.equal(manifest.commit, expected.source_commit);
assert.equal(manifest.arch, platformName.split('-').at(-1));
assert.equal(manifest.platform, platformName.startsWith('macos-') ? 'darwin' : 'win32');
'''
    subprocess.run(['node', '--input-type=module', '-e', program, str(ROOT / 'bridge-runtime-public.pem'),
                    str(ROOT / 'bridge-core-signed-manifests.json'), target, json.dumps(candidate)], check=True)


def runtime_file(name):
    if name == 'BUILD_COMMIT':
        return True
    if name in {'core', 'launcher'} or name.startswith(('core/', 'launcher/')):
        return True
    return name.startswith('web/') and name != 'web/node_modules' and not name.startswith('web/node_modules/')


def safe_member(member):
    name = member.name
    path = PurePosixPath(name)
    assert name and not path.is_absolute() and '\\' not in name and '..' not in path.parts
    assert ':' not in path.parts[0] if path.parts else name == '.'
    assert member.isfile() or member.isdir() or member.issym() or member.islnk(), name
    return name


class HashedReader:
    def __init__(self, source):
        self.source = source
        self.state = hashlib.sha256()

    def read(self, n):
        data = self.source.read(n)
        self.state.update(data)
        return data

    def digest(self):
        return self.state.hexdigest()


def summary(member, digest):
    return (member.type.decode(), member.mode, member.uid, member.gid, member.uname, member.gname,
            member.mtime, member.size, member.linkname, member.pax_headers, digest)


def inspect_member(archive, member, output=None, keep_payload=False):
    if not member.isfile():
        if output is not None:
            output.addfile(member)
        return summary(member, None), None
    source = archive.extractfile(member)
    with source:
        if keep_payload:
            assert 0 <= member.size < 65536
            data = source.read()
            if output is not None:
                from io import BytesIO
                output.addfile(member, BytesIO(data))
            return summary(member, hashlib.sha256(data).hexdigest()), data
        if output is not None:
            reader = HashedReader(source)
            output.addfile(member, reader)
            return summary(member, reader.digest()), None
        state = hashlib.sha256()
        while data := source.read(1 << 20):
            state.update(data)
        return summary(member, state.hexdigest()), None


def build(prior, core, index, destination, lock, target, level):
    preserved = {}
    expected_index = {row['file']: row for row in index['files']}
    assert len(expected_index) == len(index['files'])
    assert set(expected_index) >= {'BUILD_COMMIT', 'core/deeptutor_cli/main.py', 'launcher/manifest.json',
                                  'web/server.js', 'web/.next/BUILD_ID'}
    assert all(runtime_file(name) for name in expected_index)
    dependency_paths = {f'web/node_modules/{name}/package.json': (name, version)
                        for name, version in lock['expected_web_packages'].items()}
    dependencies = {}
    core_rows = {}

    with destination.open('xb') as target_file, gzip.GzipFile(filename='', fileobj=target_file,
                 mode='wb', mtime=0, compresslevel=level) as zipped:
        with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.PAX_FORMAT, copybufsize=1024*1024) as output:
            with tarfile.open(prior, mode='r|gz', bufsize=1024*1024) as source:
                for member in source:
                    name = safe_member(member)
                    if runtime_file(name):
                        continue
                    assert name not in preserved, name
                    row, payload = inspect_member(source, member, output, name in dependency_paths)
                    preserved[name] = row
                    if payload is not None:
                        pkg, version = dependency_paths[name]
                        assert json.loads(payload)['version'] == version
                        dependencies[pkg] = {'version': version, 'sha256': row[-1]}

            with tarfile.open(core, mode='r|gz', bufsize=1024*1024) as source:
                for member in source:
                    name = safe_member(member)
                    assert name in expected_index and name not in core_rows and name not in preserved and member.isfile()
                    small = {'BUILD_COMMIT', 'web/.next/BUILD_ID', 'launcher/manifest.json'}
                    row, payload = inspect_member(source, member, output, name in small)
                    frozen = expected_index[name]
                    assert (member.size, member.mode, row[-1]) == (frozen['bytes'], frozen['mode'], frozen['sha256']), name
                    core_rows[name] = row
                    if name == 'BUILD_COMMIT':
                        assert payload.decode().strip() == lock['candidate']['source_commit']
                    if name == 'web/.next/BUILD_ID':
                        assert payload.decode().strip() == lock['candidate']['frontend_build']
                    if name == 'launcher/manifest.json':
                        launcher = json.loads(payload)
                        assert launcher['coreCommit'] == lock['candidate']['source_commit']
                        assert launcher['buildId'] == lock['candidate']['launcher_build']

    assert set(core_rows) == expected_index.keys()
    assert dependencies.keys() == lock['expected_web_packages'].keys()
    runtime = {'python/python.exe', 'node/node.exe'} if target == 'windows-x64' else {'python/bin/python3', 'node/bin/node'}
    assert set(preserved) >= runtime | {'web/node_modules/next/dist/server/lib/start-server.js'}
    return preserved, core_rows, dependencies


def read_back(archive, preserved, core_rows):
    expected = preserved | core_rows
    seen = set()
    with tarfile.open(archive, mode='r|gz', bufsize=1024*1024) as source:
        for member in source:
            name = safe_member(member)
            assert name in expected and name not in seen, name
            record, _ = inspect_member(source, member)
            assert record == expected[name], name
            seen.add(name)
    assert seen == expected.keys()


def stage_archive(repository, pin, archive, report, row):
    for selected, label in [(archive, archive.name), (report, report.name)]:
        release = metadata(repository, pin['tag'])
        assert_release(release, pin, True)
        matches = [asset for asset in release['assets'] if asset['name'] == label]
        if not matches:
            subprocess.run(['gh', 'release', 'upload', pin['tag'], str(selected), '--repo', repository],
                           check=True, timeout=1400)
            release = metadata(repository, pin['tag'])
            assert_release(release, pin, True)
            matches = [asset for asset in release['assets'] if asset['name'] == label]
        assert len(matches) == 1
        got = matches[0]
        sha256 = row['sha256'] if selected == archive else digest(selected)
        assert got['state'] == 'uploaded' and got['size'] == selected.stat().st_size
        assert got['digest'] == 'sha256:' + sha256, label


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=TARGETS, required=True)
    parser.add_argument('--output', type=Path, default=Path('bridge-output'))
    parser.add_argument('--prior-file', type=Path)
    parser.add_argument('--core-file', type=Path)
    parser.add_argument('--core-index', type=Path)
    parser.add_argument('--check-metadata', action='store_true')
    parser.add_argument('--stage', action='store_true')
    args = parser.parse_args()

    started = time.monotonic()
    lock = read(ROOT / 'bridge-r2-lock.json')
    repository, previous, candidate = (lock[key] for key in ('repository', 'previous', 'candidate'))
    assert repository == '1281504089-cell/kaixin-k12-tutor'
    assert previous['tag'] == 'student-20261117-k12-16' and candidate['tag'] == 'student-20261117-k12-18'
    assert lock['archive_limit_exclusive'] == 2 * 1024**3
    prior_row = previous['bridges'][args.target]
    old = metadata(repository, previous['tag'])
    current = metadata(repository, candidate['tag'])
    assert_release(old, previous, False)
    assert_release(current, candidate, True)
    prior_asset = locate(repository, old, prior_row)
    core_asset = locate(repository, current, candidate['core'])
    index_asset = locate(repository, current, candidate['core_index'])
    check_signatures(args.target, candidate)
    if args.check_metadata:
        print(args.target + ': GitHub asset IDs, lengths, SHA-256 and owner signature match')
        return

    output = args.output.resolve()
    output.mkdir(parents=True)
    name = f'kaixin-bridge-20261117-k12-18-r2-{args.target}.tar.gz'
    archive = output / name
    assert not archive.exists()
    with tempfile.TemporaryDirectory(prefix='bridge-r2-') as work:
        scratch = Path(work)
        prior = verify_file(args.prior_file, prior_row) if args.prior_file else download(prior_asset, prior_row, scratch)
        core = verify_file(args.core_file, candidate['core']) if args.core_file else download(core_asset, candidate['core'], scratch)
        index_path = verify_file(args.core_index, candidate['core_index']) if args.core_index else download(index_asset, candidate['core_index'], scratch)
        index = read(index_path)
        assert index['source_commit'] == candidate['source_commit']
        temp = archive.with_suffix('.partial')
        for level in (6, 9):
            preserved, core_rows, dependencies = build(prior, core, index, temp, lock, args.target, level)
            if temp.stat().st_size < lock['archive_limit_exclusive']:
                break
            temp.unlink()
        else:
            raise RuntimeError(f'{args.target} exceeds the 2 GiB GitHub asset limit at gzip level 9')
        read_back(temp, preserved, core_rows)
        payload_bytes = temp.stat().st_size
        row = {'bytes': payload_bytes, 'sha256': digest(temp)}
        temp.rename(archive)
    result = {'passed': True, 'target': args.target, 'tag': candidate['tag'], 'release_id': candidate['release_id'],
              'source_commit': candidate['source_commit'], 'launcher_build': candidate['launcher_build'],
              'frontend_build': candidate['frontend_build'], 'core': candidate['core'],
              'previous_bridge': prior_row, 'archives': {name: row}, 'compression_level': level,
              'archive_limit_exclusive': lock['archive_limit_exclusive'], 'archive_headroom_bytes': lock['archive_limit_exclusive']-payload_bytes,
              'native_members_preserved': len(preserved), 'core_members_verified': len(core_rows),
              'web_node_modules_members_preserved': sum(n.startswith('web/node_modules/') for n in preserved),
              'web_dependencies': dependencies, 'archive_readback': 'all members compared byte by byte and metadata checked',
              'seconds': round(time.monotonic()-started, 2),
              'run_id': int(os.environ['GITHUB_RUN_ID']) if 'GITHUB_RUN_ID' in os.environ else None,
              'workflow_commit': os.environ.get('GITHUB_SHA')}
    report = output / f'bridge-r2-{args.target}.json'
    report.write_text(json.dumps(result, indent=2) + '\n')
    if args.stage:
        stage_archive(repository, candidate, archive, report, row)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
