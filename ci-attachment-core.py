"""Build the one frozen, credential-free core used by all three installers."""
import gzip,hashlib,io,json,os,subprocess,tarfile
from pathlib import Path,PurePosixPath
ROOT=Path.cwd(); CONFIG=json.loads((ROOT/'attachment-release.json').read_text())
subprocess.run(['python','bootstrap_source.py','--with-updates'],check=True)
SOURCE=ROOT/'student-source';WEB=SOURCE/'web'
DOC_FIGURES=('core/assets/figs/web-dev/','core/assets/figs/system/')
tracked=subprocess.check_output(['git','ls-files','-z'],cwd=SOURCE).decode().rstrip('\0').split('\0')
aggregate=hashlib.sha256()
for name in sorted(n for n in tracked if n!='SOURCE_FREEZE.json'):
 data=(SOURCE/name).read_bytes();aggregate.update(name.encode()+b'\0'+hashlib.sha256(data).digest())
assert aggregate.hexdigest()==CONFIG['source_files_sha256'], 'Rebuilt source differs from the frozen tested source'
# These screenshots document development; fail if runtime code starts referring to them.
for name in tracked:
 if name.startswith(('deeptutor/','deeptutor_cli/','web/app/','web/components/','web/features/','web/lib/','apps/desktop/src/')):
  data=(SOURCE/name).read_bytes()
  assert not any(prefix.removeprefix('core/').encode() in data for prefix in DOC_FIGURES), 'Restore required documentation asset: '+name
env={**os.environ,'NEXT_TELEMETRY_DISABLED':'1','NEXT_PUBLIC_API_BASE':'__NEXT_PUBLIC_API_BASE_PLACEHOLDER__','NEXT_PUBLIC_AUTH_ENABLED':'__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__'}
for command in [['npm','ci','--legacy-peer-deps','--no-audit','--no-fund'],['npm','run','build']]:subprocess.run(command,cwd=WEB,env=env,check=True)
subprocess.run(['npx','vitest','run',*CONFIG['web_tests']],cwd=WEB,env=env,check=True)
OUT=ROOT/'attachment-core';OUT.mkdir()
prior=OUT/'prior-core.tar.gz'
subprocess.run(['gh','release','download','core-updates','--pattern',CONFIG['prior_core']['archive'],'--output',str(prior)],check=True)
assert hashlib.sha256(prior.read_bytes()).hexdigest()==CONFIG['prior_core']['sha256']
archive=OUT/CONFIG['archive'];seen=set();omitted_docs=[];required={'core/deeptutor/services/student_learning/reports.py','BUILD_COMMIT','core/deeptutor/api/routers/student_uploads.py','core/deeptutor/services/student_learning/uploads.py','core/deeptutor_cli/main.py','web/server.js','web/.next/BUILD_ID'}
def add(out,name,data,mode=0o644):
 parts=PurePosixPath(name).parts
 assert not name.startswith('/') and '..' not in parts and '.git' not in parts
 assert not any(p in {'node_modules','__pycache__','.DS_Store'} for p in parts)
 assert not name.lower().endswith(('.node','.dll','.dylib','.exe','.so','.pem')) and 'data/user' not in name
 assert name not in seen,name
 seen.add(name);required.discard(name)
 info=tarfile.TarInfo(name);info.mode=mode;info.mtime=info.uid=info.gid=0;info.size=len(data);out.addfile(info,io.BytesIO(data))
with archive.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=6) as gz,tarfile.open(fileobj=gz,mode='w|',format=tarfile.PAX_FORMAT) as out:
 with tarfile.open(prior,'r:gz') as original:
  for item in original:
   if item.isfile() and item.name.startswith('core/'):
    if item.name.startswith(DOC_FIGURES):
     omitted_docs.append({'file':item.name,'bytes':item.size});continue
    file=SOURCE/item.name.removeprefix('core/')
    add(out,item.name,file.read_bytes() if file.is_file() else original.extractfile(item).read(),item.mode)
 for name in CONFIG['new_backend_files']:
  file=SOURCE/name;arc='core/'+name
  if arc not in seen:add(out,arc,file.read_bytes(),file.stat().st_mode&0o777)
 add(out,'BUILD_COMMIT',(CONFIG['source_commit']+'\n').encode())
 standalone=WEB/'.next/standalone'
 for file in sorted(standalone.rglob('*')):
  rel=file.relative_to(standalone)
  if any(p in {'node_modules','__pycache__','.DS_Store'} for p in rel.parts) or file.is_dir():continue
  assert file.is_file() and not file.is_symlink(),str(rel)
  add(out,'web/'+rel.as_posix(),file.read_bytes(),file.stat().st_mode&0o777)
assert not required,required
report={'omitted_documentation_figures':omitted_docs,'source_commit':CONFIG['source_commit'],'backend_source_commit':CONFIG['source_commit'],'frontend_build':(WEB/'.next/BUILD_ID').read_text().strip(),'archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'files':len(seen),'real_keys_used':False,'personal_records_included':False}
(OUT/'attachment-core.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
subprocess.run(['gh','release','upload',CONFIG['tag'],str(archive),str(OUT/'attachment-core.json'),'--clobber'],check=True)
