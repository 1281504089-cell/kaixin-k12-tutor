"""Run the unmodified production updater through its real renderer IPC."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def migration_install(root, target, install, resources, home, evidence):
    helper = root / 'launcher-migration'
    (home / '.launcher-migration-synthetic.json').write_text('{"synthetic":true}')
    out = root / ('migration-' + target)
    source = resources.parent.parent if target.startswith('macos-') else install
    command = [sys.executable, str(helper / 'package_launcher.py'), '--target', target,
               '--final-installed-app-dir', str(source), '--existing-isolated-profile', str(home),
               '--baseline-manifest', str(root / 'migration-seeds' / ('runtime-' + target + '.json'))]
    if target == 'windows-x64':
        command += ['--makensis', str(Path(os.environ['ProgramFiles(x86)']) / 'NSIS/makensis.exe')]
    subprocess.run(command + ['--output-dir', str(out)], check=True, timeout=600)
    package_report = json.loads(next(out.glob('*-report.json')).read_text())
    artifact = out / package_report['artifact']
    assert package_report['testOnly'] is False
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == package_report['sha256']
    checkpoint = evidence / 'migration-before.json'
    subprocess.run([sys.executable, str(helper / 'verify_profile.py'), '--profile', str(home),
                    '--out', str(checkpoint)], check=True, timeout=300)
    fixed = root / ('fixed-entry' + ('.app' if target.startswith('macos-') else ''))
    shutil.copytree(source, fixed, ignore=lambda directory, names:
                    [name for name in names if name in {'seed', 'update'}] if Path(directory) == resources else [], symlinks=True)
    fixed_resources = fixed / 'Contents/Resources' if target.startswith('macos-') else fixed / 'resources'
    for old in (root / 'legacy-shell').rglob('*'):
        if old.is_file():
            shutil.copyfile(old, fixed_resources / 'app' / old.relative_to(root / 'legacy-shell'))
    (fixed_resources / 'app/src/update-network.mjs').unlink()
    failure_rejected = None
    if target.startswith('macos-'):
        rollback = fixed.with_name('fixed-entry.rollback.app')
        fixed.rename(rollback)
        extracted = root / 'migration-extracted'
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(artifact), str(extracted)], check=True)
        (extracted / '开心动力超级学霸.app').rename(fixed)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(fixed)], check=True)
    else:
        test_out = root / 'migration-test-only'
        subprocess.run(command + ['--output-dir', str(test_out), '--test-installer'], check=True, timeout=600)
        setup = next(test_out.glob('*-Setup.exe'))
        bad_home = root / 'missing-profile'
        result = subprocess.run('"' + str(setup) + '" /S /D=' + str(fixed),
                                env={**os.environ, 'OPEN_DEEPTUTOR_TEST_HOME': str(bad_home)}, timeout=180)
        assert result.returncode != 0
        failure_rejected = True
        result = subprocess.run('"' + str(setup) + '" /S /D=' + str(fixed),
                                env={**os.environ, 'OPEN_DEEPTUTOR_TEST_HOME': str(home),
                                     'KX_MIGRATION_CHECK_REPORT': str(evidence / 'migration-installer-check.json')}, timeout=600)
        if result.returncode != 0:
            diagnostics = sorted(evidence.glob('migration-installer-check*.json'))
            print('\n'.join(file.read_text() for file in diagnostics) if diagnostics else 'Installer failed before the native checker', flush=True)
        assert result.returncode == 0, 'Migration installer failed, exit code ' + str(result.returncode)
        rollback = fixed.with_name(fixed.name + '.launcher-' + package_report['frozenShellCommit'][:12] + '.rollback')
        assert rollback.is_dir()
        shutil.rmtree(test_out)
    for name in ['main.mjs', 'release-updates.mjs', 'update-network.mjs']:
        assert (fixed_resources / 'app/src' / name).read_bytes() == (resources / 'app/src' / name).read_bytes()
    preservation = evidence / 'migration-preservation.json'
    subprocess.run([sys.executable, str(helper / 'verify_profile.py'), '--profile', str(home),
                    '--before', str(checkpoint), '--out', str(preservation)], check=True, timeout=300)
    package_report.update(nativeMigration='passed', fixed_entry_replaced=True, rollback_retained=True,
                          missing_profile_rejected=failure_rejected,
                          windows_installer_test_mode=target == 'windows-x64',
                          data_preservation=json.loads(preservation.read_text()))
    return fixed, fixed_resources, out, package_report, rollback


def verify_update_entry(root, target, install, resources, home, evidence):
    active = json.loads((home / 'active.json').read_text())
    base = json.loads((resources / 'seed/runtime.json').read_text())
    native = home / 'runtimes' / base['runtimeId']
    python = native / ('python/python.exe' if target == 'windows-x64' else 'python/bin/python3')
    fixture = home / 'migration-fixture.json'

    def python_probe(code, manifest=active):
        source = home / 'runtimes' / manifest['runtimeId'] / 'core'
        result = subprocess.check_output([str(python), '-c', code], env={**os.environ,
            'PYTHONPATH': str(source), 'DEEPTUTOR_HOME': str(home / 'workspace'),
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}, timeout=90)
        return json.loads(result.decode('utf-8').strip().splitlines()[-1])

    seeded = python_probe('''
import asyncio,json
from deeptutor.services.session import get_session_store
from deeptutor.services.task_board import get_task_board_store,CreateCard
from deeptutor.services.config.model_catalog import get_model_catalog_service
async def run():
 s=get_session_store();r=await s.create_session(title='before launcher migration');await s.add_message(r['id'],'user','synthetic existing learning record')
 task=get_task_board_store().create(CreateCard(title='synthetic existing task'),'').cards[-1]
 c=get_model_catalog_service();d=c.load();d['services']['llm']={'active_profile_id':'fixture','active_model_id':'fixture','profiles':[{'id':'fixture','name':'fixture','binding':'openai','base_url':'http://127.0.0.1:9/v1','api_key':'fixture-only-not-a-real-key','models':[{'id':'fixture','model':'gpt-4o-mini','name':'fixture'}]}]};c.save(d)
 return {'session_id':r['id'],'task_id':task.id}
print(json.dumps(asyncio.run(run())))
''')
    fixture.write_text(json.dumps(seeded))
    assert json.loads((native / 'installed.json').read_text()) == base
    (home / 'active.json').write_text(json.dumps(base))
    probe, probe_resources, migration_out, migration_report, rollback = migration_install(
        root, target, install, resources, home, evidence)
    pkg_file = probe_resources / 'app/package.json'
    pkg = json.loads(pkg_file.read_text())
    pkg['main'] = 'src/update-flow.cjs'
    pkg_file.write_text(json.dumps(pkg, ensure_ascii=False))
    shutil.copyfile(root / 'ci-update-flow.cjs', probe_resources / 'app/src/update-flow.cjs')
    for name in ['main.mjs', 'release-updates.mjs', 'update-network.mjs']:
        assert hashlib.sha256((probe_resources / 'app/src' / name).read_bytes()).digest() == hashlib.sha256((resources / 'app/src' / name).read_bytes()).digest()
    if target.startswith('macos-'):
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(probe)], check=True)
        executable = probe / 'Contents/MacOS/开心动力超级学霸'
    else:
        executable = probe / '开心动力超级学霸.exe'
    subprocess.run([str(executable)], env={**os.environ, 'OPEN_DEEPTUTOR_TEST_HOME': str(home),
                   'KX_UPDATE_FLOW_RESULT': str(evidence / 'update-entry.json')}, check=True, timeout=1000)
    after = json.loads((home / 'active.json').read_text())
    code = '''
import asyncio,json,os
from pathlib import Path
from deeptutor.services.session import get_session_store
from deeptutor.services.task_board import get_task_board_store
from deeptutor.services.config.model_catalog import get_model_catalog_service
fixture=json.loads((Path(os.environ['DEEPTUTOR_HOME']).parent/'migration-fixture.json').read_text())
async def run():
 session=await get_session_store().get_session_with_messages(fixture['session_id'])
 return {'chat_preserved':any(m.get('content')=='synthetic existing learning record' for m in session['messages']), 'task_preserved':any(c.id==fixture['task_id'] and c.title=='synthetic existing task' for c in get_task_board_store().read().cards), 'saved_key_preserved':'fixture-only-not-a-real-key' in json.dumps(get_model_catalog_service().load())}
r=asyncio.run(run());assert all(r.values()),r;print(json.dumps(r))
'''
    preserved = python_probe(code, after)
    report_file = evidence / 'update-entry.json'
    report = json.loads(report_file.read_text())
    report.update(preserved)
    report_file.write_text(json.dumps(report, indent=2))
    migration_report['nativeUpdateUI'] = report
    next(migration_out.glob('*-report.json')).write_text(json.dumps(migration_report, ensure_ascii=False, indent=2))
    shutil.rmtree(probe)
    shutil.rmtree(rollback)
    return report, migration_out, migration_report
