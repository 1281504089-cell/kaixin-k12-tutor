"""Build one versioned incremental asset from a verified desktop core and its inventories."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
from unicodedata import normalize


def stream_sha256(stream):
    digest = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        digest.update(block)
    return digest.hexdigest()


def sha256(file):
    with file.open('rb') as stream:
        return stream_sha256(stream)


def inventory(file):
    document = json.loads(file.read_bytes())
    rows = {}
    aliases = set()
    for row in document['files']:
        name = row['file']
        if name != 'BUILD_COMMIT' and not name.startswith(('core/', 'web/', 'launcher/')):
            raise ValueError(f'Invalid core file path: {name}')
        if any(part in ('', '.', '..') or re.search(r'[\\:<>"|?*\x00-\x1f]|[ .]$', part)
               or re.match(r'^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)', part, re.I)
               for part in name.split('/')):
            raise ValueError(f'Invalid portable file path: {name}')
        alias = normalize('NFC', name).lower()
        if alias in aliases or type(row['bytes']) is not int or row['bytes'] < 0 or row['mode'] not in (0o644, 0o755):
            raise ValueError(f'Invalid core file record: {name}')
        if not re.fullmatch(r'[a-f0-9]{64}', row['sha256']):
            raise ValueError(f'Invalid file digest: {name}')
        aliases.add(alias)
        rows[name] = row
    if rows.get('BUILD_COMMIT', {}).get('bytes') not in (40, 41) or not re.fullmatch(r'[a-f0-9]{40}', document['source_commit']):
        raise ValueError('Core inventory is missing its build identity')
    return document['source_commit'], rows


class CheckedStream:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, length):
        data = self.stream.read(length)
        self.digest.update(data)
        return data


def build(old_files, new_files, old_core_sha, new_archive, output):
    if not re.fullmatch(r'[a-f0-9]{64}', old_core_sha) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.+_-]*\.tar\.gz', output.name):
        raise ValueError('Invalid previous core digest or incremental asset filename')
    if output.name == new_archive.name:
        raise ValueError('Use a distinct incremental asset filename')
    _, previous = inventory(old_files)
    commit, target = inventory(new_files)
    next_core_sha = sha256(new_archive)
    if old_core_sha == next_core_sha:
        raise ValueError('The two core archives are identical')
    descriptor = {'formatVersion': 1, 'fromCoreSha256': old_core_sha, 'toCoreSha256': next_core_sha}
    plan = json.dumps({**descriptor, 'files': list(target.values())}, separators=(',', ':')).encode()
    if len(plan) > 16 * 1024 ** 2:
        raise ValueError('Incremental file inventory exceeds the client limit')
    matched = set()
    already_created = False
    try:
        with output.open('xb') as raw:
            already_created = True
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as compressed, \
                    tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as out, \
                    tarfile.open(new_archive, mode='r|gz') as source:
                record = tarfile.TarInfo('delta-inventory.json')
                record.size = len(plan)
                out.addfile(record, io.BytesIO(plan))
                for member in source:
                    if member.isdir():
                        continue
                    name = member.name.removeprefix('./')
                    row = target.get(name)
                    if not row or name in matched or not member.isfile() or member.size != row['bytes']:
                        raise ValueError(f'Unexpected file in full core: {name}')
                    with source.extractfile(member) as stream:
                        if name == 'BUILD_COMMIT':
                            content = stream.read()
                            if content.strip() != commit.encode():
                                raise ValueError('Build commit differs from core inventory')
                            stream = io.BytesIO(content)
                        if previous.get(name) != row:
                            verified = CheckedStream(stream)
                            entry = tarfile.TarInfo(name)
                            entry.size, entry.mode = row['bytes'], row['mode']
                            out.addfile(entry, verified)
                            actual = verified.digest.hexdigest()
                        else:
                            actual = stream_sha256(stream)
                    if actual != row['sha256']:
                        raise ValueError(f'Core file digest differs: {name}')
                    matched.add(name)
            if matched != set(target):
                raise ValueError('The full core is missing inventoried files')
        size = output.stat().st_size
        if size >= new_archive.stat().st_size or size > 2 * 1024 ** 3:
            raise ValueError('Use the full core when the incremental asset is no smaller')
        return {**descriptor, 'archive': output.name, 'bytes': size, 'sha256': sha256(output)}
    except BaseException:
        if already_created:
            output.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous_inventory', type=Path)
    parser.add_argument('target_inventory', type=Path)
    parser.add_argument('previous_core_sha256')
    parser.add_argument('target_core', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.previous_inventory, args.target_inventory, args.previous_core_sha256,
                           args.target_core, args.output)))
