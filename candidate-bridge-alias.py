"""Rename only the three candidate assets; retain every stable release asset."""
import json
import subprocess
import base64
import hashlib
import sys
from pathlib import Path

REPO = '1281504089-cell/kaixin-k12-tutor'
TAG = 'student-20261117-k12-1'
def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)])
def api(path):
    return json.loads(gh('api', 'repos/' + REPO + '/' + path))
def write_api(method, path, payload):
    file = Path('alias-api-input.json');file.write_text(json.dumps(payload))
    return json.loads(gh('api', '-X', method, 'repos/' + REPO + '/' + path, '--input', file))

plan = json.loads(Path('BRIDGE-NAME-COLLISION.json').read_text())
assert plan['candidate_release_id'] == 447366728 and plan['source_commit'] == '5ff65526b0665ae844d865ef21a88eaebbf63da2'
assert {r['target'] for r in plan['collisions']} == {'windows-x64', 'macos-x64', 'macos-arm64'}
delivery = json.loads(Path('STAGE-DELIVERY-PLAN.json').read_text())
raw = Path('attachment-final-manifests.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == delivery['sha256']
final = json.loads(raw)
assert final['core_commit'] == plan['source_commit'] and len(final['manifests']) == 36
for row in plan['collisions']:
    full = final['manifests']['runtime-' + row['target'] + '.json']
    assert full['archive'] == row['proposed_asset_name'] and full['runtimeId'] == row['proposed_runtime_id']
    assert full['sha256'] == row['candidate']['sha256'] and full['commit'] == plan['source_commit']
if '--selfcheck' in sys.argv:
    print('PASS: candidate-only plan, signed stage bytes, three new identities')
    raise SystemExit(0)
release = api('releases/tags/' + TAG)
assert release['id'] == plan['candidate_release_id'] and release['prerelease'] and not release['draft']
aliases = []
for row in plan['collisions']:
    expected = row['candidate']
    assert expected['id'] in {a['id'] for a in release['assets']}
    path = 'releases/assets/' + str(expected['id'])
    before = api(path)
    assert before['id'] == expected['id'] and before['size'] == expected['bytes'] and before['digest'] == 'sha256:' + expected['sha256']
    assert before['name'] in (row['name'], row['proposed_asset_name'])
    error = None
    if before['name'] != row['proposed_asset_name']:
        try:
            gh('api', '-X', 'PATCH', 'repos/' + REPO + '/' + path, '-f', 'name=' + row['proposed_asset_name'])
        except Exception as caught:
            error = str(caught)
    after = api(path)
    assert after['id'] == expected['id'] and after['name'] == row['proposed_asset_name']
    assert after['size'] == expected['bytes'] and after['digest'] == 'sha256:' + expected['sha256']
    aliases.append(dict(target=row['target'], asset_id=after['id'], previous_name=row['name'],
                        name=after['name'], bytes=after['size'], sha256=expected['sha256'],
                        runtime_id=row['proposed_runtime_id'], verified=True, write_response_error=error))
receipt = dict(schema_version=1, tag=TAG, candidate_release_id=release['id'],
               source_commit=plan['source_commit'], aliases=aliases, stable_release_mutated=False)
Path('BRIDGE-ASSET-ALIASES.json').write_text(json.dumps(receipt, indent=2) + '\n')
gh('release', 'upload', TAG, 'BRIDGE-ASSET-ALIASES.json', '--clobber')
branch = delivery['branch'];expected = delivery['expected_head']
ref = api('git/ref/heads/' + branch)
if ref['object']['sha'] == expected:
    blob = write_api('POST', 'git/blobs', {'content':raw.decode(), 'encoding':'utf-8'})
    parent = api('git/commits/' + expected)
    tree = write_api('POST', 'git/trees', {'base_tree':parent['tree']['sha'], 'tree':[{'path':'attachment-final-manifests.json','mode':'100644','type':'blob','sha':blob['sha']}]})
    commit = write_api('POST', 'git/commits', {'message':'[skip ci] Deliver owner-signed staged K12 manifests to the running native matrix','tree':tree['sha'],'parents':[expected]})
    try:
        write_api('PATCH', 'git/refs/heads/' + branch, {'sha':commit['sha'],'force':False})
    except Exception:
        if api('git/ref/heads/' + branch)['object']['sha'] != commit['sha']:
            raise
    assert api('git/ref/heads/' + branch)['object']['sha'] == commit['sha']
else:
    commit = api('git/commits/' + ref['object']['sha'])
    assert [p['sha'] for p in commit['parents']] == [expected] and '[skip ci]' in commit['message']
actual = api('contents/attachment-final-manifests.json?ref=' + branch)
assert base64.b64decode(actual['content']) == raw
receipt.update(native_delivery_commit=api('git/ref/heads/' + branch)['object']['sha'], native_original_workflow_commit=expected,
               signed_manifest_sha256=delivery['sha256'], new_native_run_requested=False)
Path('BRIDGE-ASSET-ALIASES.json').write_text(json.dumps(receipt, indent=2) + '\n')
gh('release', 'upload', TAG, 'BRIDGE-ASSET-ALIASES.json', '--clobber')
print(json.dumps(receipt))
