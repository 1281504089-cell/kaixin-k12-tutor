"""Split verified native DMG bytes into transfer sizes supported by the installed client."""
from hashlib import file_digest,sha256
from pathlib import Path
from zipfile import ZipFile
import json,os,subprocess,sys,time
n=int(sys.argv[1]);assert 1<=n<=5
run=45886832532;expected='9684dd8364986d2824971fba76707bdefa141b92'
repo=os.environ['GITHUB_REPOSITORY'];assert repo=='1281504089-cell/kaixin-k12-tutor'
def request(path):
    return json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/'+path]))
name=f'physical-intel-9719ddda-volume-{n}'
for _ in range(100):
    index=request(f'actions/runs/{run}/artifacts?per_page=70')['artifacts']
    matches=[r for r in index if r['name']==name]
    if matches:break
    time.sleep(15)
row,=matches
assert row['workflow_run']['head_sha']==expected and row['workflow_run']['id']==run and not row['expired']
src=Path('input.zip')
with src.open('xb') as out:subprocess.run(['gh','api',f'repos/{repo}/actions/artifacts/{row["id"]}/zip'],stdout=out,check=True)
with src.open('rb') as f:assert 'sha256:'+file_digest(f,'sha256').hexdigest()==row['digest']
entries=json.loads(Path(__file__).with_name('volumes.json').read_bytes())
entry=entries[str(n)]
out=Path('parts');out.mkdir()
with ZipFile(src) as z:
    info,=z.infolist()
    assert info.filename==entry['file'] and info.file_size==entry['bytes']
    checksum=sha256()
    with z.open(info) as f:
        i=1
        while block:=f.read(384*1024**2):
            (out/f'slice-{i}.bin').write_bytes(block);checksum.update(block);i+=1
    assert checksum.hexdigest()==entry['sha256'] and i-1==(entry['bytes']+384*1024**2-1)//(384*1024**2)
src.unlink()
