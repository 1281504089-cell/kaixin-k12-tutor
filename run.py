"""Native test runner for the two already-signed COS updates."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from threading import Thread
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence'
COS = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
REPO = 'https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/'
APP = '开心动力超级学霸'
WINDOWS = sys.platform == 'win32'


def read(file):
    return json.loads(file.read_bytes())


def write(file, body):
    file.write_text(json.dumps(body, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def run(*args, **kwargs):
    return subprocess.run([str(value) for value in args], check=True, **kwargs)


def sha(file):
    with file.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def install_part(row, folder):
    target = folder / row['name']
    assert row['url'].startswith(REPO) and row['url'].endswith('/' + target.name)
    run('curl.exe' if WINDOWS else '/usr/bin/curl', '--fail', '--silent', '--show-error', '--location',
        '--proto', '=https', '--proto-redir', '=https', '--max-redirs', '4',
        '--connect-timeout', '20', '--max-time', '1600', '--retry', '4', '--max-filesize', row['bytes'],
        '--output', target, row['url'], timeout=2400)
    assert target.stat().st_size == row['bytes'] and sha(target) == row['sha256'], target.name
    print(f'Previous installer part verified from GitHub: {target.name}', flush=True)
    return target


def install_previous(files, work):
    install = work / 'installed'
    install.mkdir()
    if WINDOWS:
        setup, = [path for path in files if path.suffix == '.exe']
        subprocess.run(f'"{setup}" /S /D={install}', timeout=1300, check=True)
        return install / 'resources', install / (APP + '.exe')
    image, = [path for path in files if path.suffix == '.dmg']
    mount = work / 'mount'
    mount.mkdir()
    run('/usr/bin/hdiutil', 'verify', image, timeout=400)
    run('/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', mount, image, timeout=400)
    app = install / (APP + '.app')
    try:
        run('/usr/bin/ditto', mount / app.name, app, timeout=900)
    finally:
        for attempt in range(3):
            detached = subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount)], capture_output=True)
            if detached.returncode == 0:
                break
            time.sleep(3)
        assert detached.returncode == 0, detached.stderr
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app, timeout=450)
    return app / 'Contents/Resources', app / 'Contents/MacOS' / APP


def public_get(name, limit, digest, size=None):
    if name.endswith('.json'):
        assert name.startswith('runtime-') and limit <= 16_000
    else:
        assert name.startswith('kaixin-core-delta-') and name.endswith('.tar.gz') and limit <= 8 * 1024**2
    assert '/' not in name
    url = COS + name
    request = Request(url, headers={'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'})
    with urlopen(request, timeout=18) as response:
        assert response.status == 200 and response.geturl() == url
        announced = int(response.headers['Content-Length'])
        assert 0 < announced <= limit and (size is None or announced == size)
        payload = response.read(announced + 1)
    assert len(payload) == announced and sha256(payload).hexdigest() == digest, name
    print(f'COS lightweight readback: {name}, {announced} bytes', flush=True)
    return payload


def stage_feed(target, plan, baseline):
    name = 'runtime-' + target + '.json'
    stable = public_get(name, 16000, plan['stable_sha256'])
    current = json.loads(stable)
    assert current['commit'] == plan['final_commit']
    base_runtime = baseline.get('baseRuntimeId', baseline['runtimeId'])
    entry, = [item for item in current['compatibleBaseManifests'] if item['baseRuntimeId'] == base_runtime]
    child_name = entry['file']
    child = public_get(child_name, 16000, plan['compatibility'][child_name])
    selected = json.loads(child)
    assert selected['baseRuntimeId'] == base_runtime and selected['commit'] == current['commit']
    delta = selected['coreDelta']
    assert delta['fromCoreSha256'] == plan['previous']['corePayloadSha256']
    assert delta['toCoreSha256'] == selected['corePayloadSha256'] == current['corePayloadSha256']
    archive = delta['archive']
    payload = public_get(archive, 8 * 1024**2, delta['sha256'], delta['bytes'])
    report = {'stable': name, 'stable_sha256': plan['stable_sha256'], 'selected': child_name,
              'selected_sha256': plan['compatibility'][child_name], 'delta': delta,
              'network_bytes': len(stable) + len(child) + len(payload)}
    write(EVIDENCE / 'cos-lightweight.json', report)
    return current, selected, {name: stable, child_name: child, archive: payload}, report


def run_app(target, plan, baseline, resources, executable, work):
    current, selected, files, cos = stage_feed(target, plan, baseline)
    class Feed(BaseHTTPRequestHandler):
        def do_GET(self):
            raw = files.get(self.path.removeprefix('/'))
            if raw is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    app = resources / 'app'
    shutil.copyfile(ROOT / 'probe.cjs', app / 'probe.cjs')
    package = app / 'package.json'
    write(package, {**read(package), 'main': 'probe.cjs'})
    if not WINDOWS:
        bundle = executable.parents[2]
        run('/usr/bin/codesign', '--force', '--sign', '-', bundle, timeout=450)
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', bundle, timeout=450)
    home = work / 'isolated-learning'
    result = EVIDENCE / 'native-update.json'
    spec_path = work / 'probe.json'
    with ThreadingHTTPServer(('127.0.0.1', 0), Feed) as server:
        Thread(target=server.serve_forever, daemon=True).start()
        write(spec_path, {'target': target, 'baseline': baseline, 'current': current, 'selected': selected,
                          'cos': cos, 'launcher': plan['launcher'],
                          'origin': f'http://127.0.0.1:{server.server_port}', 'result': str(result)})
        env = {**os.environ, 'OPEN_DEEPTUTOR_TEST_HOME': str(home), 'KX_QA_SPEC': str(spec_path)}
        with (EVIDENCE / 'app.log').open('wb') as log:
            process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 1750
                failure = result.with_suffix('.error.txt')
                while time.monotonic() < deadline:
                    if failure.exists():
                        raise RuntimeError(failure.read_text(encoding='utf8'))
                    if result.exists():
                        proof = read(result)
                        assert proof['passed'] and proof['learning_record_reopened'] and proof['restarted']
                        print(json.dumps(proof, ensure_ascii=False), flush=True)
                        return
                    time.sleep(2)
                raise TimeoutError('Native update and restart receipt never arrived')
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                logfile = home / 'logs/runtime.log'
                if logfile.exists():
                    shutil.copyfile(logfile, EVIDENCE / 'runtime.log')
                server.shutdown()


def main():
    target = sys.argv[1]
    expected = 'AMD64' if target == 'windows-x64' else 'arm64'
    assert platform.machine() == expected and sys.platform == ('win32' if target == 'windows-x64' else 'darwin')
    EVIDENCE.mkdir()
    work = Path(os.environ['RUNNER_TEMP']) / 'scholar-native-qa'
    work.mkdir()
    folder = work / 'previous-installers'
    folder.mkdir()
    plan = read(ROOT / 'plan.json')[target]
    with ThreadPoolExecutor(3) as pool:
        files = list(pool.map(lambda item: install_part(item, folder), plan['installers']))
    resources, exe = install_previous(files, work)
    baseline = read(resources / 'update/runtime.json')
    assert all(baseline[field] == expected for field, expected in plan['previous'].items()), target
    base = resources / 'update' / baseline['archive']
    assert sha(base) == baseline['sha256']
    write(EVIDENCE / 'previous-installed.json', {'target': target, 'runtime': baseline['runtimeId'],
                                                  'core_sha256': baseline['corePayloadSha256']})
    shutil.rmtree(folder)
    run_app(target, plan, baseline, resources, exe, work)


if __name__ == '__main__':
    main()
