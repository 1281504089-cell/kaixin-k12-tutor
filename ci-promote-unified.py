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
def artifact_receipts(native_runs):
    targets=('macos-x64','macos-arm64','windows-x64')
    assert set(native_runs)==set(targets)
    all_installers={}
    used={}
    for platform in targets:
        run_id=native_runs[platform]['id']
        sha=native_runs[platform]['sha']
        run=used.setdefault(run_id,api(f'actions/runs/{run_id}'))
        assert run['head_sha']==sha and run['head_branch']=='codex/k12-native-reverify-20261117-diagram-1'
        assert run['status']=='completed'
        jobs=api(f'actions/runs/{run_id}/jobs')['jobs']
        evidence_job,=(j for j in jobs if f'({platform},' in j['name'])
        assert evidence_job['status']=='completed' and evidence_job['conclusion']=='success'
        if platform=='macos-x64':
            physical=approval['local_intel']
            assert physical['passed'] and physical['target']==platform and physical['source_commit']==config['source_commit']
            assert physical['signed_restart'] and physical['check_again_current']
            real=physical['network']
            expected=config['archives']['kaixin-core-delta-integrated-2-to-diagram-1.tar.gz']
            assert (real['bytes'],real['sha256'])==(expected['bytes'],expected['sha256'])
        folder=WORK/('evidence-'+platform)
        gh('run','download',run_id,'--name','attachments-'+platform,'--dir',folder,timeout=180)
        installed=json.loads((folder/('verification-'+platform+'.json')).read_bytes())
        fallback=json.loads((folder/'fallback.json').read_bytes())
        online=json.loads((folder/'online-cos.json').read_bytes())
        assert installed['target']==platform and installed['native_install']=='passed'
        assert installed['core_commit']==fallback['commit']==online['commit']==config['source_commit']
        assert installed['core_sha256']==fallback['core_sha256']==config['core_sha256']
        assert installed['run_id']==run_id and installed['workflow_commit']==sha
        assert fallback['passed'] and online['passed'] and online['restarted'] and online['checked_again']
        assert verified(rows[fallback['archive']],config['archives'][fallback['archive']])
        assert fallback['archive_sha256']==config['archives'][fallback['archive']]['sha256']
        assert online['delta']['name'] in config['archives'] and verified(rows[online['delta']['name']],online['delta'])
        if platform=='macos-x64':
            alternate=json.loads((folder/'online-github.json').read_bytes())
            assert alternate['passed'] and alternate['checked_again'] and alternate['restarted'] and alternate['channel']=='github'
            assert alternate['commit']==config['source_commit']
        files={row['file']:{'bytes':row['bytes'],'sha256':row['sha256']} for row in installed['full_files']}
        assert len(files)>=4 and not (files.keys()&all_installers.keys())
        assert all(verified(rows[name],row) for name,row in files.items())
        all_installers.update(files)
        reports=['fallback.json','online-cos.json'] + (['online-github.json'] if platform=='macos-x64' else [])
        for name in reports:
            path=WORK/(platform+'-'+name)
            path.write_bytes((folder/name).read_bytes())
            if path.name not in rows:
                gh('release','upload',TAG,path,timeout=120)
    return all_installers

def prepare_active_history(reserve,protected):
    stable=inventory('core-updates')
    keys=len(stable.keys()|reserve.keys())
    if keys<=1000:return []
    count=keys-1000+8
    import re
    allowed=re.compile(r'runtime-(?:macos|windows)-(?:x64|arm64)-20261117-k12-(?:1|2|4|7|8)-base-[a-f0-9]{12}\.json')
    keep=sorted(name for name in stable if name not in protected and allowed.fullmatch(name))
    assert len(keep)>=count and count<=100
    tags='core-updates-history-20261121'
    response=subprocess.run(['gh','release','view',tags],capture_output=True,timeout=30)
    if response.returncode:
        gh('release','create',tags,'--target',config['source_carrier'],'--latest=false',
           '--title','Historical desktop update descriptors','--notes','Archived exact signed descriptors previously carried on the live update tag.')
    backups=inventory(tags)
    archive_dir=WORK/'history'
    archive_dir.mkdir()
    rows_to_archive=[]
    for name in keep[:count]:
        remote=stable[name]
        raw=bytes_for(remote['browser_download_url'])
        expected={'bytes':len(raw),'sha256':sha256(raw).hexdigest()}
        assert verified(remote,expected),name
        path=archive_dir/name
        path.write_bytes(raw)
        rows_to_archive.append({'name':name,'previous_id':remote['id'],**expected})
    missed=[archive_dir/r['name'] for r in rows_to_archive if r['name'] not in backups]
    if missed:
        gh('release','upload',tags,*missed,timeout=550)
    backups=inventory(tags)
    for row in rows_to_archive:
        assert verified(backups[row['name']],row)
        row['archive_url']=backups[row['name']]['browser_download_url']
    write(RECEIPT/'old-compatibility-history.json',rows_to_archive)
    gh('release','upload',tags,RECEIPT/'old-compatibility-history.json','--clobber',timeout=120)
    for row in rows_to_archive:
        live=api('releases/assets/'+str(row['previous_id']))
        assert live['name']==row['name'] and verified(live,row)
        gh('api','--method','DELETE',f'repos/{REPO}/releases/assets/{live["id"]}')
    return rows_to_archive

