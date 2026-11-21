"""Read each frozen COS object once and stage the same bytes on GitHub."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import datetime
import json
import os
import subprocess
import time

REPO = os.environ['GH_REPO']
TAG = 'student-20261121-diagram-1'
COS = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
WORK = Path('publication-work')
RECEIPT = WORK/'previous'
RECEIPT.mkdir(parents=True)
DEFAULTS = {'runtime-macos-x64.json','runtime-macos-arm64.json','runtime-windows-x64.json'}

def gh(*args, timeout=120):
    return subprocess.run(['gh', *map(str,args)], check=True, stdout=subprocess.PIPE, timeout=timeout).stdout

def api(path):
    return json.loads(gh('api',f'repos/{REPO}/{path}'))

def write(path, payload):
    path.write_text(json.dumps(payload,indent=2)+'\n')

def open_url(url, timeout=100):
    result = urlopen(Request(url,headers={'User-Agent':'Kaixin-release-verification','Accept-Encoding':'identity'}),timeout=timeout)
    assert urlparse(result.geturl()).netloc in {urlparse(COS).netloc,'raw.githubusercontent.com','github.com','release-assets.githubusercontent.com'}
    return result

def bytes_for(url, max_bytes=250_000):
    with open_url(url) as response:
        result = response.read(max_bytes+1)
    assert len(result)<=max_bytes
    return result

def inventory(tag):
    return {row['name']:row for row in api('releases/tags/'+tag)['assets']}

def verified(remote, expected):
    return remote['state']=='uploaded' and remote['size']==expected['bytes'] and remote['digest']=='sha256:'+expected['sha256']

def stage_one(name, row):
    assert Path(name).name==name
    release = inventory(TAG)
    prior = release.get(name)
    url = COS+row.get('cos_name',name)
    if prior:
        assert verified(prior,row)
        assert name.endswith('.json') or name+'.cos-receipt.json' in release
        return
    deadline = time.monotonic()+1030
    while True:
        try:
            remote=open_url(url)
            break
        except OSError:
            if time.monotonic()>=deadline:
                raise
            time.sleep(20)
    saved=WORK/name
    count=0
    digest=sha256()
    first_byte=None
    with remote as response, saved.open('xb') as output:
        headers={key.lower():value for key,value in response.headers.items()}
        while piece:=response.read(8<<20):
            if count==0: first_byte=piece[:1].hex()
            count+=len(piece)
            assert count<=row['bytes']
            digest.update(piece)
            output.write(piece)
    assert (count,digest.hexdigest())==(row['bytes'],row['sha256']), name
    print('COS bytes verified',name,count,digest.hexdigest(),flush=True)
    if not name.endswith('.json'):
        receipt=RECEIPT/(name+'.cos-receipt.json')
        write(receipt,{'channel':'COS','url':url,'verified':True,'bytes':count,'sha256':digest.hexdigest(),
                       'at':datetime.datetime.now(datetime.UTC).isoformat(), 'version':headers.get('x-cos-version-id'),
                       'etag':headers.get('etag'),'last_modified':headers.get('last-modified'),
                       'crc64':headers.get('x-cos-hash-crc64ecma'),'first_byte':first_byte})
        gh('release','upload',TAG,receipt,timeout=120)
    gh('release','upload',TAG,saved,timeout=1050)
    assert verified(inventory(TAG)[name],row)
    saved.unlink()

def main(config_url, config_hash):
    config_raw=bytes_for(config_url)
    assert sha256(config_raw).hexdigest()==config_hash
    config=json.loads(config_raw)
    assert config['tag']==TAG and config['source_commit']=='64ec3957abd504086777df87becf3851f5908aed'
    assert api('releases/latest')['tag_name']=='student-20261117-k12-18'
    exists=subprocess.run(['gh','release','view',TAG],capture_output=True,timeout=30)
    if exists.returncode:
        notes=WORK/'notes.md'
        notes.write_text('教师绘图更新候选，发布后可在应用内检查更新。\n\n'
                         '- 已审核例图库优先，同模板改参数和明确函数条件可本机计算。\n'
                         '- 示例缺失时使用可核对图元及排列连接关系；保留独立核对。\n'
                         '- 保留聊天正文配图、右侧原图、来源引用和学习记录。\n',encoding='utf-8')
        gh('release','create',TAG,'--target',config['source_carrier'],'--prerelease','--title',
           '开心动力超级学霸 2026-11-21 教学绘图更新','--notes-file',notes)
    release=api('releases/tags/'+TAG)
    assert release['prerelease'] and not release['draft'] and release['target_commitish']==config['source_carrier']
    archives=config['archives']
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda item:stage_one(*item),config['feeds'].items()))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item:stage_one(*item),archives.items()))
    rows=inventory(TAG)
    for name,row in (archives|config['feeds']).items():
        assert verified(rows[name],row),name
    assert api('releases/latest')['tag_name']=='student-20261117-k12-18'
    write(Path('PUBLICATION-RECEIPT.json'),{'staged':True,'published':False,'tag':TAG,'source_commit':config['source_commit'],
              'release_id':release['id'],'config_sha256':config_hash,'github_verified_asset_digests':len(archives)+len(config['feeds'])})

if __name__ == "__main__":
    main("https://raw.githubusercontent.com/1281504089-cell/kaixin-k12-tutor/27e8a9db96a0e32be6eb5baaddfa037bd54640f1/release-sources/20261121-diagram-1-stage.json", "f3d525adfa8c5543393ec96a1c04adbbdbe7820d74dcf28f4dada896702a6683")
