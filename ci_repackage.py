"""Replace only the launcher and included signed core in a verified installer copy."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import Request, urlopen


def validate_installer_files(files, target, tag):
    names = {row['file'] for row in files}
    assert len(names) == len(files) and all(0 < row['bytes'] < 2_000_000_000 for row in files)
    if target == 'windows-x64':
        stem = 'Kaixin-Super-Scholar-Windows-v1.7.1-'
        expected = {stem+'Setup.exe', *(stem+'Runtime.00'+str(i) for i in range(1,5))}
    else:
        assert target in {'macos-x64', 'macos-arm64'} and 4 <= len(files) <= 5
        brand = 'Intel' if target == 'macos-x64' else 'Apple-Silicon'
        stem = 'Kaixin-Super-Scholar-MacOS-'+brand+'-v1.7.1-'+tag.removeprefix('student-')+'-part'
        expected = {stem+'.dmg', *(stem+f'.{i:03d}.dmgpart' for i in range(2,len(files)+1))}
    assert names == expected, 'Missing or unexpected full-installer segment'


def validate_reuse_lock(lock, batch, release, target):
    reuse = lock['reuse_existing_native']
    assert lock['tag'] == batch['tag'] == release['tag_name'] == 'student-20261117-k12-5'
    assert lock['core_commit'] == batch['core_commit'] == '9328240380d13ef75435434a8c901028ea4470dc'
    assert lock['core_sha256'] == batch['core_asset']['digest'].removeprefix('sha256:')
    assert lock['release_id'] == release['id'] == 448792391 and release['prerelease'] and not release['draft']
    assert reuse['baseline_latest_id'] == 448283800 and reuse['original_native_run'] == 44114676923
    assert reuse['original_native_workflow_commit'] == '800eeeece85fd1f36a5d3f55854bfabd6baa89dd'
    validate_installer_files([{'file':r['name'],'bytes':r['bytes']} for r in lock['targets'][target]['files']], target, lock['tag'])
    assets = {r['name']:r for r in release['assets']}
    for row in reuse['original_installer_assets'][target]:
        assert row['url']=='https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/'+lock['tag']+'/'+row['name']
        actual=assets[row['name']]
        assert actual['id']==row['id'] and actual['size']==row['bytes'] and actual['digest']=='sha256:'+row['sha256']
    assert {r['name'] for r in reuse['original_installer_assets'][target]} == {r['name'] for r in lock['targets'][target]['files']}
    assert not any(name in assets for name in ['kaixin-bridge-20261117-k12-5-'+target+'.tar.gz','attachment-stage-'+target+'.json','verification-'+target+'.json']), 'Existing stage requires frozen-stage reuse, not reconstruction'
    prior_asset=reuse['prior_core_asset']
    assert prior_asset['name']=='kaixin-core-20261117-k12-4.tar.gz' and prior_asset['bytes']==572023510
    assert prior_asset['sha256']=='3220d81db122a1805eaa88b3f51de4bd31468192e056ea0bf461079120e9552f' and prior_asset['id']==758074993
    assert prior_asset['url']=='https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-4/'+prior_asset['name']
    prior=reuse['prior_manifests'][target]
    assert prior['commit']=='2af326481943f7e072036637ba186aa829dce39d' and prior['baseRuntimeId']==batch['manifests'][target]['baseRuntimeId']
    assert prior['sha256']==reuse['prior_core_asset']['sha256'] and prior['archive']==reuse['prior_core_asset']['name']


def verify_production_launcher(root, target, install, resources, evidence):
    # A small throwaway Electron copy tests proxies; the distributable never contains the probe.
    probe = root / ('network-probe-' + target + ('.app' if target.startswith('macos-') else ''))
    source_app = resources.parent.parent if target.startswith('macos-') else install
    shutil.copytree(source_app, probe, ignore=lambda directory, names:
                    [name for name in names if name in {'seed', 'update'}] if Path(directory) == resources else [], symlinks=True)
    probe_resources = probe / 'Contents/Resources' if target.startswith('macos-') else probe / 'resources'
    probe_pkg = probe_resources / 'app/package.json'
    value = json.loads(probe_pkg.read_text())
    value['main'] = 'src/proxy-smoke.cjs'
    probe_pkg.write_text(json.dumps(value, ensure_ascii=False))
    shutil.copyfile(root / 'ci-proxy-smoke.cjs', probe_resources / 'app/src/proxy-smoke.cjs')
    proxy_home = root / ('proxy-home-' + target)
    proxy_home.mkdir()
    if target.startswith('macos-'):
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(probe)], check=True)
        probe_exe = probe / 'Contents/MacOS/开心动力超级学霸'
    else:
        probe_exe = probe / '开心动力超级学霸.exe'
    subprocess.run([str(probe_exe)], check=True, timeout=300, env={**os.environ,
                   'KX_PROXY_HOME': str(proxy_home), 'KX_BASE_MANIFEST': str(resources / 'seed/runtime.json'),
                   'KX_PROXY_RESULT': str(evidence / 'network.json')})
    shutil.rmtree(probe)
    shutil.rmtree(proxy_home)
    test_root = root / ('launcher-tests-' + target)
    shutil.copytree(resources / 'app/src', test_root / 'src')
    shutil.copytree(root / 'fetchfix-tests', test_root / 'test')
    if not (root / 'student-source').is_dir():
        subprocess.run(['python', 'bootstrap_source.py', '--with-updates'], check=True)
    for folder in ['scripts', 'platforms']:
        shutil.copytree(root / 'student-source/apps/desktop' / folder, test_root / folder)
    shutil.copytree(root / 'student-source/apps/desktop/assets', test_root / 'assets')
    tests = subprocess.run(['node', '--test', '--test-reporter=tap', *[str(p) for p in (test_root / 'test').glob('*.test.mjs')]], capture_output=True, text=True)
    (evidence / 'launcher-tests.tap').write_text(tests.stdout + tests.stderr)
    print(tests.stdout, flush=True)
    tests.check_returncode()
    counts = {key: int(re.search(r'^# ' + key + r' (\d+)$', tests.stdout, re.M).group(1)) for key in ['tests','pass','fail','skipped']}
    assert counts['tests'] >= 81 and counts['fail'] == 0
    (evidence / 'launcher-tests.json').write_text(json.dumps({'passed':True,'native_target':target,**counts},indent=2))



def prepare_candidate(root, target, install, resources, downloads, evidence, lock):
    batch = json.loads((root / 'attachment-batch.json').read_text())
    manifest = batch['manifests'][target]
    assert manifest['baseRuntimeId'] == json.loads((resources / 'seed/runtime.json').read_text())['runtimeId']
    previous_shell = json.loads((root / 'prior-launcher-fingerprint.json').read_text())
    for name, row in previous_shell.items():
        assert hashlib.sha256((resources / 'app' / name).read_bytes()).hexdigest() == row['sha256'], 'Unexpected prior launcher'
    shutil.copytree(resources / 'app/src', root / 'previous-launcher-src')
    shutil.copytree(resources / 'update', root / 'prior-update')
    core = resources / 'update'
    for file in core.iterdir():
        file.unlink()
    asset = batch['core_asset']
    request = Request(asset['browser_download_url'], headers={'User-Agent': 'Kaixin-native-release'})
    archive = core / manifest['archive']
    with urlopen(request, timeout=60) as response, archive.open('xb') as output:
        shutil.copyfileobj(response, output, 8 * 1024**2)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['sha256']
    (core / 'runtime.json').write_text(json.dumps(manifest, indent=2))
    descriptor = json.loads((root / 'launcher-manifest.json').read_text())
    assert descriptor['coreCommit'] == batch['core_commit']
    shutil.rmtree(resources / 'app/src')
    (resources / 'app/src').mkdir()
    with tarfile.open(archive) as bundle:
        for row in descriptor['files']:
            assert row['file'].startswith('src/') and '/' not in row['file'][4:]
            data = bundle.extractfile('launcher/' + row['file']).read()
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
            (resources / 'app' / row['file']).write_bytes(data)
    for name, row in batch['shell_files'].items():
        assert hashlib.sha256((resources / 'app' / name).read_bytes()).hexdigest() == row['sha256']

    pkg = json.loads((resources / 'app/package.json').read_text())
    pkg['kaixinLauncherBuild'] = batch['launcher_build']
    (resources / 'app/package.json').write_text(json.dumps(pkg, ensure_ascii=False, indent=2))

    verify_production_launcher(root, target, install, resources, evidence)

    out = root / ('candidate-' + target)
    out.mkdir()
    if target.startswith('macos-'):
        app = resources.parent.parent
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        shutil.rmtree(downloads)
        (install / 'Applications').symlink_to('/Applications')
        stem = 'Kaixin-Super-Scholar-MacOS-' + ('Intel' if target == 'macos-x64' else 'Apple-Silicon') + '-v1.7.1-' + batch['tag'].removeprefix('student-')
        image = out / (stem + '.dmg')
        subprocess.run(['/usr/bin/hdiutil', 'create', '-volname', '开心动力超级学霸', '-srcfolder', str(install),
                        '-fs', 'APFS', '-format', 'ULFO', str(image)], check=True)
        subprocess.run(['/usr/bin/hdiutil', 'verify', str(image)], check=True)
        subprocess.run(['/usr/bin/hdiutil', 'segment', '-segmentSize', '1900m', '-o', str(out / (stem + '-part.dmg')), str(image)], check=True)
        image.unlink()
        shutil.rmtree(app)
        mount = root / ('candidate-mount-' + target)
        mount.mkdir()
        subprocess.run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', str(mount),
                        str(out / (stem + '-part.dmg'))], check=True)
        try:
            subprocess.run(['/usr/bin/ditto', str(mount / app.name), str(app)], check=True)
        finally:
            subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount)], check=True)
    else:
        parts = []
        for row in lock['targets'][target]['files']:
            if '-Runtime.' in row['name']:
                file = downloads / row['name']
                shutil.move(file, out / file.name)
                parts.append({'file': file.name, 'bytes': row['bytes'], 'sha256': row['sha256']})
        base = json.loads((resources / 'seed/runtime.json').read_text())
        parts_file = out / 'installer-parts.json'
        parts_file.write_text(json.dumps({'sha256': base['sha256'], 'parts': sorted(parts, key=lambda row: row['file'])}))
        setup = out / 'Kaixin-Super-Scholar-Windows-v1.7.1-Setup.exe'
        # An installed copy has an uninstaller; it is generated again by NSIS.
        (install / 'Uninstall 开心动力超级学霸.exe').unlink(missing_ok=True)
        nsis = Path(os.environ['ProgramFiles(x86)']) / 'NSIS/makensis.exe'
        subprocess.run([str(nsis), '/INPUTCHARSET', 'UTF8', '-DSOURCE=' + str(install), '-DOUTFILE=' + str(setup),
                        '-DICON=' + str(resources / 'app/assets/icon.ico'), '-DVERSION=1.7.1', '-DFILEVERSION=1.7.1.0',
                        '-DPARTS_MANIFEST=' + str(parts_file), '-DARCHIVE_NAME=' + base['archive'],
                        str(root / 'fetchfix-windows/installer.nsi')], check=True)
        shutil.rmtree(install)
        install.mkdir()
        result = subprocess.run('"' + str(setup) + '" /S /D=' + str(install), timeout=900)
        assert result.returncode == 0
        parts_file.unlink()
        shutil.rmtree(downloads)
    validate_installer_files([{'file': f.name, 'bytes': f.stat().st_size} for f in out.iterdir()], target, batch['tag'])
    return out, batch