def copy_new(name,wanted):
    saved=WORK/name
    original=rows[name]
    if name.endswith('.json'):
        saved.write_bytes(bytes_for(original['browser_download_url']))
    else:
        with open_url(original['browser_download_url']) as source, saved.open('xb') as output:
            total=0
            digest=sha256()
            while block:=source.read(8<<20):
                total+=len(block)
                assert total<=wanted['bytes']
                digest.update(block)
                output.write(block)
        assert (total,digest.hexdigest())==(wanted['bytes'],wanted['sha256'])
    assert saved.stat().st_size==wanted['bytes']
    if name.endswith('.json'): assert sha256(saved.read_bytes()).hexdigest()==wanted['sha256']
    gh('release','upload','core-updates',saved,timeout=1250)
    saved.unlink()

def activate(config_url,config_hash,approval_url,approval_hash):
    globals()['config']=json.loads(config_bytes:=bytes_for(config_url))
    globals()['approval']=json.loads(approval_bytes:=bytes_for(approval_url))
    assert sha256(config_bytes).hexdigest()==config_hash and sha256(approval_bytes).hexdigest()==approval_hash
    assert config['source_commit']==approval['source_commit'] and config['core_sha256']==approval['core_sha256']
    candidate=api('releases/tags/'+TAG)
    assert candidate['target_commitish']==config['source_carrier'] and candidate['prerelease']
    globals()['rows']={row['name']:row for row in candidate['assets']}
    installers=artifact_receipts(approval['native_runs'])
    for name,row in config['feeds'].items():
        assert verified(rows[name],row)
        body=bytes_for(COS+name)
        assert (len(body),sha256(body).hexdigest())==(row['bytes'],row['sha256'])
    for name,row in config['archives'].items():
        assert verified(rows[name],row)
        anchor=json.loads(bytes_for(rows[name+'.cos-receipt.json']['browser_download_url']))
        assert (anchor['url'],anchor['bytes'],anchor['sha256'])==(COS+name,row['bytes'],row['sha256']) and anchor['verified']
    assert api('releases/latest')['tag_name']=='student-20261117-k12-18'
    live=inventory('core-updates')
    protected=set(DEFAULTS)
    for name in DEFAULTS:
        original=bytes_for(live[name]['browser_download_url']+'?frozen=before')
        doc=json.loads(original)
        assert doc['commit']=='ec6cce3ba809d83e2226454c0ca713e747441714'
        assert sha256(original).hexdigest()==live[name]['digest'].removeprefix('sha256:')
        (RECEIPT/name).write_bytes(original)
        protected.update(r['file'] for r in doc['compatibleBaseManifests'])
        protected.add(doc['archive'])
    assets={k:v for k,v in (config['archives']|config['feeds']).items() if 'candidate.json' not in k and k not in DEFAULTS}
    import base64,gzip
    source=json.loads(bytes_for('https://raw.githubusercontent.com/'+REPO+'/'+config['source_carrier']+'/release-sources/20261121-diagram-1.json'))
    assert source['source_commit']==config['source_commit'] and source['cos_core']['sha256']==config['core_sha256']
    patch=source['patch']
    raw=gzip.decompress(base64.b64decode(patch['payload'],validate=True))
    assert sha256(raw).hexdigest()==patch['sha256']
    file=WORK/patch['file']
    assert file.parent==WORK
    file.write_bytes(raw)
    if file.name not in inventory(TAG): gh('release','upload',TAG,file)
    historical=prepare_active_history(assets,protected)
    live=inventory('core-updates')
    assert len(live.keys()|assets.keys())<=1000
    remaining=[]
    for name,row in assets.items():
        if name in live:
            assert verified(live[name],row)
        else:
            remaining.append((name,row))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda kv:copy_new(*kv),remaining))
    live=inventory('core-updates')
    assert all(verified(live[name],row) for name,row in assets.items())
    def apply_defaults():
        for name in ['runtime-macos-x64.json','runtime-macos-arm64.json','runtime-windows-x64.json']:
            wanted=config['feeds'][name]
            new=WORK/name
            body=bytes_for(rows[name]['browser_download_url'])
            assert (len(body),sha256(body).hexdigest())==(wanted['bytes'],wanted['sha256'])
            new.write_bytes(body)
            gh('release','upload','core-updates',new,'--clobber',timeout=130)
            assert verified(inventory('core-updates')[name],wanted)
            assert bytes_for('https://github.com/'+REPO+'/releases/download/core-updates/'+name+'?v='+str(time.time_ns()))==body
    try:
        apply_defaults()
    except (OSError,AssertionError,subprocess.SubprocessError):
        gh('release','upload','core-updates',*(RECEIPT/name for name in sorted(DEFAULTS)),'--clobber',timeout=120)
        raise
    notes=WORK/'public-notes.md'
    note_lines=[
        '## 2026-11-21 教学绘图更新','',
        '- 优先用已审核例图库。明确函数和同模板换参数时在本机计算。', 
        '- 未命中的示意图可使用结构化图元。只要求排列和连接时由本机排版，继续独立核对。',
        '- 已核对的图跟在对应讲解旁。可在同一窗口右侧打开原图。',
        '- 保留各对话入口的题库权限、资料引用和学习记录。','',
        '## 下载安装','',
        '- Apple 芯片 Mac 取 Apple-Silicon 的全部分卷。Intel Mac 取 Intel 的全部分卷。把同组文件放在同一目录后打开 part.dmg。',
        '- Windows 把 Setup.exe 和四个 Runtime 分卷放在同一目录，双击 Setup.exe。',
        '- 已安装用户在应用内点击「检查更新」。默认 COS，GitHub 备用时可能需要可访问 GitHub 的网络。','',
        '冻结学习核心：' + config['source_commit'],'',
    ]
    notes.write_text('\n'.join(note_lines),encoding='utf-8')
    gh('release','edit',TAG,'--notes-file',notes,'--prerelease=false','--latest')
    final=api('releases/latest')
    assert final['id']==candidate['id'] and final['tag_name']==TAG and not final['prerelease']
    write(Path('PUBLICATION-RECEIPT.json'),{'published':True,'tag':TAG,'release_id':final['id'],'source_commit':config['source_commit'],
        'release_repository_commit':config['source_carrier'],'installers':installers,'stable_assets':len(assets)+3,'preserved_history':historical,'native_runs':approval['native_runs'],'core_sha256':config['core_sha256']})
    gh('release','upload',TAG,Path('PUBLICATION-RECEIPT.json'),timeout=120)

