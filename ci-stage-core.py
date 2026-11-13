"""Repack the already-public frozen build without any platform-native modules."""
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
from urllib.request import Request, urlopen

SOURCE_URL = 'https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/core-updates/kaixin-core-20261113-avatar-update.tar.gz'
SOURCE_SHA256 = 'f7fda335819c1bbb7334ebb36026a3015d0c89fe609e3c7ca55b109159249a9f'
COMMIT = 'a47b05f9136ca6fb72d2f1f8a04eeb425298f358'
OUT = Path('staged-core')
OUT.mkdir(exist_ok=True)
source = OUT / 'source.tar.gz'
if not source.exists():
    with urlopen(Request(SOURCE_URL, headers={'User-Agent': 'Kaixin-core-release'}), timeout=120) as response, source.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256, 'Public frozen input checksum mismatch'

archive = OUT / 'kaixin-core-20261113-sync2.tar.gz'
contents = hashlib.sha256()
count = 0
required = {'BUILD_COMMIT', 'core/deeptutor_cli/main.py', 'web/server.js', 'web/.next/BUILD_ID'}
build = ''
with tarfile.open(source, 'r:gz') as original, archive.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as compressed, tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as output:
    for item in sorted(original.getmembers(), key=lambda item: item.name):
        name = str(PurePosixPath(item.name))
        parts = PurePosixPath(name).parts
        assert not name.startswith('/') and '..' not in parts, 'Unsafe public archive path'
        if not parts or parts[0] not in {'core', 'web', 'BUILD_COMMIT'}:
            continue
        if any(part in {'node_modules', '__pycache__', '.DS_Store'} for part in parts):
            continue
        assert item.isfile() or item.isdir(), 'Unexpected payload link'
        assert not name.lower().endswith(('.node', '.dll', '.dylib', '.exe', '.so', '.pem')), 'Native binary or key in code payload'
        assert 'data/user' not in name and '.git' not in parts, 'Private state in code payload'
        info = tarfile.TarInfo(name)
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ''
        info.mode = 0o755 if item.isdir() or item.mode & 0o111 else 0o644
        if item.isdir():
            info.type = tarfile.DIRTYPE
            output.addfile(info)
            continue
        data = original.extractfile(item).read()
        info.size = len(data)
        output.addfile(info, io.BytesIO(data))
        contents.update(name.encode() + b'\0' + hashlib.sha256(data).digest())
        count += 1
        required.discard(name)
        if name == 'BUILD_COMMIT':
            assert data.decode().strip() == COMMIT
        if name == 'web/.next/BUILD_ID':
            build = data.decode().strip()
assert not required, 'Incomplete core payload'
receipt = {'source_commit': COMMIT, 'frontend_build': build, 'archive': archive.name,
           'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'bytes': archive.stat().st_size,
           'source_sha256': SOURCE_SHA256, 'payload_content_sha256': contents.hexdigest(), 'files': count,
           'native_modules_included': False, 'production_signature': 'pending local maintainer signature'}
(OUT / 'staged-core.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
