"""Promote only the Windows channel after the exact native repair passes."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest
import json
from pathlib import Path
import re
import runpy
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
REPO = '1281504089-cell/kaixin-k12-tutor'
BASE = 'student-20261121-resource-5'
TARGET = 'windows-x64'
HISTORY = 'core-updates-history-20261122-windows-startup-1'
SETUP = 'Kaixin-Super-Scholar-Windows-v1.7.1-Setup.exe'
SHARED = runpy.run_path(str(ROOT / 'resource5-release-helpers.py'), run_name='resource5_helpers')
api, gh = SHARED['api'], SHARED['gh']
inventory, require_assets = SHARED['inventory'], SHARED['require_assets']
read_asset, shape = SHARED['read_asset'], SHARED['shape']
ensure_asset, signed_target = SHARED['ensure_asset'], SHARED['signed_target']


def read(path):
    return json.loads(path.read_bytes())


def check_file(path, row):
    assert path.is_file() and path.stat().st_size == row['bytes'], path.name
    with path.open('rb') as handle:
        assert file_digest(handle, 'sha256').hexdigest() == row['sha256'], path.name


def existing(tag):
    try:
        return api('releases/tags/' + tag)
    except subprocess.CalledProcessError:
        return None


def public_feeds(lock):
    def each(item):
        name, spec = item
        raw = SHARED['get'](SHARED['COS'] + name)
        assert SHARED['size_hash'](raw) == shape(spec), name
        doc = json.loads(raw)
        signed_target(doc, TARGET)
        assert doc['commit'] == lock['source_commit'] and doc['corePayloadSha256'] == lock['core_sha256'], name
        return name, raw
    with ThreadPoolExecutor(max_workers=6) as pool:
        result = dict(pool.map(each, lock['feeds'].items()))
    SHARED['verify_signatures']([json.loads(raw) for raw in result.values()])
    assert result[lock['alias']] == result[lock['default']]
    return result


def native_proof(work, lock, approved):
    run = api(f"actions/runs/{approved['native_run']}")
    assert run['status'] == 'completed' and run['conclusion'] == 'success'
    assert run['head_branch'] == 'codex/verify-windows-startup-k12-18' and run['head_sha'] == approved['native_sha']
    assert run['path'].split('@')[0] == '.github/workflows/windows-startup-qa-k12-18.yml'
    assert run['head_repository']['full_name'] == REPO
    gh('run', 'download', run['id'], '--name', 'windows-startup-repair-real-install', '--dir', work, timeout=1350)
    proof = read(work / 'windows-acceptance.json')
    assert proof['source_commit'] == lock['source_commit'] and proof['core_sha256'] == lock['core_sha256']
    assert proof['run_id'] == run['id'] and proof['workflow_sha'] == run['head_sha'] and proof['target'] == TARGET
    assert all(proof[k] is True for k in ('passed', 'old_lock_reproduced', 'fresh_native_install', 'real_online_update',
        'signed_launcher_restarted', 'locked_recovery_and_reopen', 'original_data_preserved', 'signed_fallback_boot'))
    assert (work / 'reproduced-old-lock.txt').is_file()
    assert read(work / 'app.json')['current_core_included'] is True
    assert read(work / 'locked-workspace.json')['reopened_same_workspace'] is True
    assert read(work / 'online-windows.json')['signed_launcher_applied'] is True
    assert read(work / 'fallback-windows.json')['passed'] is True
    for path, row in lock['archives'].items():
        check_file(work / path, row)
        proof = read(work / (path + '.cos-receipt.json'))
        assert proof['verified'] and SHARED['shape'](proof) == row and proof['url'] == SHARED['COS'] + path
    proof = read(work / 'windows-acceptance.json')
    files = {row['file']: SHARED['shape'](row) for row in proof['full_files']}
    assert len(files) == 5 and SETUP in files
    check_file(work / SETUP, files[SETUP])
    return proof, files


def live_and_protected(lock, bodies):
    live = inventory(api('releases/tags/core-updates'))
    prior = {}
    protected = set(lock['archives']) | set(lock['feeds'])
    for target in ('macos-x64', 'macos-arm64', TARGET):
        name = 'runtime-' + target + '.json'
        raw = read_asset('core-updates', name, live[name])
        doc = json.loads(raw)
        signed_target(doc, target)
        protected.update((name, doc['archive']))
        for ref in doc['compatibleBaseManifests']:
            protected.add(ref['file'])
        if target == TARGET:
            assert doc in (lock['prior'], json.loads(bodies[name]))
        else:
            assert doc['commit'] == lock['prior']['commit']
        prior[name] = raw
    SHARED['verify_signatures']([json.loads(raw) for raw in prior.values()])
    return live, protected, prior


def publish():
    lock = read(ROOT / 'windows-stage-lock.json')
    approved = read(ROOT / 'windows-publication-gate.json')
    patch = (ROOT / 'source-from-resource-5.patch').read_bytes()
    source = SHARED['digest'](patch)
    assert approved['source_commit'] == lock['source_commit'] and approved['patch_sha256'] == source
    assert re.fullmatch(r'[a-f0-9]{40}', approved['source_carrier'])
    assert api('releases/latest')['tag_name'] == BASE
    bodies = public_feeds(lock)
    tag = lock['tag']
    with TemporaryDirectory(prefix='kaixin-windows-startup-') as scratch:
        work = Path(scratch)
        proof, files = native_proof(work, lock, approved)
        base_release = api('releases/tags/' + BASE)
        base_assets = inventory(base_release)
        require_assets(base_assets, {name: row for name, row in files.items() if name != SETUP})
        assert not SHARED['asset_matches'](base_assets[SETUP], files[SETUP])
        live, protected, previous = live_and_protected(lock, bodies)
        default = lock['default']
        pending = lock['archives'] | {name: row for name, row in lock['feeds'].items()
                                      if name not in {default, lock['alias']}}
        archive = SHARED['build_history_plan'](
            lock['source_commit'], live, pending, protected)
        SHARED['ensure_history'].__globals__['HISTORY'] = HISTORY
        history = SHARED['ensure_history'](work, {'source_carrier': approved['source_carrier']}, live, archive)
        stable = inventory(api('releases/tags/core-updates'))
        assert len(set(stable) | set(pending)) <= 1000
        for name in pending:
            if name not in stable:
                path = work / name
                if name in bodies:
                    path.write_bytes(bodies[name])
                gh('release', 'upload', 'core-updates', path, timeout=1250)
        require_assets(inventory(api('releases/tags/core-updates')), pending)

        install_links = {name: f'https://github.com/{REPO}/releases/download/{tag if name == SETUP else BASE}/{name}'
                         for name in files}
        receipt = {'published': True, 'tag': tag, 'target': TARGET, 'source_commit': lock['source_commit'],
                   'core_sha256': lock['core_sha256'], 'source_carrier': approved['source_carrier'],
                   'workflow_id': approved['native_run'], 'native_proof': proof, 'installers': files,
                   'installer_links': install_links, 'history': history}
        notes = work / 'release-notes.md'
        lines = ['## Windows x64 启动修复', '',
                 '修复安装后有时打不开、学习目录被占用时无法回滚，以及从备份恢复后更新入口不可用。', '',
                 '已安装且能打开的电脑，在应用内检查更新，按提示重开。软件打不开时用本页新版 Setup 覆盖安装，保留学习目录。',
                 '', '首次安装请把以下五个文件放在同一目录，保留原名，然后只运行 Setup。GitHub 无法访问时需要开 VPN。', '']
        lines += [f'- [{name}]({install_links[name]})' for name in [SETUP, *(sorted(set(files) - {SETUP}))]]
        notes.write_text('\n'.join(lines) + '\n', encoding='utf-8')

        release = existing(tag)
        if release is None:
            gh('release', 'create', tag, '--target', approved['source_carrier'], '--prerelease', '--latest=false',
               '--title', '开心动力超级学霸 Windows 启动修复', '--notes-file', notes)
            release = existing(tag)
        assert release['target_commitish'] == approved['source_carrier']
        for path in [work / SETUP, work / 'windows-acceptance.json', work / 'online-windows.json',
                     work / 'locked-workspace.json', work / 'fallback-windows.json',
                     *(work / (name + '.cos-receipt.json') for name in lock['archives']),
                     ROOT / 'source-from-resource-5.patch']:
            # gh run download delivers the exact native-produced installation and proof.
            assert path.is_file(), path
            rows = inventory(api('releases/tags/' + tag))
            with path.open('rb') as stream:
                expected = {'bytes': path.stat().st_size, 'sha256': file_digest(stream, 'sha256').hexdigest()}
            if path.name not in rows:
                gh('release', 'upload', tag, path, timeout=1250)
            require_assets(inventory(api('releases/tags/' + tag)), {path.name: expected})
        receipt['release_id'] = release['id']
        receipt_raw = (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode()
        rollback = previous[default]
        rollback_file = 'previous-' + default
        if rollback == bodies[default]:
            release_rows = inventory(api('releases/tags/' + tag))
            rollback = read_asset(tag, rollback_file, release_rows[rollback_file])
        assert json.loads(rollback) == lock['prior']
        ensure_asset(tag, work, rollback_file, rollback)
        ensure_asset(tag, work, 'PUBLICATION-RECEIPT.json', receipt_raw)

        stable_path = work / default
        try:
            if previous[default] != bodies[default]:
                stable_path.write_bytes(bodies[default])
                gh('release', 'upload', 'core-updates', stable_path, '--clobber')
            observed = inventory(api('releases/tags/core-updates'))
            assert read_asset('core-updates', default, observed[default]) == bodies[default]
            for name, before in previous.items():
                if name != default:
                    assert read_asset('core-updates', name, observed[name]) == before
            gh('release', 'edit', tag, '--prerelease=false', '--latest=false')
        except BaseException:
            if existing(tag)['prerelease']:
                stable_path.write_bytes(rollback)
                gh('release', 'upload', 'core-updates', stable_path, '--clobber')
                restored = inventory(api('releases/tags/core-updates'))
                assert read_asset('core-updates', default, restored[default]) == rollback
            raise
        live = api('releases/tags/' + tag)
        assert not live['draft'] and not live['prerelease'] and api('releases/latest')['tag_name'] == BASE
        previous_release = api('releases/tags/' + BASE)
        banner = f'**Windows 用户** 请使用 [Windows 启动修复正式版](https://github.com/{REPO}/releases/tag/{tag})。下方 Mac 安装文件继续使用。\n\n'
        old_notes = previous_release['body'] or ''
        if not old_notes.startswith(banner):
            notes.write_text(banner + old_notes, encoding='utf-8')
            gh('release', 'edit', BASE, '--notes-file', notes)
        assert api('releases/tags/' + BASE)['body'].startswith(banner)
        Path('PUBLICATION-RECEIPT.json').write_bytes(receipt_raw)
        print(tag, live['id'], flush=True)


if __name__ == '__main__':
    publish()
