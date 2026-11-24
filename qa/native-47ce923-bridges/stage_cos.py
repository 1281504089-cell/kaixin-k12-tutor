"""Generate exact signed-channel delta bytes without downloading a COS object."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.with_name('native-47ce923-cross')),str(HERE.with_name('native-17bf2ce')),
             str(HERE.with_name('native-47ce923-intel-restart'))]
from draft_assets import draft,pinned_draft_asset
from retain_verified_media import LOCK,match,pinned_draft,upload_one
from rebuild import delta

def main():
    assert os.environ['GITHUB_REF']=='refs/heads/codex/desktop-native-qa-17bf2ce'
    for _ in range(84):
        try:
            new, assets=pinned_draft()
            break
        except (AssertionError, ValueError):
            sleep(10)
    else:
        raise TimeoutError('Candidate not yet staged')
    assert new['id']==457063007
    old, before=draft({'draft_title':LOCK['old_draft_title']})
    assert old['id']==456863262
    frozen=LOCK['core']
    rows=json.loads((HERE/'cos-deltas.json').read_bytes())
    output={}
    with TemporaryDirectory(prefix='scholar-cos-deltas-47ce923-') as tmp:
        work=Path(tmp)
        staged_core=work/frozen['name']
        pinned_draft_asset(assets,frozen,staged_core)
        for row in rows:
            prior,current=row['before'],row['after']
            filename=current['archive']
            assert current['toCoreSha256']==frozen['sha256']
            desired={**current,'file':filename}
            existing=assets.get(filename)
            if existing:
                assert match(existing,desired)
                asset_id=existing['id']
            else:
                source=work/prior['archive']
                pinned_draft_asset(before,{**prior,'name':source.name},source)
                output_file=work/filename
                assert delta(source,staged_core,frozen['sha256'],output_file)==current
                asset_id=upload_one(new,desired,output_file)
            checked,assets=pinned_draft()
            assert checked['id']==new['id'] and assets[filename]['id']==asset_id and match(assets[filename],desired)
            output[filename]={'id':asset_id,**current}
    evidence=Path('cos-delta-native-evidence')
    evidence.mkdir()
    (evidence/'cos-frozen-deltas.json').write_text(json.dumps(output,indent=2)+'\n')
if __name__=='__main__':
    main()
