"""Make the exact verified archive draft the public student download."""
from argparse import ArgumentParser
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import Request

from deploy import API, BUILD, HERE, REPO, STUDENT_TAG as TAG, TARGETS, assets, evidence, gh, match, native_install_reports, net, read


TITLE = '开心动力超级学霸桌面版 · 出题、配图和互动实验 9719ddda'


def anonymous_assets(tag):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Kaixin-Desktop-Release-Readback'}
    with net.open(Request(API + '/releases/tags/' + tag, headers=headers), timeout=40) as response:
        assert response.status == 200
        visible = json.load(response)
    assert visible['tag_name'] == tag and not visible['draft']
    rows = {row['name']:row for row in visible['assets']}
    assert len(rows) == len(visible['assets'])
    return visible['id'], rows


def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--evidence',type=Path,required=True)
    a=p.parse_args()
    assert os.environ.get('GITHUB_REF')=='refs/heads/codex/desktop-stable-9719ddda'
    lock,approval=read(HERE/'deployment-lock.json'),read(a.approval)
    active=read(a.evidence/'activated.json')
    assert active['passed'] and active['source_commit']==approval['source_commit']==BUILD
    assert active['core']==lock['core'] and active['draft_release']==lock['draft_id']
    row=gh(f'repos/{REPO}/releases/{lock["draft_id"]}')
    assert row['id']==lock['draft_id'] and (row['draft'] or row['tag_name']==TAG)
    assert row['name']==(lock['draft_title'] if row['draft'] else TITLE)
    exact=assets(row)
    prior=assets(gh(f'repos/{REPO}/releases/tags/student-20261121-resource-5'))
    all_keys={}
    public_installers={}
    installer_rows={target:[] for target in TARGETS}
    with TemporaryDirectory(prefix='verified-release-notes-') as directory:
        work=Path(directory)
        notes=(HERE/'release-notes.md').read_text(encoding='utf-8').rstrip()
        for target in TARGETS:
            _,media=native_install_reports(target,approval['native'][target],work)
            platform_name={'macos-x64':'Intel Mac','macos-arm64':'Apple 芯片 Mac','windows-x64':'Windows x64'}[target]
            notes+='\n\n## '+platform_name+' 完整安装\n\n'
            for item in media['installer_media']:
                name=item['file']
                old=item['storage']=='prior_verified_release'
                lookup=prior if old else exact
                expected=lookup[name]
                assert match(expected,item) and expected['id']==item['asset_id']
                tag='student-20261121-resource-5' if old else TAG
                url=f'https://github.com/{REPO}/releases/download/{tag}/{name}'
                notes+=f'- [{name}]({url})\n'
                all_keys[name]=item['asset_id']
                public_installers[name]=(tag,item)
                installer_rows[target].append({**item,"download":url})
        core=exact[lock['core']['name']]
        assert match(core,lock['core'])
        patch=lock['patch']['name']
        assert match(exact[patch],lock['patch'])
        notes+='\n\n## 发行源码\n\n'
        notes+=f'从已同步的源码基线 `9c019338` 应用本页补丁后，Git 源码树为 `{lock["source_tree"]}`。\n'
        notes+=f'[下载本批源码补丁](https://github.com/{REPO}/releases/download/{TAG}/{patch})\n'
        for supplement in lock['source_supplements']:
            name=supplement['name']
            assert match(exact[name],supplement)
            notes+=f"- [{supplement['label']}](https://github.com/{REPO}/releases/download/{TAG}/{name})\n"
        if row['draft']:
            content={'tag_name':TAG,'target_commitish':lock['source_carrier_commit'],
                     'name':TITLE,'body':notes,'draft':False,'prerelease':False,'make_latest':'true'}
            assert a.approval.name=='ACTIVATE.json' and approval['explicit_release_ready'] is True
            input_file=work/'submission.json'
            input_file.write_text(json.dumps(content,ensure_ascii=False),encoding='utf-8')
            subprocess.run(['gh','api','--method','PATCH',f'repos/{REPO}/releases/{row["id"]}',
                             '--input',str(input_file)],stdout=subprocess.DEVNULL,check=True)
    public=gh(f'repos/{REPO}/releases/tags/{TAG}')
    latest=gh(f'repos/{REPO}/releases/latest')
    assert latest['id']==public['id']==row['id'] and not public['draft'] and not public['prerelease']
    assert public['target_commitish']==lock['source_carrier_commit']
    public_tag,previous_tag=TAG,'student-20261121-resource-5'
    visible_id,visible=anonymous_assets(public_tag)
    _,previous_visible=anonymous_assets(previous_tag)
    assert visible_id == public['id']
    for name,(tag,item) in public_installers.items():
        view=visible if tag==public_tag else previous_visible
        assert match(view[name],item) and view[name]['id']==item['asset_id']
    assert match(visible[lock['core']['name']],lock['core']) and visible[patch]['id']==exact[patch]['id']
    evidence(a.evidence/'student-github-published.json',{'published':True,'tag':TAG,'release_id':public['id'],
        'url':public['html_url'],'source_commit':BUILD,'core_sha256':lock['core']['sha256'],
        'source_carrier_commit':public['target_commitish'],'installer_asset_ids':all_keys,
        'anonymous_metadata_verified':True,'installers':{target:[item for item in group] for target,group in installer_rows.items()}})


if __name__=='__main__':
    main()
