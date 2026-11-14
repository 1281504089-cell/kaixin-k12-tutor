"""Upload only evidence for the exact already-published audio release."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

repo = '1281504089-cell/kaixin-k12-tutor'
root = Path.cwd()
read = lambda name: json.loads((root / name).read_text())


def gh(*args):
    return subprocess.check_output(['gh', *args])


def api(path):
    return json.loads(gh('api', 'repos/' + repo + '/' + path))


current = read('CURRENT-DESKTOP-RELEASE.json')
post = read('POST-PUBLISH-VERIFIED.json')
verification = read('VERIFICATION-AUDIO-20261114.json')
assert current['tag'] == 'student-20261114-audio' and current['release_id'] == 445374839
assert current['learning_source_commit'] == post['downloaded_core_commit'] == verification['learning_source_commit'] == '651fbd6a41f8649c53c23f3fea79de98776cde05'
assert current['core_sha256'] == post['downloaded_sha256'] == '362fc67900c8b77be93eb7c967ffe6c96334af6a0f3362065cddbc20d73a64d1'
assert post['signature_verified_manifests'] == verification['signed_manifests'] == 27
assert all(current['platforms'][target]['chat_audio']['passed'] for target in ['windows-x64', 'macos-x64', 'macos-arm64'])
names = ['CURRENT-DESKTOP-RELEASE.json', 'POST-PUBLISH-VERIFIED.json', 'VERIFICATION-AUDIO-20261114.json',
         'INSTALLATION.txt', 'INSTALL-LATEST.md', 'AUDIO-SCIENCE-20261114.md']
if current['usb_delivery']['completed']:
    usb = read('USB-DELIVERY-RECEIPT.json')
    assert usb['tag'] == current['tag'] and usb['core_commit'] == current['learning_source_commit']
    assert usb['verified_payload_files'] == len(usb['files']) == 9 and usb['superseded_installation_removed']
    assert all(row['usb_readback_verified'] for row in usb['files'])
    assert usb['other_materials_unchanged'] and usb['protected_math_documents'] == 6
    names.append('USB-DELIVERY-RECEIPT.json')
assert all((root / name).is_file() and not (root / name).is_symlink() for name in names)
release = api('releases/latest')
assert release['id'] == current['release_id'] and release['tag_name'] == current['tag']
assert not release['draft'] and not release['prerelease']
assert api('git/ref/heads/main')['object']['sha'] == os.environ['GITHUB_SHA'], 'Refusing stale metadata'
for name in names:
    gh('release', 'upload', current['tag'], name, '--clobber')
assets = {a['name']: a for a in api('releases/tags/' + current['tag'])['assets']}
proof = []
for name in names:
    raw = (root / name).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert assets[name]['size'] == len(raw) and assets[name]['digest'] == 'sha256:' + digest
    fetched = gh('api', 'repos/' + repo + '/releases/assets/' + str(assets[name]['id']), '-H', 'Accept: application/octet-stream')
    assert fetched == raw
    proof.append({'file': name, 'bytes': len(raw), 'sha256': digest})
print(json.dumps({'tag': current['tag'], 'metadata_commit': os.environ['GITHUB_SHA'], 'usb_complete': current['usb_delivery']['completed'], 'assets_read_back': proof}))
