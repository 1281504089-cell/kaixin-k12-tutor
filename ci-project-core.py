"""Build the frozen sidebar repair without changing production feeds or native dependencies."""
import gzip,hashlib,io,json,os,subprocess,tarfile
from pathlib import Path,PurePosixPath
from urllib.request import Request,urlopen
ROOT=Path.cwd()
CONFIG=json.loads((ROOT/'project-release.json').read_text())
PATCH=ROOT/'project-history.patch'
assert hashlib.sha256(PATCH.read_bytes()).hexdigest()==CONFIG['patch_sha256']
subprocess.run(['python','bootstrap_source.py','--with-updates'],check=True)
SOURCE=ROOT/'student-source'
for patch in ['desktop-inplace-sync2.patch','project-history.patch']:
 subprocess.run(['git','apply','--check',str(ROOT/patch)],cwd=SOURCE,check=True)
 subprocess.run(['git','apply',str(ROOT/patch)],cwd=SOURCE,check=True)
WEB=SOURCE/'web'
env={**os.environ,'NEXT_TELEMETRY_DISABLED':'1','NEXT_PUBLIC_API_BASE':'__NEXT_PUBLIC_API_BASE_PLACEHOLDER__','NEXT_PUBLIC_AUTH_ENABLED':'__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__'}
for command in [['npm','ci','--legacy-peer-deps','--no-audit','--no-fund'],['npm','run','build']]:
 subprocess.run(command,cwd=WEB,env=env,check=True)
subprocess.run(['npx','vitest','run','tests/workspace-sidebar-history.spec.tsx','tests/session-api-history.spec.ts','tests/student-study-projects.spec.tsx','tests/sidebar-lazy-history.spec.tsx','tests/sidebar-recents.spec.tsx','tests/workspace-session-menu.spec.tsx','tests/ui-layout.spec.tsx'],cwd=WEB,env=env,check=True)
OUT=ROOT/'staged-projects';OUT.mkdir()
original=OUT/'prior-core.tar.gz'
url='https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/core-updates/kaixin-core-20261113-sync2.tar.gz'
with urlopen(Request(url,headers={'User-Agent':'Kaixin-project-release'}),timeout=120) as response,original.open('wb') as stream:
 while chunk:=response.read(1024**2):stream.write(chunk)
assert hashlib.sha256(original.read_bytes()).hexdigest()=='0b1102e17c2c9f08f0840d883ca583bf94c1dafff72c85d08ce5b4daf5b1a129'
archive=OUT/'kaixin-core-20261114-projects.tar.gz'
count=0;required={'BUILD_COMMIT','core/deeptutor_cli/main.py','web/server.js','web/.next/BUILD_ID'}
def add(output,name,data,mode=0o644):
 global count
 parts=PurePosixPath(name).parts
 assert not name.startswith('/') and '..' not in parts and '.git' not in parts
 assert not any(part in {'node_modules','__pycache__','.DS_Store'} for part in parts)
 assert not name.lower().endswith(('.node','.dll','.dylib','.exe','.so','.pem'))
 assert 'data/user' not in name
 info=tarfile.TarInfo(name);info.mode=mode;info.mtime=info.uid=info.gid=0;info.size=len(data)
 output.addfile(info,io.BytesIO(data));count+=1;required.discard(name)
with archive.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=6) as gz,tarfile.open(fileobj=gz,mode='w|',format=tarfile.PAX_FORMAT) as output:
 with tarfile.open(original,'r:gz') as prior:
  for item in prior:
   if item.isfile() and item.name.startswith('core/'):
    add(output,item.name,prior.extractfile(item).read(),item.mode)
 add(output,'BUILD_COMMIT',(CONFIG['source_commit']+'\n').encode())
 standalone=WEB/'.next/standalone'
 for file in sorted(standalone.rglob('*')):
  relative=file.relative_to(standalone)
  if any(part in {'node_modules','__pycache__','.DS_Store'} for part in relative.parts):continue
  if file.is_dir():continue
  assert file.is_file() and not file.is_symlink(),str(relative)
  add(output,'web/'+relative.as_posix(),file.read_bytes(),file.stat().st_mode&0o777)
assert not required,required
receipt={'source_commit':CONFIG['source_commit'],'backend_source_commit':'a47b05f9136ca6fb72d2f1f8a04eeb425298f358','frontend_build':(WEB/'.next/BUILD_ID').read_text().strip(),'archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'files':count,'native_modules_included':False,'unit_tests':29,'production_signature':'pending local maintainer signature'}
(OUT/'staged-projects-core.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
