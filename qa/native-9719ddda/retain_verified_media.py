"""Retain only installer bytes used by this job's successful native tests."""

import argparse
from hashlib import file_digest
import http.client
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit

import sys
OLD_RECIPE=Path(__file__).resolve().parent.parent/'native-17bf2ce'
sys.path.append(str(OLD_RECIPE))

from ci_fresh_install import REPO, metadata
from draft_assets import draft

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE/'input-lock.json').read_text(encoding='utf-8'))
TYPES = {'macos-arm64':'arm64','macos-x64':'x86_64','windows-x64':'AMD64'}
LIMIT = 2 * 1024**3


def match(asset, wanted):
    return (asset['name'],asset['state'],asset['size'],asset.get('digest')) == (
        wanted['file'],'uploaded',wanted['bytes'],'sha256:'+wanted['sha256'])


def sha(file):
    with file.open('rb') as body:
        return file_digest(body,'sha256').hexdigest()


def verify_receipt(target, evidence):
    report = json.loads((evidence/'native-acceptance.json').read_text(encoding='utf-8'))
    assert report['passed'] is True and report['target']==target and report['runner']==TYPES[target]
    assert report['run_id'] == os.environ['GITHUB_RUN_ID'] and report['workflow_sha']==os.environ['GITHUB_SHA']
    assert report['source_commit']==LOCK['source_commit'] and report['core']==LOCK['core']
    assert report['fresh_install']['active_commit']==LOCK['source_commit']
    assert report['update']['passed'] and report['update']['source_commit']==LOCK['source_commit']
    assert report['update']['signed_restart'] and report['update']['check_again_current']
    assert report['recovery']['phase']=='recovered' and report['recovery']['learning_record_intact']
    assert not report['cos_used'] and not report['real_learning_data_used']
    directory=Path(report['retained_media_path']).resolve(strict=True)
    scratch=Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    assert directory.name=='fresh-installer-media' and directory.parent.parent==scratch
    assert directory.parent.name.startswith('native-scholar-9719ddda-')
    names=set()
    for entry in report['installer_media']:
        name=entry['file']
        assert re.fullmatch(r'[a-zA-Z0-9.+_-]+',name) and name not in names
        assert 0 < entry['bytes'] < LIMIT
        if target=='windows-x64':
            assert re.fullmatch(r'Kaixin-Super-Scholar-Windows-v1\.7\.1-(?:Setup\.exe|Runtime\.00[1-4])',name)
        else:
            brand='Apple-Silicon' if target=='macos-arm64' else 'Intel'
            assert re.fullmatch(rf'Kaixin-Super-Scholar-MacOS-{brand}-v1\.7\.1-20261127-9719ddda-native-qa-part(?:\.dmg|\.00[2-5]\.dmgpart)',name)
        actual=directory/name
        assert actual.is_file() and not actual.is_symlink()
        assert (actual.stat().st_size,sha(actual))==(entry['bytes'],entry['sha256']),name
        names.add(name)
    assert names=={p.name for p in directory.iterdir()}
    return report,directory


def upload_one(release, asset, pathname):
    url=urlsplit(release['upload_url'].removesuffix('{?name,label}'))
    expected=f'/repos/{REPO}/releases/{release["id"]}/assets'
    assert url.scheme=='https' and url.netloc=='uploads.github.com' and url.path==expected
    assert not (url.query or url.fragment)
    conn=http.client.HTTPSConnection('uploads.github.com',timeout=160,blocksize=1024**2)
    try:
        with pathname.open('rb') as body:
            conn.request('POST',expected+'?'+urlencode({'name':asset['file']}),body=body,headers={
              'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Content-Type':'application/octet-stream',
              'Content-Length':str(asset['bytes']),'Accept':'application/vnd.github+json',
              'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Scholar-Verified-Native-Media'})
            answer=conn.getresponse()
            if answer.status!=201:
                answer.read(65536)
                raise RuntimeError(f'GitHub rejected {asset["file"]} (HTTP {answer.status}); inspect draft before retrying.')
            row=json.loads(answer.read(65536))
    finally:
        conn.close()
    assert (row['name'],row['state'],row['size']) == (asset['file'],'uploaded',asset['bytes'])
    return row['id']


def pinned_draft():
    release, assets=draft(LOCK)
    expected=LOCK['core']
    staged=assets.get(expected['name'])
    assert release['draft'] is True and staged is not None
    assert (staged['state'],staged['size'],staged['digest'])==('uploaded',expected['bytes'],'sha256:'+expected['sha256'])
    return release,assets


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',choices=TYPES)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    assert os.environ['GITHUB_REF']=='refs/heads/codex/desktop-native-qa-5af77432'
    report,directory=verify_receipt(args.target,args.evidence)
    initial,_=pinned_draft()
    draft_id=initial['id']
    result=[]
    profile=LOCK['targets'][args.target]
    old_parts={row['name']:row for row in profile['baseline_installers'] if '-Runtime.' in row['name']}
    previous=metadata('student-20261121-resource-5') if old_parts else None
    part_ids=(776311172,776313305,776315773,776318399)
    if previous:
        assert previous['id']==453846225 and not previous['draft'] and not previous['prerelease']
    for asset in report['installer_media']:
        name=asset['file']
        release,current=pinned_draft()
        assert release['id']==draft_id,'The private QA draft changed'
        if name in current:
            assert match(current[name],asset),'Existing draft asset differs. No replacement attempted.'
            result.append({**asset,'storage':'draft','asset_id':current[name]['id'],'uploaded_this_job':False})
        elif name in old_parts:
            original=old_parts[name]
            assert (asset['bytes'],asset['sha256'])==(original['bytes'],original['sha256'])
            published,= (row for row in previous['assets'] if row['name']==name)
            assert match(published,asset) and published['id']==part_ids[int(name.rsplit('.',1)[1])-1]
            result.append({**asset,'storage':'prior_verified_release','asset_id':published['id'],
                           'release_id':previous['id'],'url':published['browser_download_url']})
        else:
            asset_id=upload_one(release,asset,directory/name)
            for attempt in range(5):
                readback,rows=pinned_draft()
                assert readback['id']==draft_id
                saved=rows.get(name)
                if saved and match(saved,asset) and saved['id']==asset_id:
                    break
                time.sleep(3)
            else:
                raise RuntimeError('GitHub did not return the expected installer SHA-256: '+name)
            result.append({**asset,'storage':'draft','asset_id':asset_id,'uploaded_this_job':True})
    proof={'passed':True,'draft_release_id':draft_id,'source_commit':LOCK['source_commit'],'target':args.target,
           'run_id':report['run_id'],'workflow_sha':report['workflow_sha'],'installer_media':result}
    with (args.evidence/'retained-native-media.json').open('x',encoding='utf-8') as sink:
        json.dump(proof,sink,indent=2)
        sink.write('\n')
    print(f'{args.target}: {len(result)} exact installed media entries retained and checked.')


if __name__=='__main__':
    main()
