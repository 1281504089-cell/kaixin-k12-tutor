"""Create an isolated test input from owner-frozen, already-signed release inputs."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('scenario', choices=['migration', 'cos', 'fallback'])
p.add_argument('target', choices=['windows-x64', 'macos-x64', 'macos-arm64'])
p.add_argument('--baseline', required=True, type=Path)
p.add_argument('--candidate', required=True, type=Path)
p.add_argument('--old-launcher', required=True, type=Path)
p.add_argument('--new-launcher', required=True, type=Path)
p.add_argument('--cos-manifest', type=Path, help='exact downloaded bytes under the selected object name, required for COS/fallback')
p.add_argument('--stage-github', action='store_true', help='route stable GitHub requests to its accessible candidate tag for preflight')
p.add_argument('--github-archive-id', type=int, help='actual stable download asset ID if different from the candidate ID')
p.add_argument('--out', required=True, type=Path)
a = p.parse_args()
read = lambda f: json.loads(f.read_bytes())
old, new = read(a.baseline), read(a.candidate)
prev, selected = old['manifests'][a.target], new['manifests'][a.target]
launchers = {x['buildId']: x for x in (read(a.old_launcher), read(a.new_launcher))}
assert old['tag'] == 'student-20261117-k12-11' and new['tag'] == 'student-20261117-k12-12'
assert prev['builtAt'] < selected['builtAt'] and prev['baseRuntimeId'] == selected['baseRuntimeId']
for batch, manifest, launcher in ((old, prev, '20261118-updater-5'), (new, selected, '20261119-updater-6')):
    asset = batch['core_asset']
    assert batch['launcher_build'] == launcher and launchers[launcher]['coreCommit'] == manifest['commit'] == batch['core_commit']
    assert asset['name'] == manifest['archive'] and asset['digest'] == 'sha256:' + manifest['sha256']
    assert asset['size'] > 0
assert bool(a.cos_manifest) == (a.scenario != 'migration')
assert a.scenario != 'cos' or not a.stage_github
spec = dict(scenario=a.scenario, target=a.target, baseline=prev, selected=selected, launchers=launchers,
            bytes=new['core_asset']['size'], githubArchiveId=a.github_archive_id or new['core_asset']['id'])
if a.cos_manifest:
    content = a.cos_manifest.read_bytes()
    assert json.loads(content) == selected, 'Selected COS manifest must be the same signed object as the candidate'
    assert a.cos_manifest.name.startswith(f'runtime-{a.target}') and a.cos_manifest.suffix == '.json'
    spec['cosManifest'] = dict(name=a.cos_manifest.name, sha256=hashlib.sha256(content).hexdigest())
if a.stage_github:
    spec['stageTag'] = new['tag']
with a.out.open('x', encoding='utf-8') as output:
    json.dump(spec, output, ensure_ascii=False, indent=2)
