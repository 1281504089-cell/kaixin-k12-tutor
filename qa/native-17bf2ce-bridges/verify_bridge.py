"""Boot one frozen universal archive on its own architecture, in a cold scratch profile."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import time
import zlib

from ci_fresh_install import MACHINES, REPO, digest, download, fetch, locate, verify_signature
from ci_repackage import read, run, write
from native_electron import launcher_files, setup
from reuse_native_bridge import reuse

HERE = Path(__file__).resolve().parent
LOCK = read(HERE / 'donor-lock.json')
PREVIEW = HERE.parent / 'cos-compat-17bf2ce-local-preview'
CANDIDATE = HERE.parent / 'candidate-17bf2ce-local-signed'


def checked_inputs(target, receipt_path, manifest_path, launcher_path):
    proof, manifest, launcher = map(read, (receipt_path, manifest_path, launcher_path))
    donor = LOCK['targets'][target]['asset']
    assert proof['native_prefix'] == {key: donor[key] for key in ('name', 'bytes', 'sha256')}
    assert proof['core'] == LOCK['core'] and proof['native_prefix_reused'] is True
    assert isinstance(proof['unchanged_native_entries'], int) and proof['unchanged_native_entries'] > 0
    bridge = proof['bridge']
    assert bridge['name'] == f'kaixin-bridge-20261124-17bf2ce-{target}.tar.gz'
    assert 0 < bridge['bytes'] < 2 * 1024**3
    assert (manifest['archive'], manifest['sha256'], manifest['commit']) == (bridge['name'], bridge['sha256'], LOCK['commit'])
    assert manifest['runtimeId'].endswith(f'-{target}-universal') and not manifest.get('baseRuntimeId')
    assert manifest['corePayloadSha256'] == LOCK['core']['sha256']
    assert launcher['coreCommit'] == LOCK['commit'] and launcher['buildId'] == LOCK['launcher_build']
    return proof, manifest, launcher, donor


def public_release(donor):
    assert LOCK['repository'] == REPO
    endpoint = f'repos/{REPO}/releases/assets/{donor["id"]}'
    if os.environ.get('GH_TOKEN'):
        asset = json.loads(subprocess.check_output(['gh', 'api', endpoint]))
    else:
        with fetch('https://api.github.com/' + endpoint, 'application/vnd.github+json') as response:
            asset = json.load(response)
    release = {'tag_name': LOCK['tag'], 'assets': [asset]}
    locate(release, donor)
    return release


def check_file(path, expected):
    assert path.is_file() and path.stat().st_size == expected['bytes'], path.name
    assert digest(path) == expected['sha256'], path.name



def read_cut_member(path, proof):
    check_file(path, proof['bridge'])
    prefix_bytes = proof['bridge']['bytes'] - proof['core']['bytes']
    length = min(prefix_bytes, 8 * 1024**2)
    with path.open('rb') as stream:
        stream.seek(prefix_bytes - length)
        tail = stream.read(length)
    for hit in reversed(list(re.finditer(rb"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x13", tail))):
        member = tail[hit.start():]
        try:
            stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
            stream.decompress(member, 16 * 1024**2)
            if stream.eof and not stream.unused_data and not stream.unconsumed_tail:
                return member
        except zlib.error:
            continue
    raise ValueError('The last Darwin gzip member was not found in the 8 MiB tail of the native prefix')

def run_probe(executable, profile, output):
    env = dict(os.environ, OPEN_DEEPTUTOR_TEST_HOME=str(profile), KX_BRIDGE_EVIDENCE=str(output))
    for name in ('GH_TOKEN', 'GITHUB_TOKEN'):
        env.pop(name, None)
    # Windows hosted runners need a normal taskkill on timeout to stop the owned child tree.
    with (output/'process.log').open('wb') as log:
        process = subprocess.Popen([str(executable)], cwd=executable.parent, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=os.name != 'nt')
        try:
            assert process.wait(timeout=900) == 0, 'Native Electron cold launch failed'
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=False)
            else:
                os.killpg(process.pid, 15)
            process.wait(timeout=40)
            raise
        finally:
            runtime = profile/'logs/runtime.log'
            if runtime.is_file():
                shutil.copyfile(runtime, output/'runtime.log')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=MACHINES)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--launcher', type=Path, default=CANDIDATE/'launcher-manifest.json')
    parser.add_argument('--core', type=Path, default=CANDIDATE/LOCK['core']['name'])
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--bridge', type=Path, help='Exact, already-built bridge read from the lab')
    source.add_argument('--donor', type=Path, help='Exact previous donor already present in the lab')
    parser.add_argument('--inspect', action='store_true', help='Verify receipt identity and read only small GitHub metadata')
    parser.add_argument('--boundary-member', type=Path, help='Byte-exact final native gzip member copied from the frozen bridge')
    parser.add_argument('--capture-boundary', type=Path, help='Write only the final native gzip member of --bridge')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--retain-verified', type=Path, help='Move the verified archive to this new file after a successful native boot')
    args = parser.parse_args()
    target = args.target
    receipt = args.receipt or PREVIEW/f'bridge-{target}.json'
    manifest_path = args.manifest or PREVIEW/'feed-plan'/f'preview-{target}'/'github'/f'runtime-{target}.json'
    proof, manifest, launcher, donor = checked_inputs(target, receipt, manifest_path, args.launcher)
    if args.inspect:
        public_release(donor)
        print(json.dumps({'scope': 'receipt and public donor metadata', 'target': target, 'donor':donor, 'frozen':proof['bridge']}, ensure_ascii=False))
        return
    if args.capture_boundary:
        assert args.bridge is not None
        captured = read_cut_member(args.bridge, proof)
        with args.capture_boundary.open('xb') as file:
            file.write(captured)
        return
    assert platform.machine() == MACHINES[target], 'Use a runner with the actual target architecture'
    if args.evidence is None:
        parser.error('--evidence is required to boot')
    output = args.evidence.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(dir=os.environ.get('RUNNER_TEMP'), prefix='kaixin-17bf2ce-native-') as directory:
        work = Path(directory)
        expected = proof['bridge']
        archive = work/expected['name']
        started = time.monotonic()
        if args.bridge:
            shutil.copyfile(args.bridge, archive)
            check_file(archive, expected)
            origin = 'exact lab bridge'
        else:
            assert args.core.stat().st_size == proof['core']['bytes']
            prior = args.donor or work/donor['name']
            if not args.donor:
                download(public_release(donor), donor, prior)
            boundary = None
            if args.boundary_member:
                assert 0 < args.boundary_member.stat().st_size <= 8 * 1024**2
                boundary = args.boundary_member.read_bytes()
            result = reuse(prior, donor, args.core, proof['core'], archive, proof['unchanged_native_entries'], boundary)
            assert result == expected, 'Reconstruction differed from the signed bridge; supply the frozen boundary member or whole lab bridge'
            if not args.donor:
                prior.unlink()
            origin = 'locally reconstructed from pinned donor and signed core'
        app, resources, executable = setup(work, target)
        seed = resources/'seed'
        seed.mkdir()
        archive.rename(seed/archive.name)
        write(seed/'runtime.json', manifest)
        launcher_dir = resources/'app'
        launcher_files(seed/archive.name, launcher_dir)
        assert read(launcher_dir/'manifest.json') == launcher
        for row in launcher['files']:
            name = Path(row['file'])
            assert len(name.parts) == 2 and name.parts[0] == 'src' and name.name not in ('.', '..')
            check_file(launcher_dir/name, row)
        verify_signature(resources, manifest, launcher)
        write(launcher_dir/'package.json', {'name':'kaixin-super-scholar', 'productName':'开心动力超级学霸',
              'version':'1.7.1', 'main':'native-bridge-probe.cjs', 'type':'module', 'kaixinLauncherBuild':launcher['buildId']})
        shutil.copyfile(HERE/'native-bridge-probe.cjs', launcher_dir/'native-bridge-probe.cjs')
        if target == 'windows-x64':
            shutil.copyfile(HERE/'icon.ico', launcher_dir/'assets/icon.ico')
        if target.startswith('macos-'):
            run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', app, timeout=300)
            run('/usr/bin/codesign', '--verify', '--deep', '--strict', app, timeout=300)
        profile = work/'empty-learning-profile'
        profile.mkdir()
        run_probe(executable, profile, output)
        ready = read(output/'bridge-window.json')
        assert ready['bridge_sha256'] == expected['sha256'] and ready['arch'] == target.rsplit('-',1)[-1]
        assert ready['electron'] == '45.1.0' and ready['boot_commit'] == LOCK['commit']
        if args.retain_verified:
            assert args.retain_verified.name == expected['name'] and not args.retain_verified.exists()
            (seed/archive.name).rename(args.retain_verified)
        write(output/'result.json', {'passed':True, 'target':target, 'archive':expected, 'origin':origin,
              'launcher_signature_verified':True, 'runtime_signature_verified':True, 'existing_learning_used':False,
              'whole_package_cos_downloads':0, 'boot':ready, 'seconds':round(time.monotonic()-started,3)})


if __name__ == '__main__':
    main()
