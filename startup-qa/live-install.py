"""Prove the Windows preview on its native OS before any official release mutation."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import json
from hashlib import sha256
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.request import Request, urlopen

from ci_fresh_install import digest, download, metadata, verify_signature, workload_valid
from ci_repackage import install_native, prepare_candidate, read, replace_included_core, run, write

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'real-proof'
BASE = read(ROOT / 'windows-baseline.json')
LOCK = read(ROOT / 'windows-stage-lock.json')
DESCRIPTOR = read(ROOT / 'launcher-manifest.json')
COS = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com'
TARGET = 'windows-x64'
MEMORY = Path('data/user/memory/L3/profile.md')
MEMORY_BYTES = '隔离验收记录 2026-11-22 Windows 已学平行四边形\n'.encode('utf-8')


def mirror(name, folder):
    expected = (LOCK['archives'] | LOCK['feeds'])[name]
    file = folder / name
    amount = 0
    first = None
    sha = sha256()
    request = Request(COS + '/desktop/' + name, headers={'User-Agent': 'Kaixin isolated native Windows QA'})
    with urlopen(request, timeout=65) as response, file.open('xb') as sink:
        assert response.status == 200 and response.geturl() == request.full_url
        anchor = {key: response.headers.get(header) for key, header in (
            ('version', 'x-cos-version-id'), ('etag', 'ETag'), ('last_modified', 'Last-Modified'))}
        while block := response.read(4 << 20):
            if first is None:
                first = block[:1].hex()
            amount += len(block)
            assert amount <= expected['bytes']
            sha.update(block)
            sink.write(block)
    assert amount == expected['bytes'] and sha.hexdigest() == expected['sha256'], name
    write(OUTPUT / (name + '.cos-receipt.json'), {'verified': True, 'url': request.full_url,
          'bytes': amount, 'sha256': sha.hexdigest(), 'first_byte': first, **anchor})
    return file


def memory(root):
    return (root / MEMORY).read_bytes()


def stop(process):
    if process.poll() is None:
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], check=False, capture_output=True)
        process.wait(timeout=25)


def spawn(executable, home, **env):
    return subprocess.Popen([str(executable)], cwd=executable.parent, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env={**os.environ,
                            'OPEN_DEEPTUTOR_TEST_HOME': str(home), **env})


def read_since(log, offset):
    if not log.exists():
        return ''
    with log.open('rb') as stream:
        stream.seek(offset)
        return stream.read().decode('utf-8', 'replace')


def wait_for(check, label, seconds=300):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value is not None and value is not False:
            return value
        time.sleep(1)
    raise TimeoutError(label)


def app_ready(process, home, offset, commit):
    log = read_since(home / 'logs/runtime.log', offset)
    assert process.poll() is None, ('Installed app exited', log[-1400:])
    assert 'Desktop startup failed:' not in log, log[-1400:]
    frontend = re.search(r'Local:\s+(http://127\.0\.0\.1:\d+)', log)
    active = home / 'active.json'
    if not frontend or not active.exists() or read(active).get('commit') != commit:
        return
    try:
        with urlopen(frontend[1] + '/chat', timeout=12) as response:
            if response.status == 200:
                return frontend[1]
    except OSError:
        return


@contextmanager
def lock_learning_file(file):
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.CreateFileW(str(file), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        api.CloseHandle(handle)


def interrupted(home):
    active = read(home / 'active.json')
    backup = home / 'backups/before-locked-startup-qa'
    memory_file = backup / MEMORY
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_bytes(MEMORY_BYTES)
    active_file = home / 'workspace' / MEMORY
    active_file.write_bytes(b'locked interrupted learning sentinel')
    task = home / 'upgrade.json'
    write(task, {'phase': 'testing', 'previous': active, 'candidate': active, 'backup': str(backup)})
    return active_file, backup, task


def check_prior_lock(executable, home):
    file, backup, tx = interrupted(home)
    log = home / 'logs/runtime.log'
    before = log.stat().st_size
    with lock_learning_file(file):
        app = spawn(executable, home)
        try:
            def failure():
                current = read_since(log, before)
                if 'Desktop startup failed:' in current:
                    assert any(code in current for code in ('EPERM', 'EBUSY', 'EACCES')), current[-1500:]
                    return current
            evidence = wait_for(failure, 'R5 startup failure with a native Windows deny-delete handle', 65)
            assert read(tx)['phase'] == 'testing' and memory(backup) == MEMORY_BYTES
            assert not (home / 'workspace-location.json').exists()
        finally:
            stop(app)
    file.write_bytes(MEMORY_BYTES)
    tx.unlink()
    (OUTPUT / 'reproduced-old-lock.txt').write_text(evidence, encoding='utf-8')


def check_recovery(executable, home):
    file, backup, tx = interrupted(home)
    log = home / 'logs/runtime.log'
    result = {}
    with lock_learning_file(file):
        for attempt in range(2):
            offset = log.stat().st_size
            app = spawn(executable, home)
            try:
                frontend = wait_for(lambda: app_ready(app, home, offset, LOCK['source_commit']),
                                    'candidate app ready while original workspace remains locked')
                location = read(home / 'workspace-location.json')
                restored = home / location['name']
                assert re.fullmatch(r'workspace-recovered-\d{13}', location['name'])
                assert read(tx)['phase'] == 'recovered'
                assert memory(restored) == memory(backup) == MEMORY_BYTES
                assert file.read_bytes() == b'locked interrupted learning sentinel'
                with urlopen(frontend + '/api/student/desktop-update/status', timeout=20) as response:
                    launcher = json.load(response)
                    assert launcher['available'] and launcher['build_id'] == DESCRIPTOR['buildId'], launcher
                with urlopen(frontend + '/api/student/desktop-update/installed-build', timeout=20) as response:
                    assert json.load(response)['source_commit'] == LOCK['source_commit']
                if attempt == 0:
                    result = dict(loaded_workspace=location['name'], original_preserved=True,
                                  backup_preserved=True, launcher_status_available=True)
                else:
                    assert location['name'] == result['loaded_workspace']
                    result['reopened_same_workspace'] = True
            finally:
                stop(app)
    result['learning_sha256'] = sha256(MEMORY_BYTES).hexdigest()
    write(OUTPUT / 'locked-workspace.json', result)


def check_update(resources, executable, home, baseline, feed, selected):
    report = OUTPUT / 'online-windows.json'
    spec = ROOT / 'probe.json'
    delta = selected['coreDelta']
    write(spec, {'report': str(report), 'target': TARGET, 'channel': 'cos', 'tag': LOCK['tag'],
        'cosOrigin': COS, 'defaultFile':LOCK['default'], 'alias':LOCK['alias'], 'baseline':baseline,
        'selected':selected, 'descriptor':DESCRIPTOR, 'delta_output':str(OUTPUT / delta['archive']), 'delta': {'name':delta['archive'], 'bytes':delta['bytes'],
        'sha256':delta['sha256']}, 'manifest': {'name': feed, **LOCK['feeds'][feed]}})
    package = resources / 'app/package.json'
    original = package.read_bytes()
    probe = package.parent / 'windows-update-probe.cjs'
    shutil.copyfile(ROOT / probe.name, probe)
    write(package, {**read(package), 'main':probe.name})
    app = spawn(executable, home, KX_DIAGRAM_PROBE=str(spec))
    try:
        def completed():
            failure = report.with_suffix('.json.error')
            if failure.exists():
                raise RuntimeError(failure.read_text(encoding='utf-8'))
            return read(report) if report.exists() else None
        row = wait_for(completed, 'actual window update and signed launcher restart', 840)
        assert row['passed'] and row['checked_again'] and row['restarted'] and row['signed_launcher_applied']
        assert row['commit'] == LOCK['source_commit'] and memory(home / 'workspace') == MEMORY_BYTES
        assert digest(OUTPUT / delta['archive']) == delta['sha256']
        write(OUTPUT / (delta['archive'] + '.cos-receipt.json'), row['delta_anchor'])
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        restarted = api.OpenProcess(0x100000, False, row['reopened_pid'])
        if restarted:
            try:
                assert api.WaitForSingleObject(restarted, 25000) == 0, 'updated app still running'
            finally:
                api.CloseHandle(restarted)
        else:
            assert ctypes.get_last_error() == 87, 'could not verify that the updated app exited'
    finally:
        stop(app)
        package.write_bytes(original)
        probe.unlink()


def main():
    assert os.name == 'nt' and platform.machine() == 'AMD64'
    assert LOCK['source_commit'] == DESCRIPTOR['coreCommit']
    assert LOCK['prior']['commit'] == BASE['core_commit']
    OUTPUT.mkdir()
    work = Path(os.environ['RUNNER_TEMP']) / 'Windows 启动原样验收'
    work.mkdir()
    files = work / 'R5 public installers'
    files.mkdir()
    release = metadata(BASE['tag'])
    assert release['id'] == BASE['release_id'] and not release['draft'] and not release['prerelease']
    downloads = [download(release, row, files / row['name']) for row in BASE['files']]
    old_install = work / '旧版安装'
    resources, executable = install_native(TARGET, files, old_install)
    baseline = read(resources / 'update/runtime.json')
    assert (baseline['commit'], baseline['sha256'], baseline['runtimeId']) == (
        BASE['core_commit'], BASE['core_sha256'], BASE['runtime_id'])
    home = work / '学生合成学习记录'
    m = home / 'workspace' / MEMORY
    m.parent.mkdir(parents=True)
    m.write_bytes(MEMORY_BYTES)
    app = spawn(executable, home)
    try:
        wait_for(lambda: app_ready(app, home, 0, BASE['core_commit']), 'R5 fixture first boot', 850)
    finally:
        stop(app)
    check_prior_lock(executable, home)
    signed_root = read(mirror(LOCK['alias'], work))
    assert signed_root['commit'] == LOCK['source_commit']
    named = next(ref['file'] for ref in signed_root['compatibleBaseManifests']
                 if ref['baseRuntimeId'] == BASE['base_runtime_id'])
    selected = read(mirror(named, work))
    assert selected['sha256'] == LOCK['core_sha256'] and selected['commit'] == LOCK['source_commit']
    verify_signature(resources, selected, DESCRIPTOR)
    check_update(resources, executable, home, baseline, named, selected)

    core_file = mirror(selected['archive'], work)
    os.link(core_file, OUTPUT / core_file.name)
    replace_included_core(resources, core_file, selected, DESCRIPTOR,
                          {row['file']: row for row in DESCRIPTOR['files']})
    nsis = Path(os.environ['ProgramFiles(x86)']) / 'NSIS/makensis.exe'
    if not nsis.exists():
        run('choco', 'install', 'nsis', '--no-progress', '-y', timeout=500)
    output = work / 'candidate installers'
    installers = prepare_candidate(TARGET, LOCK['tag'], old_install, resources, files, BASE, output, ROOT)
    installed = work / '新装测试 使用较长的中文路径'
    resources, executable = install_native(TARGET, output, installed)
    assert workload_valid(resources, executable, selected, DESCRIPTOR)
    check_recovery(executable, home)
    shutil.rmtree(home)

    fresh = work / '全新学生资料 用户一'
    run('node', ROOT / 'ci-fresh-smoke.mjs', executable, resources, fresh, OUTPUT, cwd=ROOT, timeout=940,
        env={**os.environ, 'KX_EXPECTED_PLATFORM': 'win32', 'KX_EXPECTED_ARCH': 'x64'})
    assert read(OUTPUT / 'app.json')['core_commit'] == LOCK['source_commit']
    shutil.rmtree(fresh)
    bridge_file = mirror(signed_root['archive'], work)
    os.link(bridge_file, OUTPUT / bridge_file.name)
    seed = resources / 'seed'
    existing = read(seed / 'runtime.json')
    (seed / existing['archive']).unlink()
    shutil.rmtree(resources / 'update')
    shutil.move(bridge_file, seed / bridge_file.name)
    write(seed / 'runtime.json', signed_root)
    fallback = work / '签名整包回退'
    fallback.mkdir()
    app = spawn(executable, fallback)
    try:
        wait_for(lambda: app_ready(app, fallback, 0, LOCK['source_commit']), 'signed universal fallback starts', 800)
        assert read(fallback / 'active.json') == signed_root
    finally:
        stop(app)
    write(OUTPUT / 'fallback-windows.json', {'passed':True, 'commit':LOCK['source_commit'],
          'archive':signed_root['archive'], 'sha256':signed_root['sha256'], 'runtime':signed_root['runtimeId']})
    records = [{'file': artifact.name, 'bytes': artifact.stat().st_size, 'sha256': digest(artifact)}
               for artifact in installers]
    setup, = [file for file in installers if file.name.endswith('Setup.exe')]
    for record in records:
        if '-Runtime.' in record['file']:
            expected = next(row for row in BASE['files'] if row['name'] == record['file'])
            assert (record['bytes'], record['sha256']) == (expected['bytes'], expected['sha256'])
    shutil.move(setup, OUTPUT / setup.name)
    write(OUTPUT / 'windows-acceptance.json', {'passed': True, 'target': TARGET,
          'source_commit': LOCK['source_commit'], 'core_sha256': LOCK['core_sha256'],
          'launcher_build': DESCRIPTOR['buildId'], 'run_id': int(os.environ['GITHUB_RUN_ID']),
          'workflow_sha': os.environ['GITHUB_SHA'], 'old_lock_reproduced': True,
          'fresh_native_install': True, 'real_online_update': True, 'signed_launcher_restarted': True,
          'locked_recovery_and_reopen': True, 'original_data_preserved': True, 'signed_fallback_boot': True,
          'full_files': records, 'old_source_downloads': downloads})
    for receipt in ('windows-acceptance.json', 'locked-workspace.json', 'fallback-windows.json',
                    *(name + '.cos-receipt.json' for name in LOCK['archives'])):
        print('WINDOWS_QA_PROOF', receipt, (OUTPUT / receipt).read_text(encoding='utf-8').replace('\n',''), flush=True)
    print('PASS Windows fresh install, real update with launcher replacement, locked workspace recovery, and signed fallback.',
          flush=True)


if __name__ == '__main__':
    main()