CONFIG_URL = "https://raw.githubusercontent.com/1281504089-cell/kaixin-k12-tutor/27e8a9db96a0e32be6eb5baaddfa037bd54640f1/release-sources/20261121-diagram-1-stage.json"
CONFIG_SHA = "f3d525adfa8c5543393ec96a1c04adbbdbe7820d74dcf28f4dada896702a6683"

def prepare_archives():
    raw=bytes_for(CONFIG_URL)
    assert sha256(raw).hexdigest()==CONFIG_SHA
    lock=json.loads(raw)
    assert lock['tag']==TAG and api('releases/latest')['tag_name']=='student-20261117-k12-18'
    global rows
    rows=inventory(TAG)
    live=inventory('core-updates')
    pending=lock['archives']
    defaults={name:live[name]['digest'] for name in DEFAULTS}
    assert len(live.keys()|pending.keys())<=1000
    assert all(verified(rows[name],row) for name,row in pending.items())
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item:copy_new(*item), ((n,r) for n,r in pending.items() if n not in live)))
    final=inventory('core-updates')
    assert all(verified(final[name],row) for name,row in pending.items())
    assert {name:final[name]['digest'] for name in DEFAULTS}==defaults
    assert api('releases/latest')['tag_name']=='student-20261117-k12-18'
    write(Path('PUBLICATION-RECEIPT.json'),{'staged_archives':list(pending),'defaults_unchanged':True,'published':False})

if __name__=='__main__':
    prepare_archives()
