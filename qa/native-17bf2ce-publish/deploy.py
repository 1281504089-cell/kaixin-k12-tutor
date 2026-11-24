"""Promote exact frozen GitHub feed bytes after a separate approved native gate."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest, sha256
import http.client
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

REPO = '1281504089-cell/kaixin-k12-tutor'
API = 'https://api.github.com/repos/' + REPO
HERE = Path(__file__).resolve().parent
BUILD = '17bf2ce6b062a2ba9b838b1b35b68feba2e7daa5'
TARGETS = ('macos-x64','macos-arm64','windows-x64')
STABLE = 'core-updates'
HISTORY = 'core-updates-history-20261121-resource-5'
HOSTS = {'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}


class ReleaseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url=urlsplit(newurl)
        assert url.scheme=='https' and url.hostname in HOSTS and not (url.username or url.password)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


net=build_opener(ReleaseRedirects())


def gh(*args):
    return json.loads(subprocess.check_output(['gh','api',*args],stderr=subprocess.PIPE))


def release(tag):
    return gh(f'repos/{REPO}/releases/tags/{tag}')


def assets(row):
    pages=gh('--paginate','--slurp',f'repos/{REPO}/releases/{row["id"]}/assets?per_page=100')
    flattened=[item for page in pages for item in page]
    values={item['name']:item for item in flattened}
    assert len(values)==len(flattened)
    return values


def read(path):
    return json.loads(path.read_bytes())


def evidence(path, item):
    path.write_text(json.dumps(item,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def descriptor(file):
    with file.open('rb') as stream:
        return {'bytes':file.stat().st_size,'sha256':file_digest(stream,'sha256').hexdigest()}


def match(asset, expected):
    return asset.get('state')=='uploaded' and asset.get('size')==expected['bytes'] and (
        asset.get('digest')=='sha256:'+expected['sha256'])


def download(asset, expected, target):
    assert match(asset,expected),asset['name']
    exact_url=API+f'/releases/assets/{asset["id"]}'
    assert asset['url']==exact_url
    request=Request(exact_url,headers={'Accept':'application/octet-stream','Accept-Encoding':'identity',
        'User-Agent':'Scholar-Stable-Promotion','Range':f'bytes=0-{expected["bytes"]-1}'})
    request.add_unredirected_header('Authorization','Bearer '+os.environ['GH_TOKEN'])
    digest=sha256()
    size=0
    try:
        with net.open(request,timeout=120) as response,target.open('xb') as output:
            assert response.status in (200,206)
            if response.status==206:
                assert response.headers['Content-Range']==f'bytes 0-{expected["bytes"]-1}/{expected["bytes"]}'
            while block:=response.read(1024**2):
                size+=len(block)
                assert size<=expected['bytes']
                digest.update(block)
                output.write(block)
        assert (size,digest.hexdigest())==(expected['bytes'],expected['sha256']),asset['name']
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def upload(row, name, file):
    expected=descriptor(file)
    upload_url=urlsplit(row['upload_url'].removesuffix('{?name,label}'))
    endpoint=f'/repos/{REPO}/releases/{row["id"]}/assets'
    assert upload_url.scheme=='https' and upload_url.netloc=='uploads.github.com' and upload_url.path==endpoint
    assert expected['bytes']<2*1024**3
    connection=http.client.HTTPSConnection('uploads.github.com',timeout=160,blocksize=1024**2)
    try:
        with file.open('rb') as body:
            connection.request('POST',endpoint+'?'+urlencode({'name':name}),body=body,headers={
              'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Content-Type':'application/octet-stream',
              'Content-Length':str(expected['bytes']),'Accept':'application/vnd.github+json',
              'User-Agent':'Scholar-Stable-Promotion'})
            response=connection.getresponse()
            code=response.status
            data=response.read(65536)
    finally:
        connection.close()
    if code!=201:
        raise RuntimeError(f'Upload failed ({code}) for {name}; no unexpected asset is automatically replaced')
    saved=json.loads(data)
    assert saved['name']==name and saved['size']==expected['bytes']
    for _ in range(5):
        time.sleep(1)
        checked=gh(f'repos/{REPO}/releases/assets/{saved["id"]}')
        if match(checked,expected):
            return checked
    raise RuntimeError('Uploaded asset SHA-256 was not readable: '+name)


def ensure(row, name, file, inventory):
    expected=descriptor(file)
    prior=inventory.get(name)
    if prior:
        assert match(prior,expected), name+' exists with different content'
        return prior
    added=upload(row,name,file)
    inventory[name]=added
    return added


def draft(lock):
    pages=gh('--paginate','--slurp',f'repos/{REPO}/releases?per_page=100')
    row,=(item for page in pages for item in page if item['draft'] and item['name']==lock['draft_title'])
    assert row['id']==lock['draft_id']
    return row


def native_reports(target, expected, scratch, *, bridge=False):
    artifact=gh(f'repos/{REPO}/actions/artifacts/{expected["artifact_id"]}')
    assert not artifact['expired'] and artifact['workflow_run']['id']==expected['run_id']
    prefix='native-universal-bridge-' if bridge else 'native-17bf2ce-'
    assert artifact['name']==prefix+target and artifact['size_in_bytes']<5*1024**2
    run=gh(f'repos/{REPO}/actions/runs/{expected["run_id"]}')
    assert run['status']=='completed' and run['head_sha']==expected['workflow_sha']
    expected_path='native-bridge-17bf2ce.yml' if bridge else 'native-17bf2ce-qa.yml'
    assert run['path'].split('@')[0]=='.github/workflows/'+expected_path
    local=scratch/(prefix+target+'.zip')
    with local.open('xb') as output:
        subprocess.run(['gh','api',f'repos/{REPO}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=output,check=True)
    assert local.stat().st_size<9*1024**2
    names=('result.json','retained-native-bridge.json') if bridge else (
        'native-acceptance.json','retained-native-media.json')
    with ZipFile(local) as packed:
        reports={}
        for name in names:
            member,=(info for info in packed.infolist() if Path(info.filename).name==name)
            assert member.file_size<256*1024
            raw=packed.read(member)
            assert sha256(raw).hexdigest()==expected[name]
            reports[name]=json.loads(raw)
    return reports


def native_gate(lock, approval, scratch):
    assert approval['explicit_release_ready'] is True
    assert approval['source_commit']==BUILD and approval['core_sha256']==lock['core']['sha256']
    assert approval['draft_id']==lock['draft_id']
    assert set(approval['native'])==set(approval['bridges'])==set(TARGETS)
    current=assets(draft(lock))
    prior=assets(release('student-20261121-resource-5'))
    for target in TARGETS:
        expected=approval['native'][target]
        reports=native_reports(target,expected,scratch)
        native=reports['native-acceptance.json']
        media=reports['retained-native-media.json']
        assert native['passed'] and native['source_commit']==BUILD and native['target']==target
        assert native['core']==lock['core'] and native['fresh_install']['active_commit']==BUILD
        assert native['update']['signed_restart'] and native['update']['check_again_current']
        assert native['update']['source_commit']==BUILD
        assert native['recovery']['learning_record_intact'] and native['recovery']['phase']=='recovered'
        assert media['passed'] and media['target']==target and media['draft_release_id']==lock['draft_id']
        assert media['source_commit']==BUILD and str(media['run_id'])==str(expected['run_id'])
        assert media['workflow_sha']==expected['workflow_sha']
        for item in media['installer_media']:
            rows=current if item['storage']=='draft' else prior
            row=rows[item['file']]
            assert match(row,item) and row['id']==item['asset_id']
        expected_bridge=approval['bridges'][target]
        bridge_reports=native_reports(target,expected_bridge,scratch,bridge=True)
        result=bridge_reports['result.json']
        retained=bridge_reports['retained-native-bridge.json']
        locked,=(item for item in lock['archives'] if item['name']==f'kaixin-bridge-20261124-17bf2ce-{target}.tar.gz')
        assert result['passed'] and result['target']==target and result['archive']==locked
        assert result['runtime_signature_verified'] and result['launcher_signature_verified']
        assert result['boot']['native_window'] and result['boot']['boot_commit']==BUILD
        assert result['boot']['bridge_sha256']==locked['sha256']
        assert retained['passed'] and retained['target']==target and retained['draft_release_id']==lock['draft_id']
        assert retained['source_commit']==BUILD and str(retained['run_id'])==str(expected_bridge['run_id'])
        assert retained['workflow_sha']==expected_bridge['workflow_sha']
        assert retained['bridge']=={'file':locked['name'],'bytes':locked['bytes'],'sha256':locked['sha256']}
        row=current[locked['name']]
        assert match(row,locked) and row['id']==retained['asset_id']


def remove_exact(name, expected, inventory):
    current=gh(f'repos/{REPO}/releases/assets/{expected["id"]}')
    assert current['name']==name and current['digest']==expected['digest']
    assert current['size']==expected['size'] and current['state']=='uploaded'
    subprocess.run(['gh','api','--method','DELETE',f'repos/{REPO}/releases/assets/{current["id"]}'],
                   capture_output=True,check=True)
    inventory.pop(name,None)
    time.sleep(1)


def verified_body(row,expected,folder,name):
    file=folder/name
    download(row,expected,file)
    return file


def installed_aliases(lock):
    return [item for item in lock['feeds'] if item['name'] not in lock['previous']]


def main():
    if sys.flags.optimize:
        raise RuntimeError('Verification assertions are required')
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--approval',type=Path)
    parser.add_argument('--approval-sha256')
    args=parser.parse_args()
    if args.apply:
        assert os.environ.get('GITHUB_REF')=='refs/heads/codex/desktop-stable-17bf2ce'
        assert args.approval and descriptor(args.approval)['sha256']==args.approval_sha256
    lock=read(HERE/'deployment-lock.json')
    assert lock['source_commit']==BUILD
    args.evidence.mkdir(parents=True,exist_ok=True)
    subprocess.run(['node',str(HERE/'verify.mjs')],check=True)
    staging=draft(lock)
    staged=assets(staging)
    live=release(STABLE)
    history=release(HISTORY)
    assert live['id']==lock['stable_release_id'] and not live['draft'] and not live['immutable']
    assert history['id']==lock['history_release_id'] and not history['draft'] and not history['immutable']
    live_objects=assets(live)
    historical=assets(history)
    for item in lock['archives']:
        assert match(staged[item['name']],item)
    for item in lock['feeds']:
        assert descriptor(HERE/'feed/github'/item['name'])=={k:item[k] for k in ('bytes','sha256')}
    for name,item in lock['previous'].items():
        current=live_objects[name]
        assert match(current,item)
        if current['id']!=item['id']:
            assert match(staged['previous-github-'+name],item),'A changed prior-ID needs the durable exact rollback backup'
    for name,item in lock['protected'].items():
        assert match(live_objects[name],item) and live_objects[name]['id']==item['id']
    pending={item['name'] for item in installed_aliases(lock)+lock['archives']}
    removing={item['name'] for item in lock['retire']}
    assert removing.isdisjoint(set(lock['protected'])|set(lock['previous'])|pending)
    assert len(set(live_objects)-removing|pending)<=992
    assert len(set(historical)|removing)<=1000
    for item in lock['retire']:
        if item['name'] in live_objects:
            row=live_objects[item['name']]
            assert match(row,item) and row['id']==item['id']
        else:
            assert match(historical[item['name']],item),'Missing previously archived descriptor'
    with TemporaryDirectory(prefix='scholar-stable-deploy-',dir=os.environ.get('RUNNER_TEMP')) as temp:
        work=Path(temp)
        backups={}
        for name,item in lock['previous'].items():
            backups[name]=verified_body(live_objects[name],item,work,name)
            assert backups[name].read_bytes()==(HERE/'previous'/name).read_bytes()
        archive_dir=work/'old-inactive'
        archive_dir.mkdir()
        def get_old(item):
            row=live_objects.get(item['name']) or historical[item['name']]
            return verified_body(row,item,archive_dir,item['name'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(get_old,lock['retire']))
        subprocess.run(['node',str(HERE/'verify.mjs'),str(archive_dir)],check=True)
        evidence(args.evidence/'verified-read-only.json',{'source_commit':BUILD,'stable_release':live['id'],
            'history_release':history['id'],'draft_release':staging['id'],'before':len(live_objects),
            'preserved_old_default_sha256':{name:descriptor(file)['sha256'] for name,file in backups.items()},
            'archived_small_descriptors':len(removing),'pending_new':len(pending)})
        if not args.apply:
            return
        native_gate(lock,read(args.approval),work)
        for name,file in backups.items():
            backup=ensure(staging,'previous-github-'+name,file,staged)
            readback=verified_body(backup,descriptor(file),work,'verify-previous-github-'+name)
            assert readback.read_bytes()==file.read_bytes()
        for item in lock['retire']:
            name=item['name']
            saved=ensure(history,name,archive_dir/name,historical)
            checked=verified_body(saved,item,work,'verify-archived-'+name)
            assert checked.read_bytes()==(archive_dir/name).read_bytes()
            if name in live_objects:
                remove_exact(name,live_objects[name],live_objects)
        for item in lock['archives']:
            name=item['name']
            found=live_objects.get(name)
            if found:
                assert match(found,item),name
                continue
            local=verified_body(staged[name],item,work,name)
            ensure(live,name,local,live_objects)
            local.unlink()
        for item in installed_aliases(lock):
            ensure(live,item['name'],HERE/'feed/github'/item['name'],live_objects)
        current=assets(live)
        for item in installed_aliases(lock)+lock['archives']:
            assert match(current[item['name']],item)
        assert all(match(current[name],item) and current[name]['id']==live_objects[name]['id']
                   for name,item in lock['previous'].items())
        completed=[]
        def stop_gracefully(*_):
            raise KeyboardInterrupt('Deployment interrupted during canonical activation')
        signal.signal(signal.SIGTERM,stop_gracefully)
        try:
            for name,item in lock['previous'].items():
                remove_exact(name,live_objects[name],live_objects)
                path=HERE/'feed/github'/name
                uploaded=ensure(live,name,path,live_objects)
                read_back=verified_body(uploaded,descriptor(path),work,'activated-'+name)
                assert read_back.read_bytes()==path.read_bytes()
                completed.append(name)
        except BaseException:
            rollback_errors=[]
            rollback_live=assets(live)
            for name,path in backups.items():
                try:
                    present=rollback_live.get(name)
                    if present and match(present,descriptor(path)):
                        verified=present
                    else:
                        if present:
                            assert match(present,descriptor(HERE/'feed/github'/name)), 'Unexpected third-party stable change'
                            remove_exact(name,present,rollback_live)
                        verified=ensure(live,name,path,rollback_live)
                    returned=verified_body(verified,descriptor(path),work,'rollback-'+name)
                    assert returned.read_bytes()==path.read_bytes()
                except Exception as error:
                    rollback_errors.append(f'{name}: {error}')
            evidence(args.evidence/'activation-rollback.json',{'activated_before_error':completed,'rollback_errors':rollback_errors})
            if rollback_errors:
                raise RuntimeError('Stable rollback incomplete: '+'; '.join(rollback_errors))
            raise
        evidence(args.evidence/'activated.json',{'passed':True,'source_commit':BUILD,'stable_release':live['id'],
            'draft_release':staging['id'],'activated':completed,'core':lock['core'],
            'original_default_sha256':{name:descriptor(file)['sha256'] for name,file in backups.items()}})


if __name__=='__main__':
    main()
