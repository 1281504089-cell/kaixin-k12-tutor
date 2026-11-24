"""Attach the exact, previously verified incremental source bundle to the candidate draft."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
import gzip
import json
import os
import re
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.with_name('native-47ce923-cross')),str(HERE.with_name('native-17bf2ce'))]
from draft_assets import draft,pinned_draft_asset
from retain_verified_media import LOCK,match,pinned_draft,upload_one

BASE={
    'name':'kaixin-source-from-windows-startup-17bf2ce.patch.gz',
    'bytes':616700,'sha256':'5311839c0a54896f01d59056d320be607f29a4a53f5cbfa169510aff910fdb0b',
}

def main():
    assert os.environ['GITHUB_REF']=='refs/heads/codex/desktop-native-qa-17bf2ce'
    for _ in range(84):
        try:
            new, assets=pinned_draft()
            break
        except (AssertionError, ValueError):
            sleep(10)
    else:
        raise TimeoutError('The new pinned source release draft did not become available')
    assert new['id']==457063007
    old, prior=draft({'draft_title':LOCK['old_draft_title']})
    assert old['id']==456863262
    recipe=json.loads((HERE/'source-patch-recipe.json').read_bytes())
    file=recipe['file']
    assert file['commit']==LOCK['source_commit'] and file['tree']==LOCK['tree']
    with TemporaryDirectory(prefix='scholar-source-47ce923-') as t:
        work=Path(t)
        base=work/BASE['name']
        pinned_draft_asset(prior,BASE,base)
        chunks=re.split(rb'(?m)(?=^diff --git )',gzip.decompress(base.read_bytes()))[1:]
        previous={part.split(b'\n',1)[0].decode('ascii'):part.decode('utf-8') for part in chunks}
        assert len(previous)==len(chunks)
        rows=previous|recipe['complete_replacement_diffs']
        assert len(recipe['order'])==len(set(recipe['order'])) and set(recipe['order'])==rows.keys()
        raw=''.join(rows[path] for path in recipe['order']).encode()
        archive=gzip.compress(raw,mtime=0)
        assert (len(archive),sha256(archive).hexdigest())==(file['bytes'],file['sha256'])
        filename=file['archive']
        destination=work/filename
        destination.write_bytes(archive)
        locked={**file,'file':filename}
        existing=assets.get(filename)
        if existing:
            assert match(existing,locked)
            asset_id=existing['id']
        else:
            asset_id=upload_one(new,locked,destination)
        checked,saved=pinned_draft()
        assert checked['id']==new['id'] and saved[filename]['id']==asset_id and match(saved[filename],locked)
    print(json.dumps({'draft_id':new['id'],'asset_id':asset_id,**file},ensure_ascii=False))

if __name__=='__main__':
    main()
