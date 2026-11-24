"""Retain the verified inputs in a new private release draft before native jobs run."""
from pathlib import Path
import json
import os
import sys
from tempfile import TemporaryDirectory
from time import sleep

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent/'native-17bf2ce'),str(HERE.parent/'native-47ce923-intel-restart')]
from ci_repackage import read,write
from draft_assets import draft,gh,pinned_draft_asset
from rebuild import delta as rebuild_delta
from retain_verified_media import match as match_media,upload_one

LOCK=read(HERE/'input-lock.json')
OLD=read(HERE.parent/'native-17bf2ce/input-lock.json')
REPO='1281504089-cell/kaixin-k12-tutor'
CORE=LOCK['core']


def match(row,expected):
    return match_media(row,{**expected,'file':expected['name']})


def create_or_get_draft(work):
    rows=gh('--paginate','--slurp',f'repos/{REPO}/releases?per_page=100')
    same=[row for page in rows for row in page if row['draft'] and row['name']==LOCK['draft_title']]
    if not same:
        request=work/'draft.json'
        write(request,{'tag_name':'scholar-native-qa-47ce923','name':LOCK['draft_title'],
                       'draft':True,'prerelease':True,'make_latest':'false','target_commitish':os.environ['GITHUB_SHA']})
        gh('--method','POST',f'repos/{REPO}/releases','--input',str(request))
    target,assets=draft(LOCK)
    assert target['draft'] and target['id']!=456863262
    return target,assets


def main():
    marker=Path('native-47ce923-input-evidence')
    marker.mkdir()
    assert os.environ['GITHUB_REF']=='refs/heads/codex/desktop-native-qa-17bf2ce'
    with TemporaryDirectory(prefix='scholar-stage-47ce923-',dir=os.environ['RUNNER_TEMP']) as directory:
        work=Path(directory)
        for _ in range(84):
            prior,source=draft(OLD)
            assert prior['id']==456863262
            if CORE['name'] in source and match(source[CORE['name']],CORE):
                break
            sleep(10)
        else:
            raise TimeoutError('The exact replacement core is not available from the Intel staging run')
        paths={}
        core=work/CORE['name']
        pinned_draft_asset(source,CORE,core)
        paths[CORE['name']]=(core,CORE)
        launcher=LOCK['launcher']
        path=HERE.parent/'native-47ce923-intel-restart'/launcher['name']
        paths[launcher['name']]=(path,launcher)
        for target,row in LOCK['targets'].items():
            for feed in (row['default'],row['compatible']):
                paths[feed['name']]=(HERE/feed['name'],feed)
            exact=row['delta']
            name=exact['archive']
            if name in paths:
                continue
            path=work/name
            wanted={**exact,'name':name}
            if name in source and match(source[name],wanted):
                pinned_draft_asset(source,wanted,path)
            else:
                old={**row['previous_delta'],'name':row['previous_delta']['archive']}
                previous=work/old['name']
                pinned_draft_asset(source,old,previous)
                assert rebuild_delta(previous,core,CORE['sha256'],path)==exact
            paths[name]=(path,wanted)
        release,assets=create_or_get_draft(work)
        ids={}
        for name,(file,expected) in paths.items():
            if name in assets:
                assert match(assets[name],expected)
                ids[name]=assets[name]['id']
            else:
                ids[name]=upload_one(release,{**expected,'file':name},file)
            _,assets=draft(LOCK)
            assert assets[name]['id']==ids[name] and match(assets[name],expected)
        write(marker/'signed-native-inputs.json',{'release_id':release['id'],'source_commit':LOCK['source_commit'],
                                                  'core':CORE,'assets':ids})


if __name__=='__main__':
    main()
