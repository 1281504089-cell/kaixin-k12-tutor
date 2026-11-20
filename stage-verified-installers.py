"""Optionally upload only tested full installers to the frozen k12-18 candidate."""
import argparse
from pathlib import Path
import time
from urllib.parse import quote

from ci_repackage import read, run, write
from importlib.util import module_from_spec, spec_from_file_location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    args = parser.parse_args()
    spec = spec_from_file_location('candidate', Path(__file__).with_name('ci-fresh-install.py'))
    candidate = module_from_spec(spec)
    spec.loader.exec_module(candidate)

    batch = read(args.inputs / 'attachment-batch.json')
    stage = read(args.inputs / 'online-stage.json')
    tag = batch['tag']
    assert tag == 'student-20261117-k12-18'
    assert args.target in candidate.MACHINES
    evidence = args.work / 'evidence'
    receipt = evidence / f'verification-{args.target}.json'
    test = read(receipt)
    assert test['target'] == args.target and test['native_install'] == 'passed'
    assert test['native_smoke']['current_core_included'] is True
    assert test['core_commit'] == batch['core_commit'] == stage['proof']['source_commit']
    assert test['core_sha256'] == batch['manifests'][args.target]['sha256']
    assert test['launcher_build'] == batch['launcher_build']
    output = args.work / 'installers'
    paths = {file.name: file for file in output.iterdir()}
    assert set(paths) == {row['file'] for row in test['full_files']}
    rows = [{**row, 'path': paths[row['file']]} for row in test['full_files']]
    rows.append({'file': receipt.name, 'path': receipt, 'bytes': receipt.stat().st_size,
                 'sha256': candidate.digest(receipt)})
    for row in rows:
        assert row['path'].stat().st_size == row['bytes'] and candidate.digest(row['path']) == row['sha256']

    def release():
        value = candidate.metadata(tag)
        assert value['id'] == stage['release_id'] and value['tag_name'] == tag
        assert value['prerelease'] is True and value['draft'] is False
        return value

    def check(existing, row):
        asset = existing[row['file']]
        assert asset['state'] == 'uploaded'
        assert asset['size'] == row['bytes'] and asset['digest'] == 'sha256:' + row['sha256']
        assert asset['browser_download_url'] == candidate.DOWNLOAD + tag + '/' + quote(row['file'], safe='')
        return {key: asset[key] for key in ('id', 'name', 'size', 'digest', 'browser_download_url')}

    existing = {asset['name']: asset for asset in release()['assets']}
    pending = []
    for row in rows:
        if row['file'] in existing:
            check(existing, row)
        else:
            pending.append(row['path'])
    if pending:
        run('gh', 'release', 'upload', tag, *pending, '--repo', candidate.REPO, timeout=7200)
    for attempt in range(6):
        existing = {asset['name']: asset for asset in release()['assets']}
        if all(row['file'] in existing and existing[row['file']].get('digest') for row in rows):
            break
        time.sleep(2 ** attempt)
    assets = [check(existing, row) for row in rows]
    write(evidence / 'uploaded-installers.json', {'target': args.target, 'release_id': stage['release_id'],
                                                'tag': tag, 'assets': assets})


if __name__ == '__main__':
    main()
