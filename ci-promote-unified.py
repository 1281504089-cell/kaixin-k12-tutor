"""Read each frozen COS object once and stage the same bytes on GitHub."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256, sha256 as release_gate_hash
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import datetime
import json
import os
import subprocess
import time

REPO = os.environ['GH_REPO']
assert REPO == '1281504089-cell/kaixin-k12-tutor'
TAG = 'student-20261121-resource-5'
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

def verify_cos_anchor(url, proof):
    version = proof.get('version')
    etag = proof.get('etag')
    modified = proof.get('last_modified')
    assert (version and version.lower() != 'null') or (etag and modified), url
    headers = {'Range': 'bytes=0-0', 'Accept-Encoding': 'identity', 'User-Agent': 'Kaixin-release-verification'}
    if etag:
        headers['If-Match'] = etag
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        assert urlparse(response.geturl()).netloc == urlparse(COS).netloc, url
        assert response.status == 206 and response.headers.get('Content-Range') == f'bytes 0-0/{proof["bytes"]}', url
        assert response.read(2).hex() == proof['first_byte'] and len(proof['first_byte']) == 2, url
        observed = {'version': response.headers.get('x-cos-version-id'), 'etag': response.headers.get('etag'),
                    'last_modified': response.headers.get('last-modified')}
        assert all(not proof.get(key) or proof[key] == value for key, value in observed.items()), url


def stage_one(name, row):
    assert Path(name).name==name
    release = inventory(TAG)
    prior = release.get(name)
    url = COS+row.get('cos_name',name)
    archived = not name.endswith('.json')
    receipt_name = name + '.cos-receipt.json'
    previous_receipt = release.get(receipt_name) if archived else None
    if prior:
        assert verified(prior, row), name
    if previous_receipt:
        proof_raw = bytes_for(previous_receipt['browser_download_url'])
        assert verified(previous_receipt, {'bytes': len(proof_raw), 'sha256': sha256(proof_raw).hexdigest()}), name
        proof = json.loads(proof_raw)
        assert proof['verified'] is True and proof['url'] == url, name
        assert (proof['bytes'], proof['sha256']) == (row['bytes'], row['sha256']), name
    if prior and previous_receipt:
        verify_cos_anchor(url, proof)
        return
    if prior and not archived:
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
    if archived and not previous_receipt:
        receipt=RECEIPT/receipt_name
        write(receipt,{'channel':'COS','url':url,'verified':True,'bytes':count,'sha256':digest.hexdigest(),
                       'at':datetime.datetime.now(datetime.UTC).isoformat(), 'version':headers.get('x-cos-version-id'),
                       'etag':headers.get('etag'),'last_modified':headers.get('last-modified'),
                       'crc64':headers.get('x-cos-hash-crc64ecma'),'first_byte':first_byte})
        gh('release','upload',TAG,receipt,timeout=120)
    if previous_receipt:
        assert first_byte == proof['first_byte'], name
        observed = {'version': headers.get('x-cos-version-id'), 'etag':headers.get('etag'),
                    'last_modified':headers.get('last-modified')}
        assert all(not proof.get(key) or proof[key] == value for key, value in observed.items()), name
    if not prior:
        gh('release','upload',TAG,saved,timeout=1050)
    assert verified(inventory(TAG)[name],row)
    saved.unlink()

def main(config_url, config_hash):
    import sys as release_sys
    if release_sys.flags.optimize:
        raise RuntimeError('Resource-5 workstation checks require Python assertions')
    report_bytes = Path(__file__).with_name('native-local-workflow.json').read_bytes()
    if release_gate_hash(report_bytes).hexdigest() != 'd3b403af92710ab6afed422d34294c2351497c10f744e5d613f1690a174f71e5':
        raise RuntimeError('The Resource-5 workstation proof does not match the approved digest')
    report = json.loads(report_bytes)
    assert report['passed'] is True and report['source_commit'] == 'a8d4dac2292e093d68b144b26d7ef7b2716f99ad' and report['core_sha256'] == '61842b2e8c2e8b670f4e0390c94859a29fd90d03b72a04f3781220bdc341b8b8'
    for check in ('drag_dynamic', 'dynamic_layout', 'textbook_jump', 'single_verified_question', 'history_reopen', 'alternate_phrasing_and_topic', 'non_gallery_diagram', 'fast_new_chat_completion'):
        assert report['checks'].get(check) is True, f'Workstation check is missing: {check}'
    config_raw=bytes_for(config_url)
    assert sha256(config_raw).hexdigest()==config_hash
    config=json.loads(config_raw)
    assert config['tag'] == TAG and config['source_commit'] == 'a8d4dac2292e093d68b144b26d7ef7b2716f99ad'
    assert config['core_sha256'] == '61842b2e8c2e8b670f4e0390c94859a29fd90d03b72a04f3781220bdc341b8b8' and config['source_carrier'] == '8280c758378e646527e0fe87580a19e0f2bc452e'
    latest = api('releases/latest')
    assert latest['tag_name'] == 'student-20261121-diagram-1' and latest['id'] == 453559695
    exists=subprocess.run(['gh','release','view',TAG],capture_output=True,timeout=30)
    if exists.returncode:
        notes=WORK/'notes.md'
        notes.write_text('超级学霸桌面版出题来源更新候选。发布后可在应用内检查更新。\n\n'
                         '- 所有对话入口共享获授权的长期资料、题库与教材检索。\n'
                         '- 保留完整原题和出处，普通找题与显式找题使用各自的检索预算。\n'
                         '- 必须配图的题目仅在有已核对图时交付。\n'
                         '- 优化题库索引准备，保留学习记录并支持匹配基线走增量。\n',encoding='utf-8')
        gh('release','create',TAG,'--target',config['source_carrier'],'--prerelease','--title',
           '开心动力超级学霸 2026-11-21 出题与题源更新','--notes-file',notes)
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
    latest = api('releases/latest')
    assert latest['tag_name'] == 'student-20261121-diagram-1' and latest['id'] == 453559695
    write(Path('PUBLICATION-RECEIPT.json'),{'staged':True,'published':False,'tag':TAG,'source_commit':config['source_commit'],
              'release_id':release['id'],'config_sha256':config_hash,'local_workflow_sha256':sha256(report_bytes).hexdigest(),'github_verified_asset_digests':len(archives)+len(config['feeds'])})


if __name__ == '__main__':
    main('https://raw.githubusercontent.com/1281504089-cell/kaixin-k12-tutor/79a0f43907a335e50f67d438c1b19dce0b88eead/releases/student-20261121-resource-5-stage.json', '356e6c3f890530060341436cc77c4ee12b020f5a6bc8c3086e7e03b0ce99eb90')
