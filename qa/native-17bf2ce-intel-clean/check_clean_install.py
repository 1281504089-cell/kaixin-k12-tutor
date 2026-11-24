"""Verify a full Intel installer independently of the legacy upgrade path."""
from argparse import ArgumentParser
from pathlib import Path
import os
import platform
import shutil
import sys
import tempfile


HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.with_name('native-17bf2ce')))
from ci_fresh_install import verify_signature
from ci_repackage import install_native, prepare_candidate, read, replace_included_core, write
from draft_assets import historical_installers, pinned_draft_asset
from retain_verified_media import match, pinned_draft, upload_one
from run_native import LOCK, boot, sha, stop, wait_ready


TARGET = 'macos-x64'


def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,required=True)
    a=p.parse_args()
    assert sys.platform=='darwin' and platform.machine()=='x86_64'
    assert os.environ['GITHUB_REF']=='refs/heads/codex/desktop-native-qa-17bf2ce'
    output=a.evidence.resolve();output.mkdir(parents=True)
    original,assets=pinned_draft()
    assert original['id']==456863262
    row=LOCK['targets'][TARGET]
    base=Path(os.environ['RUNNER_TEMP'])
    work=Path(tempfile.mkdtemp(prefix='intel-clean-scholar-',dir=base))
    try:
        names=[LOCK['core'],LOCK['launcher'],row['compatible']]
        draft_receipts=[pinned_draft_asset(assets,item,work/item['name']) for item in names]
        prior=work/'prior-installers'
        input_bytes=sum(row['bytes'] for row in LOCK['targets'][TARGET]['baseline_installers'])
        assert shutil.disk_usage(work).free>input_bytes*4, 'Intel clean installation needs staging space'
        write(output/'downloads.json',{'draft':draft_receipts,'old':historical_installers(row,prior)})
        seeded=work/'previous-application-shell'
        resources,_=install_native(TARGET,prior,seeded)
        manifest=read(work/row['compatible']['name']); launcher=read(work/LOCK['launcher']['name'])
        verify_signature(resources,manifest,launcher)
        assert read(resources/'seed/runtime.json')['runtimeId']==manifest['baseRuntimeId']
        assert manifest['commit']==LOCK['source_commit'] and manifest['sha256']==LOCK['core']['sha256']
        replace_included_core(resources,work/LOCK['core']['name'],manifest,launcher,{x['file']:x for x in launcher['files']})
        media=work/'installer'
        outputs=prepare_candidate(TARGET,'student-20261124-17bf2ce-native-qa',seeded,resources,prior,
                                  {'files':row['baseline_installers']},media,HERE)
        files=[{'file':path.name,'bytes':path.stat().st_size,'sha256':sha(path)} for path in outputs]
        resources,executable=install_native(TARGET,media,work/'clean-install')
        assert sha(resources/'update'/manifest['archive'])==LOCK['core']['sha256']
        profile=work/'empty-study-profile';profile.mkdir()
        running=boot(executable,profile,output/'fresh-install.log')
        try:
            opened=wait_ready(running,profile,manifest)
        finally:
            stop(running)
            runtime=profile/'logs/runtime.log'
            if runtime.is_file():shutil.copyfile(runtime,output/'fresh-runtime.log')
        write(output/'intel-clean-install.json',{'passed':True,'target':TARGET,'source_commit':LOCK['source_commit'],
            'fresh_install':opened,'core':LOCK['core'],'installer_media':files,'upgrade_tested_by_this_job':False,
            'run_id':os.environ['GITHUB_RUN_ID'],'workflow_sha':os.environ['GITHUB_SHA']})
        retained=[]
        for item in files:
            path=media/item['file'];assert (path.stat().st_size,sha(path))==(item['bytes'],item['sha256'])
            release,rows=pinned_draft();assert release['id']==original['id']
            existing=rows.get(item['file'])
            if existing:
                assert match(existing,item)
                asset_id=existing['id']
            else:
                asset_id=upload_one(release,item,path)
            current,saved=pinned_draft();assert current['id']==original['id']
            assert saved[item['file']]['id']==asset_id and match(saved[item['file']],item)
            retained.append({**item,'asset_id':asset_id,'storage':'draft'})
        write(output/'intel-clean-retained-media.json',{'passed':True,'target':TARGET,'source_commit':LOCK['source_commit'],
          'draft_release_id':original['id'],'run_id':os.environ['GITHUB_RUN_ID'],'workflow_sha':os.environ['GITHUB_SHA'],
          'installer_media':retained})
    finally:
        shutil.rmtree(work)


if __name__=='__main__':
    main()
