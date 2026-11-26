"""Replace the core after the verified native prefix of a retained bridge."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen

HERE=Path(__file__).resolve().parent
NATIVE=HERE.parent/'native-9719ddda'
sys.path.insert(0,str(NATIVE))
from retain_verified_media import draft, upload_one
from draft_assets import pinned_draft_asset

def read(file):
    return json.loads(file.read_text(encoding='utf-8'))

def stream(source, destination, length, current, full):
    while length:
        block=source.read(min(length, 4*1024**2))
        if not block:
            raise ValueError('A pinned input ended early')
        destination.write(block)
        current.update(block)
        full.update(block)
        length-=len(block)
    assert not source.read(1), 'Pinned input exceeded locked length'

def main(target):
    inputs=read(HERE/'donors.json')[target]
    prefix=inputs['prefix']
    lock=read(NATIVE/'input-lock.json')
    sha=lock['source_commit']
    assert sha=='9719dddaa36ae80261d676fb5914f2c48473061a'
    core=lock['core']
    release,assets=draft(lock)
    assert release['draft'] and release['id']==lock['draft_release_id'] and release['name']==lock['draft_title']
    work=Path(os.environ['RUNNER_TEMP'])/'scholar-bridge'
    work.mkdir()
    content_path=work/core['name']
    pinned_draft_asset(assets, core, content_path)
    bridge=work/f'kaixin-bridge-20261127-9719ddda-{target}.tar.gz'
    prefix_hash,core_hash,whole=sha256(),sha256(),sha256()
    max_byte=prefix['bytes']-1
    req=Request(inputs['donor_url'],headers={
         'Range':f'bytes=0-{max_byte}','Accept-Encoding':'identity','User-Agent':'Scholar verified native prefix',
    })
    with bridge.open('xb') as packaged, urlopen(req,timeout=90) as source:
        assert source.status==206 and source.headers['Content-Range']==f"bytes 0-{max_byte}/{inputs['donor_bytes']}"
        stream(source,packaged,prefix['bytes'],prefix_hash,whole)
        assert prefix_hash.hexdigest()==prefix['sha256']
        with content_path.open('rb') as full:
            stream(full,packaged,core['bytes'],core_hash,whole)
            assert core_hash.hexdigest()==core['sha256']
    sized=bridge.stat().st_size
    assert sized==prefix['bytes']+core['bytes'] and 0<sized<2*1024**3
    record={'file':bridge.name,'bytes':sized,'sha256':whole.hexdigest()}
    uploaded=upload_one(release,record,bridge)
    result={'source_commit':sha,'target':target,'core':core,'native_prefix':prefix,
            'bridge':{**{k:v for k,v in record.items() if k!='file'},'name':record['file']},
            'draft_release_id':release['id'],'bridge_asset':uploaded,'workflow_sha':os.environ['GITHUB_SHA'],
            'run_id':os.environ['GITHUB_RUN_ID']}
    receipt=Path('bridge-evidence')/f'bridge-prefix-{target}.json'
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'target':target,'bytes':sized,'sha256':record['sha256']}))

if __name__=='__main__':
    main(sys.argv[1])
