"""Rebuild a full installer from a SHA-256-pinned native k12-16 installation."""
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import time


APP = '开心动力超级学霸'
WINDOWS_STEM = 'Kaixin-Super-Scholar-Windows-v1.7.1-'


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def install_native(target, files, install):
    install.mkdir()
    if target == 'windows-x64':
        setup = files / (WINDOWS_STEM + 'Setup.exe')
        assert setup.is_file()
        subprocess.run(f'"{setup}" /S /D={install}', check=True, timeout=1200)
        return install / 'resources', install / (APP + '.exe')

    image, = files.glob('*-part.dmg')
    mount = install.parent / ('mount-' + install.name)
    mount.mkdir()
    run('/usr/bin/hdiutil', 'verify', image, timeout=600)
    run('/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen',
        '-mountpoint', mount, image, timeout=300)
    try:
        app = install / (APP + '.app')
        run('/usr/bin/ditto', mount / app.name, app, timeout=900)
    finally:
        # APFS can briefly retain a handle to this read-only CI image.
        for attempt in range(3):
            try:
                run('/usr/bin/hdiutil', 'detach', mount, timeout=120)
                break
            except subprocess.CalledProcessError as error:
                if error.returncode != 16:
                    raise
                time.sleep(2)
        else:
            run('/usr/bin/hdiutil', 'detach', '-force', mount, timeout=120)
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app, timeout=900)
    return app / 'Contents/Resources', app / 'Contents/MacOS' / APP


def replace_included_core(resources, core, manifest, descriptor, launcher_files):
    # Keep the pinned seed/base runtime and installer shell.
    update = resources / 'update'
    shutil.rmtree(update)
    update.mkdir()
    archive = update / manifest['archive']
    shutil.move(core, archive)
    write(update / 'runtime.json', manifest)

    app = resources / 'app'
    shell = {row['file']: row for row in descriptor['files']}
    assert set(shell) == set(launcher_files)
    assert descriptor['coreCommit'] == manifest['commit']
    import hashlib
    shutil.rmtree(app / 'src')
    (app / 'src').mkdir()
    installed = set()
    import gzip
    with gzip.open(archive, 'rb') as compressed, tarfile.open(fileobj=compressed, mode='r|') as bundle:
        for member in bundle:
            if member.name == 'launcher/manifest.json':
                assert member.isfile()
                with bundle.extractfile(member) as stream:
                    assert json.load(stream) == descriptor
                installed.add(member.name)
            name = member.name.removeprefix('launcher/')
            if not member.name.startswith('launcher/') or name not in shell:
                continue
            row = shell[name]
            path = PurePosixPath(name)
            assert len(path.parts) == 2 and path.parts[0] == 'src' and '..' not in path.parts
            assert member.isfile() and member.size == row['bytes']
            assert member.name not in installed
            with bundle.extractfile(member) as stream, (app / name).open('xb') as output:
                content = stream.read()
                assert hashlib.sha256(content).hexdigest() == row['sha256'] == launcher_files[name]['sha256']
                output.write(content)
            installed.add(member.name)
    assert installed == {'launcher/manifest.json', *('launcher/' + name for name in shell)}
    package = read(app / 'package.json')
    package['kaixinLauncherBuild'] = descriptor['buildId']
    write(app / 'package.json', package)


def prepare_candidate(target, tag, install, resources, downloads, expected, output, recipe):
    output.mkdir()
    if target.startswith('macos-'):
        app = resources.parent.parent
        run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', app, timeout=240)
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', app, timeout=900)
        shutil.rmtree(downloads)
        (install / 'Applications').symlink_to('/Applications')
        brand = 'Intel' if target == 'macos-x64' else 'Apple-Silicon'
        stem = f'Kaixin-Super-Scholar-MacOS-{brand}-v1.7.1-{tag.removeprefix("student-")}'
        image = output / (stem + '.dmg')
        run('/usr/bin/hdiutil', 'create', '-volname', APP, '-srcfolder', install,
            '-fs', 'APFS', '-format', 'ULFO', image, timeout=2700)
        run('/usr/bin/hdiutil', 'verify', image, timeout=600)
        shutil.rmtree(install)
        run('/usr/bin/hdiutil', 'segment', '-segmentSize', '1900m',
            '-o', output / (stem + '-part.dmg'), image, timeout=1200)
        image.unlink()
        files = sorted(output.iterdir())
        expected_names = {stem + '-part.dmg', *(stem + f'-part.{i:03d}.dmgpart' for i in range(2, len(files) + 1))}
        assert 4 <= len(files) <= 5 and {path.name for path in files} == expected_names
        return files

    import os
    rows = [row for row in expected['files'] if row['name'].startswith(WINDOWS_STEM + 'Runtime.')]
    assert sorted(row['name'] for row in rows) == [WINDOWS_STEM + f'Runtime.{i:03d}' for i in range(1, 5)]
    parts = []
    for row in rows:
        name = row['name']
        shutil.move(downloads / name, output / name)
        parts.append({'file': name, 'bytes': row['bytes'], 'sha256': row['sha256']})
    base = read(resources / 'seed/runtime.json')
    parts_manifest = output.parent / 'installer-parts.json'
    write(parts_manifest, {'sha256': base['sha256'], 'parts': sorted(parts, key=lambda part: part['file'])})
    setup = output / (WINDOWS_STEM + 'Setup.exe')
    (install / f'Uninstall {APP}.exe').unlink(missing_ok=True)
    nsis = Path(os.environ['ProgramFiles(x86)']) / 'NSIS/makensis.exe'
    run(nsis, '/INPUTCHARSET', 'UTF8', '-DSOURCE=' + str(install), '-DOUTFILE=' + str(setup),
        '-DICON=' + str(resources / 'app/assets/icon.ico'), '-DVERSION=1.7.1', '-DFILEVERSION=1.7.1.0',
        '-DPARTS_MANIFEST=' + str(parts_manifest), '-DARCHIVE_NAME=' + base['archive'],
        recipe / 'installer.nsi', timeout=2700)
    assert setup.is_file()
    shutil.rmtree(install)
    shutil.rmtree(downloads)
    return sorted(output.iterdir())
