"""Cold-boot the exact signed fallback archive on its own OS and processor."""
import argparse
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
COMPONENTS = HERE.with_name('native-17bf2ce-bridges')
sys.path[:0] = [str(HERE.with_name('native-17bf2ce')), str(COMPONENTS), str(HERE.with_name('native-47ce923-bridges'))]

from ci_fresh_install import MACHINES, digest, download, metadata, verify_signature
from ci_repackage import read, run, write
from draft_assets import draft, pinned_draft_asset
from native_electron import launcher_files, setup
from retain_verified_media import LOCK, match, upload_one
from verify_bridge import run_probe


def prepare(target, directory):
    proof = read(HERE / f'bridge-{target}.json')
    archive = proof['bridge']
    pinned = proof['native_prefix']
    manifest = read(HERE / f'bridge-runtime-{target}.json')
    assert proof['source_commit'] == manifest['commit'] == LOCK['source_commit']
    assert manifest['archive'] == archive['name'] and manifest['sha256'] == archive['sha256']
    assert proof['core'] == LOCK['core']
    assert manifest['corePayloadSha256'] == proof['core']['sha256']
    assert not manifest.get('baseRuntimeId')
    old = metadata('core-updates')
    assert old['id'] == 437538031 and not old['draft']
    donor, = (a for a in old['assets'] if a['name'] == pinned['donor'])
    assert donor['digest'] == 'sha256:' + pinned['donor_sha256']
    path = directory / donor['name']
    download(old, {'name': donor['name'], 'id': donor['id'], 'sha256': pinned['donor_sha256'],
                   'bytes': donor['size']}, path)
    release, files = draft(LOCK)
    assert release['draft'] and release['tag_name'] == 'student-20261126-unified-43dba66'
    for spec in (LOCK['core'], LOCK['launcher']):
        pinned_draft_asset(files, spec, directory / spec['name'])
    core = directory / LOCK['core']['name']
    out = directory / archive['name']
    remaining = pinned['bytes']
    prefix = sha256()
    with path.open('rb') as donor_stream, out.open('xb') as bundle:
        while remaining:
            data = donor_stream.read(min(4 * 1024**2, remaining))
            assert data
            remaining -= len(data)
            prefix.update(data)
            bundle.write(data)
        with core.open('rb') as source:
            shutil.copyfileobj(source, bundle, 4 * 1024**2)
    assert prefix.hexdigest() == pinned['sha256']
    assert out.stat().st_size == archive['bytes'] and digest(out) == archive['sha256']
    path.unlink()
    core.unlink()
    return out, manifest, read(directory / LOCK['launcher']['name']), release


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('target', choices=MACHINES)
    p.add_argument('--evidence', type=Path, required=True)
    args = p.parse_args()
    assert os.environ['GITHUB_REF'] == 'refs/heads/codex/desktop-native-qa-43dba66'
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix='scholar-43dba66-bridge-', dir=os.environ['RUNNER_TEMP']) as scratch:
        work = Path(scratch)
        bridge, manifest, launcher, prior = prepare(args.target, work)
        item = {'file':bridge.name, 'bytes':bridge.stat().st_size, 'sha256':manifest['sha256']}
        app, resources, executable = setup(work, args.target)
        seed = resources / 'seed'
        seed.mkdir()
        archive = seed / bridge.name
        bridge.rename(archive)
        write(seed / 'runtime.json', manifest)
        shell = resources / 'app'
        launcher_files(archive, shell)
        assert read(shell / 'manifest.json') == launcher
        for row in launcher['files']:
            actual = shell / row['file']
            assert actual.stat().st_size == row['bytes'] and digest(actual) == row['sha256']
        verify_signature(resources, manifest, launcher)
        probe = COMPONENTS / 'native-bridge-probe.cjs'
        shutil.copy2(probe, shell / probe.name)
        write(shell / 'package.json', {'name':'kaixin-super-scholar', 'productName':'开心动力超级学霸',
            'version':'1.7.1', 'main':probe.name, 'type':'module', 'kaixinLauncherBuild':launcher['buildId']})
        if args.target == 'windows-x64':
            shutil.copy2(COMPONENTS / 'icon.ico', shell / 'assets/icon.ico')
        else:
            run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', app, timeout=300)
            run('/usr/bin/codesign', '--verify', '--deep', '--strict', app, timeout=300)
        profile = work / 'empty-learning-profile'
        profile.mkdir()
        run_probe(executable, profile, evidence)
        boot = read(evidence / 'bridge-window.json')
        assert boot['native_window'] and boot['boot_commit'] == LOCK['source_commit']
        assert (boot['arch'], boot['core_sha256'], boot['bridge_sha256']) == (
            manifest['arch'], LOCK['core']['sha256'], item['sha256'])
        release, assets = draft(LOCK)
        assert release['id'] == prior['id'] and release['draft']
        existing = assets.get(item['file'])
        if not existing:
            upload_one(release, item, archive)
        release, assets = draft(LOCK)
        assert match(assets[item['file']], item)
        write(evidence / 'bridge-acceptance.json', {'passed':True, 'commit':LOCK['source_commit'],
            'target':args.target, 'archive':item, 'native':boot, 'draft_id':release['id'],
            'asset_id':assets[item['file']]['id'], 'whole_package_cos_downloads':0})


if __name__ == '__main__':
    main()
