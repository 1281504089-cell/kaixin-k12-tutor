"""Materialize the frozen JSON inputs exactly, without writing outside the plan."""
from base64 import b64decode
from gzip import decompress
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
raw=decompress(b64decode((HERE/'signed-plan.b64').read_bytes(),validate=True))
assert len(raw)<512*1024
rows=json.loads(raw)
assert len(rows)==92 and 'deployment-lock.json' in rows
for name,value in rows.items():
    assert name=='deployment-lock.json' or re.fullmatch(r'(?:feed/github|previous)/runtime-[a-zA-Z0-9.-]+\.json',name)
    path=HERE/name
    path.parent.mkdir(exist_ok=True,parents=True)
    data=value.encode('utf-8')
    if path.exists():
        assert path.is_file() and path.read_bytes()==data
    else:
        with path.open('xb') as out:
            out.write(data)

from hashlib import sha256
lock = json.loads((HERE/'deployment-lock.json').read_bytes())
expected = lock['patch']
assert expected['name']=='kaixin-source-from-43dba66-to-9c019338.patch.gz'
patch = b64decode((HERE/'source-patch.b64').read_bytes(),validate=True)
assert (len(patch),sha256(patch).hexdigest())==(expected['bytes'],expected['sha256'])
path=HERE/expected['name']
if path.exists():
    assert path.read_bytes()==patch
else:
    with path.open('xb') as out:
        out.write(patch)
