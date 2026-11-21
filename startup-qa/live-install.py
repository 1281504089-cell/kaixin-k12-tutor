"""Exercise the actual publicly released Windows installer plus the USB repair."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.request import urlopen

from ci_fresh_install import download
from ci_repackage import install_native

root = Path(__file__).resolve().parent
metadata = json.loads((root/'published-windows-assets.json').read_bytes())
proof = root/'real-proof'
proof.mkdir()
work = Path(os.environ['RUNNER_TEMP'])/'k12-18 Windows repair'
work.mkdir()
powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
env = dict(os.environ)
env.pop('PSMODULEPATH', None)
subprocess.run([str(powershell), '-NoProfile', '-Command',
                "Get-Command Get-FileHash -ErrorAction Stop | Out-Null"], env=env, check=True, timeout=20)

downloads = work/'public installers'
downloads.mkdir()
receipts = []
for row in metadata['windows']:
    receipts.append(download(metadata['release'], row, downloads/row['name']))
(proof/'public-download.json').write_text(json.dumps(receipts,indent=2))
resources, executable = install_native('windows-x64', downloads, work/'已安装应用')
assert executable.is_file()
target = resources/'app/src/bundles.mjs'
assert target.read_bytes() == (root/'original-bundles.mjs').read_bytes()
shutil.rmtree(downloads)
profile = work/'中文学习账号'
learning = profile/'workspace/data/user/memory/L3/profile.md'
learning.parent.mkdir(parents=True)
learning.write_text('isolated synthetic learning history')
env['OPEN_DEEPTUTOR_TEST_HOME'] = str(profile)
proc = subprocess.run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'repair/repair.ps1'),
                       '-AppDirectory',str(executable.parent)],env=env,capture_output=True,timeout=40)
(proof/'repair-console.log').write_bytes(proc.stdout+proc.stderr)
assert proc.returncode==0, repr(proc.stdout+proc.stderr)
assert (target.parent/'main.mjs').read_bytes() == (root/'repair/main.mjs').read_bytes()
assert target.read_bytes() == (root/'repair/bundles.mjs').read_bytes()
assert target.with_name('bundles.mjs.before-k12-18-recovery').read_bytes() == (root/'original-bundles.mjs').read_bytes()
started = time.monotonic()
log = profile/'logs/runtime.log'
try:
    while time.monotonic() - started < 600:
        text = log.read_text(encoding='utf-8',errors='replace') if log.exists() else ''
        assert 'Desktop startup failed:' not in text, text[-5000:]
        active = profile/'active.json'
        frontend=re.search(r'Local:\s+(http://127\.0\.0\.1:\d+)',text)
        backend=re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)',text)
        if active.exists() and frontend and backend:
            installed = json.loads(active.read_bytes())
            assert installed['commit']==metadata['source_commit']
            with urlopen(backend[1]+'/health/ready',timeout=12) as response: assert response.status==200
            with urlopen(frontend[1]+'/chat',timeout=12) as response: assert response.status==200
            assert learning.read_text() == 'isolated synthetic learning history'
            (proof/'PASSED.json').write_text(json.dumps({
                'passed':True,'platform':'windows-x64','installed_runtime':installed['runtimeId'],
                'source_commit':installed['commit'],'existing_learning_data_retained':True,
                'boot_seconds':round(time.monotonic()-started,2),'repair_sha256':sha256(target.read_bytes()).hexdigest(),
                'archive_sha256_verified_by_installed_app':True,'run_id':os.environ['GITHUB_RUN_ID'],
            },indent=2))
            break
        time.sleep(2)
    else:
        raise RuntimeError('The repaired app did not reach its local chat')
finally:
    if log.exists(): shutil.copyfile(log,proof/'runtime.log')
