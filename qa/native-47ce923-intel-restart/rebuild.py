"""Reproduce the frozen desktop core and its existing-base delta from pinned QA assets."""
from contextlib import contextmanager
from hashlib import file_digest, sha256
from pathlib import Path
import gzip
import io
import json
import tarfile


HERE = Path(__file__).resolve().parent
CHANGES = {
    'BUILD_COMMIT': 'build-commit.txt',
    'core/deeptutor/runtime/desktop_restart.py': 'desktop_restart.py',
    'launcher/src/shell-update.mjs': 'shell-update.mjs',
    'launcher/manifest.json': 'launcher-manifest-47ce923.json',
}


def digest(file):
    with file.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


class HashWriter:
    def __init__(self):
        self.length = 0
        self.digest = sha256()

    def write(self, data):
        self.length += len(data)
        self.digest.update(data)
        return len(data)

    def flush(self):
        pass


@contextmanager
def output_tar(path, level):
    if path is None:
        sink = HashWriter()
        with gzip.GzipFile(filename='', mode='wb', fileobj=sink, mtime=0, compresslevel=level) as compressed, \
             tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as result:
            yield result, sink
    else:
        with path.open('xb') as sink, \
             gzip.GzipFile(filename='', mode='wb', fileobj=sink, mtime=0, compresslevel=level) as compressed, \
             tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as result:
            yield result, None


def read_changes():
    return {name:(HERE/file).read_bytes() for name,file in CHANGES.items()}


def core(previous, output):
    changes=read_changes()
    moved='core/deeptutor/runtime/desktop_restart.py'
    found=set()
    overlay=False
    appended=False
    moved_mode=None
    with output_tar(output,4) as (archive,sink), tarfile.open(previous,mode='r|gz') as source:
        for member in source:
            assert member.isfile()
            if member.name==moved:
                assert not overlay
                moved_mode=member.mode
                continue
            overlay=overlay or member.name=='BUILD_COMMIT'
            if overlay and not appended and member.name>moved:
                assert moved_mode is not None
                record=tarfile.TarInfo(moved)
                data=changes[moved]
                record.size,record.mode=len(data),moved_mode
                archive.addfile(record,io.BytesIO(data))
                appended=True
                found.add(moved)
            stream=source.extractfile(member)
            if member.name in changes:
                data=changes[member.name]
                member.size=len(data)
                stream=io.BytesIO(data)
                found.add(member.name)
            archive.addfile(member,stream)
    assert found==changes.keys()
    return {'bytes':sink.length,'sha256':sink.digest.hexdigest()} if sink else {
        'bytes':output.stat().st_size,'sha256':digest(output)}


def delta(old_delta, new_core, new_sha, output):
    changes=read_changes()
    with tarfile.open(old_delta,mode='r|gz') as old:
        first=next(iter(old))
        assert first.name=='delta-inventory.json'
        inventory=json.load(old.extractfile(first))
        previous_changed={entry.name for entry in old if entry.name!=first.name}
    rows={row['file']:row for row in inventory['files']}
    assert len(rows)==len(inventory['files'])
    for name,data in changes.items():
        row=rows[name]
        row.update(bytes=len(data),sha256=sha256(data).hexdigest())
    inventory['toCoreSha256']=new_sha
    changed=previous_changed|changes.keys()
    plan=json.dumps(inventory,separators=(',', ':')).encode()
    with output_tar(output,6) as (archive,_), tarfile.open(new_core,mode='r|gz') as source:
        first=tarfile.TarInfo('delta-inventory.json')
        first.size=len(plan)
        archive.addfile(first,io.BytesIO(plan))
        for member in source:
            if member.name not in changed:
                continue
            row=rows[member.name]
            assert member.isfile() and (member.size,member.mode)==(row['bytes'],row['mode'])
            stream=source.extractfile(member)
            data=stream.read()
            assert sha256(data).hexdigest()==row['sha256']
            record=tarfile.TarInfo(member.name)
            record.size,record.mode=member.size,member.mode
            archive.addfile(record,io.BytesIO(data))
            changed.remove(member.name)
    assert not changed
    return {key:inventory[key] for key in ('formatVersion','fromCoreSha256','toCoreSha256')} | {
        'archive':output.name,'bytes':output.stat().st_size,'sha256':digest(output)}
