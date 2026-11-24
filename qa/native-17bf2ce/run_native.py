"""Use the published native installer shell and the pinned private candidate bytes."""

import argparse
from contextlib import contextmanager
from functools import partial
from hashlib import file_digest, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.request import urlopen

from ci_fresh_install import MACHINES, verify_signature
from ci_repackage import install_native, prepare_candidate, read, replace_included_core, run, write
from draft_assets import draft, historical_installers, pinned_draft_asset

RECIPE = Path(__file__).resolve().parent
LOCK = read(RECIPE / 'input-lock.json')
MEMORY = Path('data/user/memory/L3/profile.md')
MARKER = '17bf2ce 桌面原生验收的合成学习记录\n'.encode()


def sha(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def stop(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                       check=False, capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    process.wait(timeout=40)


def boot(executable, home, log, **extra):
    env = {**os.environ, 'OPEN_DEEPTUTOR_TEST_HOME': str(home), **extra}
    for credential in ('GH_TOKEN','GITHUB_TOKEN'):
        env.pop(credential,None)
    with log.open('ab') as out:
        return subprocess.Popen([str(executable)], cwd=executable.parent, env=env,
                                stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=os.name != 'nt')


def poll(function, seconds, label):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if result := function():
            return result
        time.sleep(1)
    raise TimeoutError(label)


def wait_ready(process, home, wanted, log_offset=0):
    def verified():
        assert process.poll() is None, 'Native app exited before learning UI was ready'
        runtime_log = home / 'logs/runtime.log'
        if not runtime_log.exists():
            return
        with runtime_log.open('rb') as stream:
            stream.seek(log_offset)
            text = stream.read().decode('utf-8', 'replace')
        if 'Desktop startup failed:' in text:
            raise RuntimeError(text[-1800:])
        urls = re.findall(r'Local:\s+(http://127\.0\.0\.1:\d+)', text)
        if not urls or not (home / 'active.json').exists() or read(home / 'active.json') != wanted:
            return
        try:
            root = urls[-1]
            with urlopen(root + '/api/settings/ui', timeout=4) as response:
                assert response.status == 200 and json.load(response)['language'] == 'zh'
            with urlopen(root + '/chat', timeout=6) as response:
                if response.status == 200:
                    return {'active_commit': wanted['commit'], 'native_pid': process.pid,
                            'chat': True, 'backend_through_ui': True}
        except OSError:
            return
    return poll(verified, 900, 'Native learning UI never became ready')


class LocalFeed(BaseHTTPRequestHandler):
    def __init__(self, *args, files, **kwargs):
        self.files = files
        super().__init__(*args, **kwargs)
    def do_GET(self):
        file = self.files.get(self.path.removeprefix('/'))
        if file is None:
            self.send_error(404)
            return
        size = file.stat().st_size
        etag = '"' + self.server.asset_hashes[file] + '"'
        start = 0
        requested = self.headers.get('Range')
        if requested:
            bound = re.fullmatch(r'bytes=(\d+)-', requested)
            if not bound or not 0 < int(bound[1]) < size or self.headers.get('If-Match') != etag:
                self.send_error(416)
                return
            start = int(bound[1])
        self.send_response(206 if start else 200)
        self.send_header('Content-Length', str(size-start))
        self.send_header('ETag', etag)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', 'application/json' if file.suffix == '.json' else 'application/gzip')
        if start:
            self.send_header('Content-Range', f'bytes {start}-{size-1}/{size}')
        self.end_headers()
        with file.open('rb') as stream:
            stream.seek(start)
            shutil.copyfileobj(stream, self.wfile, 1024*1024)


@contextmanager
def loopback(files):
    with ThreadingHTTPServer(('127.0.0.1', 0), partial(LocalFeed, files=files)) as feed:
        feed.asset_hashes = {file: sha(file) for file in files.values()}
        worker = threading.Thread(target=feed.serve_forever, daemon=True)
        worker.start()
        try:
            yield f'http://127.0.0.1:{feed.server_port}'
        finally:
            feed.shutdown()
            worker.join()


def reseal_mac(resources):
    if os.name != 'nt':
        app = resources.parent.parent
        run('/usr/bin/codesign', '--force', '--sign', '-', app, timeout=240)
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', app, timeout=240)


def probed_update(executable, resources, profile, baseline, selected, default, alias, delta, output, target):
    app_root = resources / 'app'
    package = app_root / 'package.json'
    original = package.read_bytes()
    probe = app_root / 'native-update-probe.cjs'
    shutil.copyfile(RECIPE / probe.name, probe)
    write(package, {**read(package), 'main':probe.name})
    reseal_mac(resources)
    name, report = alias.name, output / 'incremental-update.json'
    files = {f'runtime-{target}.json': default, name: alias, delta.name: delta}
    with loopback(files) as origin:
        spec = output / 'loopback-spec.json'
        write(spec, {'target':target,'origin':origin,'baseline':baseline,'selected':selected,
          'archive':{'name':delta.name,'bytes':delta.stat().st_size,'sha256':sha(delta)},
          'manifest':{'requested':name,'bytes':alias.stat().st_size,'sha256':sha(alias)},
          'launcherBuild':LOCK['launcher_build'],'diskPreflight':{'free_bytes':shutil.disk_usage(profile).free},
          'transferOrigin':'local-only'})
        process = boot(executable, profile, output/'native-update.log', KX_QA_RECEIPT=str(report),
                       KX_QA_UPDATE_SPEC=str(spec))
        try:
            def finished():
                error = report.with_suffix('.json.error.json')
                if error.exists():
                    raise RuntimeError(error.read_text(encoding='utf-8'))
                return read(report) if report.exists() else None
            result = poll(finished, 1450, 'Actual application incremental update and restart')
            assert result['passed'] and result['signed_restart'] and result['check_again_current']
            assert result['source_commit'] == LOCK['source_commit']
            assert result['network']['bytes'] == delta.stat().st_size
            # The receipt is written immediately before app.quit() and the app's shutdown may take a moment.
            time.sleep(8)
        finally:
            stop(process)
            package.write_bytes(original)
            probe.unlink()
            reseal_mac(resources)
    return result


def recover(executable, home, baseline, output):
    journal = home / 'upgrade.json'
    transaction = read(journal)
    assert transaction['phase'] == 'complete' and transaction['previous'] == baseline
    backup = Path(transaction['backup']).resolve(strict=True)
    assert backup.parent == (home / 'backups').resolve()
    assert (backup / MEMORY).read_bytes() == MARKER
    # Reopen the updated native launcher with a deliberately interrupted local transaction.
    (home / 'workspace' / MEMORY).write_bytes(b'Uncommitted synthetic interruption\n')
    write(journal, {**transaction,'phase':'testing'})
    start = (home/'logs/runtime.log').stat().st_size
    process = boot(executable, home, output/'recovery.log')
    try:
        ready = wait_ready(process, home, baseline, start)
        assert read(journal)['phase'] == 'recovered'
        route = home/'workspace-location.json'
        restored = home/read(route)['name'] if route.exists() else home/'workspace'
        assert (restored/MEMORY).read_bytes() == MARKER
        return {**ready,'phase':'recovered','learning_record_intact':True}
    finally:
        stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=list(MACHINES))
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--downloads-only', action='store_true')
    args = parser.parse_args()
    if platform.machine() != MACHINES[args.target] or (os.name == 'nt') != (args.target=='windows-x64'):
        raise ValueError('Run on the expected native OS and architecture')
    target = args.target
    row = LOCK['targets'][target]
    output = args.evidence.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='native-scholar-17bf-',dir=os.environ['RUNNER_TEMP']))
    free = shutil.disk_usage(work).free
    input_bytes = sum(value['bytes'] for value in row['baseline_installers'])
    wait_for_space = LOCK['core']['bytes'] + row['delta']['bytes'] + 128*1024**2
    if not args.downloads_only:
        wait_for_space += input_bytes
    write(output/'disk.json',{'available':free,'download_bytes_required':wait_for_space,
                             'prior_media_bytes':input_bytes,'sequential_cleanup':True})
    if free < wait_for_space:
        raise RuntimeError(f'Scratch needs {wait_for_space} bytes for the verified inputs; this runner has {free}')
    release, assets = draft(LOCK)
    defaults = [row['default'], row['compatible'], row['delta'], LOCK['launcher'], LOCK['core']]
    receipts = [pinned_draft_asset(assets, asset, work / asset.get('name', asset.get('archive'))) for asset in
      ({**raw,'name':raw.get('name', raw.get('archive'))} for raw in defaults)]
    write(output/'draft-readback.json', {'release_id':release['id'],'assets':receipts})
    if args.downloads_only:
        return
    downloads = work/'public-installers'
    evidence = historical_installers(row, downloads)
    write(output/'published-previous-installers.json',evidence)
    # No release API calls after this point. Keep the repository token out of app/runtime processes.
    os.environ.pop('GH_TOKEN',None)
    os.environ.pop('GITHUB_TOKEN',None)
    old_install = work/'installed-previous'
    resources, app = install_native(target, downloads, old_install)
    split_rows = []
    seed = read(resources/'seed/runtime.json')
    if target.startswith('macos'):
        shutil.rmtree(downloads)  # The verified DMG parts are no longer needed once the app is copied.
        downloads.mkdir()
    else:
        setup, = downloads.glob('*Setup.exe')
        setup.unlink()
        seed_archive = resources/'seed'/seed['archive']
        split_rows = sorted((item for item in row['baseline_installers'] if '-Runtime.' in item['name']),key=lambda item:item['name'])
        if (seed_archive.stat().st_size == sum(item['bytes'] for item in split_rows)
                and sha(seed_archive) == seed['sha256']):
            for item in split_rows:
                (downloads/item['name']).unlink()
        else:
            split_rows = []  # Keep the original parts if the installed base cannot reconstruct them exactly.
    write(output/'post-baseline-disk.json',{'available':shutil.disk_usage(work).free,
                                           'windows_parts_recreated_after_upgrade':bool(split_rows)})
    old = read(resources/'update/runtime.json')
    assert old == row['baseline_manifest'], 'Installed previous core differs from the signed fixture'
    assert read(resources/'seed/runtime.json')['runtimeId'] == row['seed_base_runtime_id']
    alias = work/row['compatible']['name']
    selected = read(alias)
    descriptor = read(work/LOCK['launcher']['name'])
    for feed in (work/row['default']['name'],alias):
        verify_signature(resources,read(feed),descriptor)
    verify_signature(resources,old,descriptor)
    assert descriptor['coreCommit']==selected['commit']==LOCK['source_commit']
    assert selected['coreDelta']==row['delta']
    assert selected['sha256']==LOCK['core']['sha256']
    assert selected['baseRuntimeId']==row['seed_base_runtime_id']
    profile = work/'isolated-update-profile'
    memory=profile/'workspace'/MEMORY
    memory.parent.mkdir(parents=True)
    memory.write_bytes(MARKER)
    upgraded=probed_update(app,resources,profile,old,selected,work/row['default']['name'],
                          alias,work/row['delta']['archive'],output,target)
    assert memory.read_bytes()==MARKER
    recovered=recover(app,profile,old,output)
    write(output/'recovery.json',recovered)
    shutil.rmtree(profile)
    if split_rows:
        with seed_archive.open('rb') as stream:
            for item in split_rows:
                digest = sha256()
                remaining = item['bytes']
                with (downloads/item['name']).open('xb') as part:
                    while remaining:
                        block = stream.read(min(remaining,4*1024**2))
                        assert block, 'Installed seed ended before the locked installer boundary'
                        remaining -= len(block)
                        digest.update(block)
                        part.write(block)
                assert digest.hexdigest() == item['sha256'], item['name']
            assert not stream.read(1)
    replace_included_core(resources,work/LOCK['core']['name'],selected,descriptor,
                          {value['file']:value for value in descriptor['files']})
    native_media=work/'fresh-installer-media'
    media=prepare_candidate(target,'student-20261124-17bf2ce-native-qa',old_install,resources,downloads,
                            {'files':row['baseline_installers']},native_media,RECIPE)
    media_hashes=[{'file':file.name,'bytes':file.stat().st_size,'sha256':sha(file)} for file in media]
    fresh=work/'candidate-native-clean-install'
    resources,app=install_native(target,native_media,fresh)
    shutil.rmtree(native_media)
    fresh_profile=work/'fresh-synthetic-profile'
    fresh_profile.mkdir()
    assert sha(resources/'update'/selected['archive'])==LOCK['core']['sha256']
    candidate=boot(app,fresh_profile,output/'fresh-install.log')
    try:
        started=wait_ready(candidate,fresh_profile,selected)
    finally:
        stop(candidate)
    write(output/'native-acceptance.json',{'passed':True,'source_commit':LOCK['source_commit'],'core':LOCK['core'],
      'target':target,'runner':platform.machine(),'installer_media':media_hashes,
      'fresh_install':started,'update':upgraded,'recovery':recovered,'cos_used':False,
      'real_learning_data_used':False})


if __name__=='__main__':
    main()
