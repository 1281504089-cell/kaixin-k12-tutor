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
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zipfile import ZipFile

REPO = '1281504089-cell/kaixin-k12-tutor'
API = 'https://api.github.com/repos/' + REPO
HERE = Path(__file__).resolve().parent
BUILD = '9c0193385e64c36028d0717ad43d51606c8e7ed5'
TARGETS = ('macos-x64','macos-arm64','windows-x64')
STABLE = 'core-updates'
HISTORY = 'core-updates-history-20261121-resource-5'
STUDENT_TAG = 'student-20261126-teaching-figures-9c019338'
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
    row=gh(f'repos/{REPO}/releases/{lock["draft_id"]}')
    assert row['id']==lock['draft_id']
    assert row['name']==lock['draft_title'] if row['draft'] else row['tag_name']==STUDENT_TAG
    return row


def native_reports(target, expected, scratch, *, variant='native'):
    bridge = variant == 'bridge'
    name = ('bridge-native-9c019338-' if bridge else 'native-9c019338-') + target
    workflow = 'bridge-native-9c019338.yml' if bridge else 'native-9c019338.yml'
    names = ('bridge-acceptance.json',) if bridge else ('native-acceptance.json', 'retained-native-media.json')
    job_name = ('native-fallback (' if bridge else 'native (') + target + ','
    artifact=gh(f'repos/{REPO}/actions/artifacts/{expected["artifact_id"]}')
    assert not artifact['expired'] and artifact['workflow_run']['id']==expected['run_id']
    assert artifact['name']==name and artifact['size_in_bytes']<5*1024**2
    run=gh(f'repos/{REPO}/actions/runs/{expected["run_id"]}')
    assert run['status']=='completed' and run['head_sha']==expected['workflow_sha']
    assert run['path'].split('@')[0]=='.github/workflows/'+workflow
    jobs=gh(f'repos/{REPO}/actions/runs/{expected["run_id"]}/jobs?per_page=100')['jobs']
    accepted,=(job for job in jobs if job['name'].startswith(job_name))
    assert accepted['conclusion']=='success'
    local=scratch/(name+'.zip')
    with local.open('xb') as output:
        subprocess.run(['gh','api',f'repos/{REPO}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=output,check=True)
    assert local.stat().st_size<9*1024**2
    with ZipFile(local) as packed:
        reports={}
        for name in names:
            member,=(info for info in packed.infolist() if Path(info.filename).name==name)
            assert member.file_size<256*1024
            raw=packed.read(member)
            assert sha256(raw).hexdigest()==expected[name]
            reports[name]=json.loads(raw)
    return reports


def native_install_reports(target, expected, scratch):
    combined = native_reports(target, expected, scratch)
    return combined['native-acceptance.json'], combined['retained-native-media.json']


def cos_gate(lock):
    origin='https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
    for name,wanted in lock['cos_stable'].items():
        with urlopen(origin+name,timeout=30) as result:
            payload=result.read(wanted['bytes']+1)
        assert (len(payload),sha256(payload).hexdigest())==(wanted['bytes'],wanted['sha256']), name
        assert payload==(HERE/'feed/github'/name).read_bytes()
    assert set(lock['cos_stable'])==set(lock['previous'])


def native_gate(lock, approval, scratch):
    assert approval['explicit_release_ready'] is True
    assert approval['source_commit']==BUILD and approval['core_sha256']==lock['core']['sha256']
    assert approval['draft_id']==lock['draft_id']
    assert set(approval['native'])==set(approval['bridges'])==set(TARGETS)
    assert approval['cos_stable_passed'] is True and approval['cos_stable']==lock['cos_stable']
    current=assets(draft(lock))
    prior=assets(release('student-20261121-resource-5'))
    delta,=(item for item in lock['archives'] if item['name'].startswith('delta-'))
    for target in TARGETS:
        expected=approval['native'][target]
        native,media=native_install_reports(target,expected,scratch)
        assert native['passed'] and native['source_commit']==BUILD and native['target']==target
        assert native['core']==lock['core'] and native['fresh_install']['active_commit']==BUILD
        upgraded=native['update']
        assert upgraded['signed_restart'] and upgraded['check_again_current'] and upgraded['source_commit']==BUILD
        assert upgraded['launcher_build']==lock['launcher_build'] and upgraded['launcher_files_verified']>0
        assert (upgraded['network']['bytes'],upgraded['network']['sha256'])==(delta['bytes'],delta['sha256'])
        assert native['recovery']['learning_record_intact'] and native['recovery']['phase']=='recovered'
        assert not native['cos_used'] and not native['real_learning_data_used']
        assert media['passed'] and media['target']==target and media['draft_release_id']==lock['draft_id']
        assert media['source_commit']==BUILD and str(media['run_id'])==str(expected['run_id'])
        assert media['workflow_sha']==expected['workflow_sha']
        assert [{key:item[key] for key in ('file','bytes','sha256')} for item in media['installer_media']]==native['installer_media']
        for item in media['installer_media']:
            rows=current if item['storage']=='draft' else prior
            row=rows[item['file']]
            assert match(row,item) and row['id']==item['asset_id']
        item=native_reports(target,approval['bridges'][target],scratch,variant='bridge')['bridge-acceptance.json']
        locked,=(entry for entry in lock['archives'] if entry['name']==f'kaixin-bridge-20261126-9c019338-{target}.tar.gz')
        assert item['passed'] and item['target']==target and item['commit']==BUILD
        assert item['archive']=={'file':locked['name'],'bytes':locked['bytes'],'sha256':locked['sha256']}
        assert item['native']['native_window'] and item['native']['boot_commit']==BUILD
        assert item['native']['bridge_sha256']==locked['sha256'] and item['native']['core_sha256']==lock['core']['sha256']
        assert item['draft_id']==lock['draft_id'] and item['whole_package_cos_downloads']==0
        row=current[locked['name']]
        assert match(row,locked) and row['id']==item['asset_id']


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
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--stage',action='store_true')
    mode.add_argument('--apply',action='store_true')
    parser.add_argument('--approval',type=Path)
    parser.add_argument('--approval-sha256')
    args=parser.parse_args()
    if args.stage or args.apply:
        assert os.environ.get('GITHUB_REF')=='refs/heads/codex/desktop-stable-9c019338'
    if args.apply:
        assert args.approval and descriptor(args.approval)['sha256']==args.approval_sha256
    lock=read(HERE/'deployment-lock.json')
    assert lock['source_commit']==BUILD
    cos_gate(lock)
    args.evidence.mkdir(parents=True,exist_ok=True)
    subprocess.run(['node',str(HERE/'verify.mjs')],check=True)
    staging=draft(lock)
    staged=assets(staging)
    if not args.apply:
        for _ in range(58):
            if all(item['name'] in staged for item in lock['archives']):
                break
            time.sleep(15)
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
    patch=lock['patch']
    patch_file=HERE/patch['name']
    assert descriptor(patch_file)=={key:patch[key] for key in ('bytes','sha256')}
    current_defaults={row['name']:row for row in lock['feeds'] if row['name'] in lock['previous']}
    if args.apply and all(match(live_objects.get(name,{}),row) for name,row in current_defaults.items()):
        with TemporaryDirectory(prefix='scholar-stable-readback-') as temp:
            work=Path(temp)
            native_gate(lock,read(args.approval),work)
            for item in installed_aliases(lock)+lock['archives']:
                assert match(live_objects[item['name']],item)
            for name,item in current_defaults.items():
                assert verified_body(live_objects[name],item,work,name).read_bytes()==(HERE/'feed/github'/name).read_bytes()
                old=lock['previous'][name]
                saved=verified_body(staged['previous-github-'+name],old,work,'previous-'+name)
                assert saved.read_bytes()==(HERE/'previous'/name).read_bytes()
        evidence(args.evidence/'activated.json',{'passed':True,'source_commit':BUILD,'stable_release':live['id'],
            'draft_release':staging['id'],'activated':list(current_defaults),'core':lock['core'],
            'original_default_sha256':{name: row['sha256'] for name,row in lock['previous'].items()},
            'resumed_readback':True})
        return
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
        if not (args.stage or args.apply):
            return
        if args.apply:
            native_gate(lock,read(args.approval),work)
        saved_patch=ensure(staging,patch['name'],patch_file,staged)
        assert match(saved_patch,patch)
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
        evidence(args.evidence/'staged.json',{'passed':True,'source_commit':BUILD,'stable_release':live['id'],
            'pending_archive_count':len(lock['archives']),'pending_alias_count':len(installed_aliases(lock)),
            'archived_signed_history':len(lock['retire']),'draft_release':staging['id'],'patch_asset_id':saved_patch['id']})
        if args.stage:
            return
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
