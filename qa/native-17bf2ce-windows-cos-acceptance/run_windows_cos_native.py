"""Native Windows 095875 COS baseline + exact local delta to 17bf2ce, no COS transfer."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
NATIVE = HERE.with_name('native-17bf2ce')
BRIDGES = HERE.with_name('native-17bf2ce-bridges')
sys.path[:0] = [str(NATIVE),str(BRIDGES)]
from ci_fresh_install import REPO, digest, download, verify_signature
from ci_repackage import read, write
from draft_assets import pinned_draft_asset
from native_electron import launcher_files, setup
from retain_verified_media import pinned_draft
from run_native import LOCK, MARKER, MEMORY, probed_update

TARGET='windows-x64'
PREVIOUS='runtime-windows-x64-20261122-textbook-interactive-3-base-42be25309949.json'
SELECTED='runtime-windows-x64-20261124-17bf2ce-base-42be25309949.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    assert os.name=='nt' and platform.machine()=='AMD64'
    assert os.environ['GITHUB_REPOSITORY']==REPO and os.environ['GITHUB_REF']=='refs/heads/codex/desktop-native-qa-17bf2ce'
    output=args.evidence.resolve()
    output.mkdir(parents=True,exist_ok=False)
    prior, published, final=map(read,(HERE/'previous-signed-runtime.json',HERE/PREVIOUS,HERE/SELECTED))
    default=HERE/'runtime-windows-x64.json'
    activate, delta=published['coreDelta'], final['coreDelta']
    assert published['commit']=='095875b15cdb1afe9c6db5db56ccc65c9015c1f9' and final['commit']==LOCK['source_commit']
    assert published['baseRuntimeId']==final['baseRuntimeId']==prior['runtimeId']
    assert activate['fromCoreSha256']==prior['corePayloadSha256'] and activate['toCoreSha256']==delta['fromCoreSha256']==published['corePayloadSha256']
    assert delta['toCoreSha256']==final['corePayloadSha256']==LOCK['core']['sha256']
    original_delta=HERE/activate['archive']
    assert (original_delta.stat().st_size,digest(original_delta))==(activate['bytes'],activate['sha256'])
    donor=read(BRIDGES/'donor-lock.json')['targets'][TARGET]['asset']
    assert donor['id']==777242649 and (prior['archive'],prior['sha256'])==(donor['name'],donor['sha256'])
    with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP'],prefix='windows-cos-signed-acceptance-') as path:
        work=Path(path)
        draft, assets=pinned_draft()
        assert draft['id']==456863262
        terminal=pinned_draft_asset(assets,{**delta,'name':delta['archive']},work/delta['archive'])
        assert terminal['github_asset_id']==787698259
        descriptor=pinned_draft_asset(assets,LOCK['launcher'],work/LOCK['launcher']['name'])
        row=json.loads(subprocess.check_output(['gh','api',f'repos/{REPO}/releases/assets/{donor["id"]}']))
        donor_receipt=download({'tag_name':'core-updates','assets':[row]},donor,work/donor['name'])
        os.environ.pop('GH_TOKEN',None)
        os.environ.pop('GITHUB_TOKEN',None)
        _, resources, executable=setup(work,TARGET)
        seed=resources/'seed'; seed.mkdir()
        (work/donor['name']).rename(seed/donor['name'])
        shutil.copyfile(HERE/'previous-signed-runtime.json',seed/'runtime.json')
        app=resources/'app'
        launcher_files(seed/donor['name'],app)
        old_launcher=read(app/'manifest.json')
        verify_signature(resources,prior,old_launcher)
        official_launcher=read(work/LOCK['launcher']['name'])
        for manifest in (published,final,read(default)):
            verify_signature(resources,manifest,official_launcher)
        shutil.copyfile(BRIDGES/'icon.ico',app/'assets/icon.ico')
        write(app/'package.json',{'name':'kaixin-super-scholar','productName':'开心动力超级学霸','version':'1.7.1',
                                 'main':'src/entry.mjs','type':'module','kaixinLauncherBuild':old_launcher['buildId']})
        profile=work/'isolated-profile'; memory=profile/'workspace'/MEMORY
        memory.parent.mkdir(parents=True); memory.write_bytes(MARKER)
        copied=work/PREVIOUS; shutil.copyfile(HERE/PREVIOUS,copied)
        shutil.copyfile(original_delta,work/activate['archive'])
        with (output/'stage-095875.log').open('wb') as out:
            subprocess.run(['node',str(HERE/'seed-published-core.mjs'),str(app),str(seed/'runtime.json'),str(copied),str(profile)],
                           stdout=out,stderr=subprocess.STDOUT,check=True,timeout=900)
        assert read(profile/'active.json')==published
        update=probed_update(executable,resources,profile,published,final,default,HERE/SELECTED,work/delta['archive'],output,TARGET)
        assert update['network']['bytes']==delta['bytes'] and update['network']['sha256']==delta['sha256']
        assert update['from']==published['runtimeId'] and update['to']==final['runtimeId']
        assert memory.read_bytes()==MARKER
        write(output/'windows-cos-native-acceptance.json',{'passed':True,'source_commit':final['commit'],
            'starting_core':published['corePayloadSha256'],'donor':donor_receipt,'launcher':descriptor,
            'staging_delta':activate,'exact_final_delta':terminal,'cos_full_downloads':0,'native_update':update})

if __name__=='__main__':
    main()
