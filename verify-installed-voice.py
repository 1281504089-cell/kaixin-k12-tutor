"""Check the installed voice transport without credentials or external calls."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--profile', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
active = json.loads((args.profile / 'active.json').read_text(encoding='utf-8'))
for name in ['runtimeId', 'baseRuntimeId']:
    if name in active and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', active[name]):
        raise ValueError('Invalid installed runtime identifier')
runtime = args.profile / 'runtimes' / active['runtimeId']
base = args.profile / 'runtimes' / active.get('baseRuntimeId', active['runtimeId'])
python = base / ('python/python.exe' if sys.platform == 'win32' else 'python/bin/python3')
with tempfile.TemporaryDirectory(prefix='voice-installed-') as temporary:
    env = {**os.environ, 'PYTHONPATH': str(runtime / 'core'), 'DEEPTUTOR_HOME': temporary,
           'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    version = subprocess.check_output([str(python), '-c',
        'import python_socks; from python_socks.async_.asyncio import Proxy; '
        'import deeptutor.services.voice.realtime_tutor as voice; from pathlib import Path; import sys; '
        'assert Path(voice.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()); '
        'assert callable(Proxy.from_url); print(python_socks.__version__)', str(runtime / 'core')],
        cwd=temporary, env=env, text=True).strip()
    assert version == '3.2.1', version
    result = subprocess.run([str(python), str(args.source / 'tests/services/test_moss_realtime.py'), '-q'],
                            cwd=temporary, env=env, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    result.check_returncode()
    count = re.search(r'Ran (\d+) tests?', result.stdout + result.stderr)
    assert count and 'skipped=' not in result.stdout + result.stderr, 'Voice checks were skipped'
report = {'runtime': active['runtimeId'], 'pythonSocks': version, 'voiceRegressionTests': int(count[1]),
          'socksWebSocketRoundTrip': 'passed', 'usesInstalledRuntime': True,
          'externalApiCalls': False, 'realKeysUsed': False}
args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report), flush=True)
