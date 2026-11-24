"""Boot and retain the verified bridge in the one existing private QA draft."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
QA_MODULES = HERE.with_name('native-17bf2ce')
sys.path.insert(0, str(QA_MODULES))
from ci_fresh_install import REPO, digest
from ci_repackage import read, write
from draft_assets import pinned_draft_asset
from retain_verified_media import LOCK as QA_LOCK, match, pinned_draft, upload_one


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=('macos-x64', 'macos-arm64', 'windows-x64'))
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    assert os.environ['GITHUB_REPOSITORY'] == REPO
    assert os.environ['GITHUB_REF'] == 'refs/heads/codex/desktop-native-qa-17bf2ce'
    assert os.environ['GITHUB_ACTIONS'] == 'true'
    assert QA_LOCK['source_commit'] == '17bf2ce6b062a2ba9b838b1b35b68feba2e7daa5'
    folder = HERE/'targets'/args.target
    receipt, manifest = folder/'bridge.json', folder/'runtime.json'
    pins = read(folder/'pins.json')
    for path in (receipt, manifest):
        assert digest(path) == pins[path.name]
    bridge = read(receipt)['bridge']
    asset = {'file':bridge['name'], 'bytes':bridge['bytes'], 'sha256':bridge['sha256']}
    initial, assets = pinned_draft()
    assert initial['draft'] is True and initial['id'] == read(HERE/'donor-lock.json')['draft_release_id']
    output = args.evidence.resolve()
    with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP'], prefix='staged-scholar-bridge-') as directory:
        work = Path(directory)
        downloads = [pinned_draft_asset(assets, QA_LOCK[key], work/QA_LOCK[key]['name']) for key in ('core','launcher')]
        retained = work/asset['file']
        arguments = [sys.executable, str(HERE/'verify_bridge.py'), args.target, '--receipt', str(receipt),
          '--manifest', str(manifest), '--core', str(work/QA_LOCK['core']['name']),
          '--launcher', str(work/QA_LOCK['launcher']['name']), '--retain-verified', str(retained), '--evidence', str(output)]
        boundary = folder/'boundary.gz'
        if 'boundary.gz' in pins:
            assert digest(boundary) == pins['boundary.gz']
            arguments += ['--boundary-member', str(boundary)]
        env = {**os.environ, 'PYTHONPATH':str(QA_MODULES)}
        subprocess.run(arguments, check=True, env=env)
        result = read(output/'result.json')
        assert result['passed'] and result['target'] == args.target and result['archive'] == bridge
        assert result['runtime_signature_verified'] and result['launcher_signature_verified']
        assert result['boot']['native_window'] and result['boot']['boot_commit'] == QA_LOCK['source_commit']
        assert result['boot']['bridge_sha256'] == digest(retained) and retained.stat().st_size == asset['bytes']
        release, current = pinned_draft()
        assert release['id'] == initial['id'] and release['draft'] is True
        existing = current.get(asset['file'])
        if existing:
            assert match(existing, asset), 'Mismatched draft asset, no replacement attempted'
            asset_id = existing['id']
        else:
            asset_id = upload_one(release, asset, retained)
        for attempt in range(5):
            checked, final = pinned_draft()
            saved = final.get(asset['file'])
            assert checked['id'] == initial['id'] and checked['draft'] is True
            if saved and saved['id'] == asset_id and match(saved,asset):
                break
            time.sleep(3)
        else:
            raise RuntimeError('Exact native bridge digest not visible in the pinned draft')
        write(output/'retained-native-bridge.json', {'passed':True, 'target':args.target, 'draft_release_id':initial['id'],
            'workflow_sha':os.environ['GITHUB_SHA'], 'run_id':os.environ['GITHUB_RUN_ID'], 'asset_id':asset_id,
            'source_commit':QA_LOCK['source_commit'], 'bridge':asset, 'downloaded_inputs':downloads,
            'uploaded_this_job':existing is None})

if __name__ == '__main__':
    main()
