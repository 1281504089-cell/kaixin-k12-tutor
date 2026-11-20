"""Run the production check-update IPC against the exact signed candidate payload."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
from urllib.request import Request,urlopen

def materials_baseline(root,target,evidence):
 lock=json.loads((root/'materials-upgrade-lock.json').read_text());row=lock['targets'][target]
 directory=root/'materials-baseline'
 if directory.exists():
  manifest=directory/'runtime.json';proof=json.loads((evidence/'materials-baseline-download.json').read_text())
  assert json.loads(manifest.read_text())==row['manifest']
  assert proof['full_archive_verified'] and proof['sha256']==row['asset']['sha256'] and proof['bytes']==row['asset']['bytes']
  return manifest
 directory.mkdir()
 archive=directory/row['manifest']['archive'];asset=row['asset']
 with urlopen(Request(asset['url'],headers={'User-Agent':'Kaixin-Materials-Upgrade-Verification'}),timeout=60) as response,archive.open('xb') as out:
  assert response.geturl().startswith(('https://github.com/','https://release-assets.githubusercontent.com/','https://objects.githubusercontent.com/'))
  shutil.copyfileobj(response,out,8*1024**2)
 with archive.open('rb') as stream:assert archive.stat().st_size==asset['bytes'] and hashlib.file_digest(stream,'sha256').hexdigest()==asset['sha256']
 manifest=directory/'runtime.json';manifest.write_text(json.dumps(row['manifest'],indent=2))
 (evidence/'materials-baseline-download.json').write_text(json.dumps({'target':target,'runtime_id':row['manifest']['runtimeId'],'bytes':asset['bytes'],'sha256':asset['sha256'],'anonymous_download':True,'full_archive_verified':True,'launcher_build':lock['launcher_build']},indent=2))
 return manifest

def verify_update_entry(root,target,install,resources,home,evidence,*,legacy=False,materials=False):
 assert isinstance(legacy,bool) and isinstance(materials,bool)
 entry='materials-oldest-update-entry' if materials and legacy else 'materials-update-entry' if materials else 'oldest-update-entry' if legacy else 'update-entry'
 launcher='oldest-launcher-src' if legacy else 'materials-launcher-src' if materials else None
 base=json.loads((resources/'seed/runtime.json').read_text());native=home/'runtimes'/base['runtimeId']
 active=json.loads((home/'active.json').read_text());prior=materials_baseline(root,target,evidence) if materials else root/'prior-update/runtime.json'
 # Generate synthetic audio with the frozen core before testing its real reinstall over the prior core.
 python=native/('python/python.exe' if target.startswith('windows') else 'python/bin/python3')
 qa_home=home/'workspace'
 qa_env={**os.environ,'PYTHONPATH':str(home/'runtimes'/active['runtimeId']/'core'),'DEEPTUTOR_HOME':str(qa_home),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','KX_NATIVE_AUDIO_QA':'1'}
 audio_file=evidence/'audio-seed.json'
 subprocess.run([str(python),str(root/'native-audio-fixture.py'),'--expect-home',str(qa_home),'--out',str(audio_file)],env=qa_env,check=True,timeout=120)
 (qa_home/'.science-fixture-allowed').touch()
 science_file=evidence/'science-seed.json'
 subprocess.run([str(python),str(root/'science_seed.py'),'--source',str(home/'runtimes'/active['runtimeId']/'core'),'--home',str(qa_home),'--output',str(science_file)],env=qa_env,check=True,timeout=120)
 (qa_home/'.k12-release-qa-allowed').touch()
 k12_file=evidence/'k12-seed.json'
 subprocess.run([str(python),str(root/'native-k12-fixture.py'),'--core',str(home/'runtimes'/active['runtimeId']/'core'),'--home',str(qa_home),'--out',str(k12_file)],env=qa_env,check=True,timeout=120)
 # Install the real prior signed code without changing the verified native base.
 code="import{readFile,writeFile}from'node:fs/promises';import{pathToFileURL}from'node:url';const{installBundle}=await import(pathToFileURL(process.argv[1]));const key=await readFile(process.argv[2]);const installed=await installBundle(process.argv[3],process.argv[4],key);await writeFile(process.argv[4]+'/active.json',JSON.stringify(installed.manifest));"
 subprocess.run(['node','--input-type=module','-e',code,str(resources/'app/src/bundles.mjs'),str(resources/'app/assets/runtime-public.pem'),str(prior),str(home)],check=True)
 old=json.loads(prior.read_text());assert old['commit']!=active['commit']
 if materials:
  native=home/'runtimes'/old['runtimeId']
  (prior.parent/old['archive']).unlink(missing_ok=True)
 shutil.rmtree(home/'runtimes'/active['runtimeId'])
 python=native/('python/python.exe' if target.startswith('windows') else 'python/bin/python3')
 def python_probe(code,manifest):
  result=subprocess.check_output([str(python),'-c',code],env={**os.environ,'PYTHONPATH':str(home/'runtimes'/manifest['runtimeId']/'core'),'DEEPTUTOR_HOME':str(home/'workspace'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1'},timeout=120)
  return json.loads(result.decode('utf-8').strip().splitlines()[-1])
 seeded=python_probe('''
import asyncio,json
from deeptutor.services.session import get_session_store
from deeptutor.services.task_board import get_task_board_store,CreateCard
from deeptutor.services.config.model_catalog import get_model_catalog_service
async def run():
 s=get_session_store();r=await s.create_session(title='attachment upgrade preservation');await s.add_message(r['id'],'user','synthetic retained learning record')
 t=get_task_board_store().create(CreateCard(title='synthetic retained task'),'').cards[-1]
 c=get_model_catalog_service();d=c.load();d['services']['llm']={'active_profile_id':'fixture','active_model_id':'fixture','profiles':[{'id':'fixture','name':'fixture','binding':'openai','base_url':'http://127.0.0.1:9/v1','api_key':'fixture-only-not-a-real-key','models':[{'id':'fixture','model':'gpt-4o-mini','name':'fixture'}]}]};c.save(d)
 from pathlib import Path
 namespace={};exec(compile(Path('native-materials-fixture.py').read_text(encoding='utf-8'),'native-materials-fixture.py','exec'),namespace)
 return {'session_id':r['id'],'task_id':t.id,**namespace['seed']()}
print(json.dumps(asyncio.run(run())))
''',old)
 seeded.update(audio=json.loads(audio_file.read_text(encoding='utf-8')),science=json.loads(science_file.read_text(encoding='utf-8')),k12=json.loads(k12_file.read_text(encoding='utf-8')))
 (home/'attachment-fixture.json').write_text(json.dumps(seeded))
 source=resources.parent.parent if target.startswith('macos') else install
 probe=root/('update-entry.app' if target.startswith('macos') else 'update-entry')
 shutil.copytree(source,probe,symlinks=True,ignore=lambda directory,names:[n for n in names if n in {'seed','update'}] if Path(directory)==resources else [])
 copied=probe/'Contents/Resources' if target.startswith('macos') else probe/'resources'
 # The production launcher always verifies its seed manifest, even when an older core is already installed.
 (copied/'seed').mkdir();shutil.copyfile(resources/'seed/runtime.json',copied/'seed/runtime.json')
 package=copied/'app/package.json';pkg=json.loads(package.read_text());pkg['main']='qa/update-flow.cjs';package.write_text(json.dumps(pkg,ensure_ascii=False))
 if launcher:
  shutil.rmtree(copied/'app/src');shutil.copytree(root/launcher,copied/'app/src')
 (copied/'app/qa').mkdir()
 shutil.copyfile(root/'ci-update-flow.cjs',copied/'app/qa/update-flow.cjs')
 shutil.copyfile(root/'ci-materials-ui.cjs',copied/'app/qa/materials-ui.cjs')
 for name in ['ci-chat-audio-ui.cjs','audio-card-probe.cjs','native-html-speech-diagnostic.cjs','science-ui.cjs','ci-turn-preview.cjs','ci-k12-library-ui.cjs']:
  shutil.copyfile(root/name,copied/'app/qa'/name)
 expected_src=root/launcher if legacy else resources/'app/src'
 if materials:expected_src=root/launcher
 for file in expected_src.iterdir():
  if file.is_file():assert (copied/'app/src'/file.name).read_bytes()==file.read_bytes()
 if materials and not legacy:
  frozen=json.loads((root/'materials-upgrade-lock.json').read_text())['launcher_files_sha256']
  assert {f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in expected_src.iterdir() if f.is_file()}==frozen
 if target.startswith('macos'):
  subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(probe)],check=True);exe=probe/'Contents/MacOS/开心动力超级学霸'
 else:exe=probe/'开心动力超级学霸.exe'
 from_launcher='a47b05f9136ca6fb72d2f1f8a04eeb425298f358' if legacy else '20261114-unified' if materials else json.loads((root/'launcher-manifest.json').read_text())['buildId']
 timeout=2800 if target=='macos-x64' and os.environ.get('KX_K12_16_INTEL_SCENE') in {'current','materials','materials-oldest'} else 1400
 subprocess.run([str(exe)],env={**os.environ,'OPEN_DEEPTUTOR_TEST_HOME':str(home),'KX_UPDATE_FLOW_RESULT':str(evidence/(entry+'.json')),'KX_CANDIDATE_TAG':json.loads((root/'attachment-batch.json').read_text())['tag'],'KX_EXPECT_SHELL_RESTART':'1' if launcher else '0','KX_START_LAUNCHER_BUILD':from_launcher},check=True,timeout=timeout)
 deadline=time.monotonic()+timeout
 while not (evidence/(entry+'.json')).is_file():
  error=evidence/(entry+'.json.error.json')
  assert not error.is_file(),error.read_text(encoding='utf-8') if error.exists() else ''
  assert time.monotonic()<deadline,'The detached application did not finish its real restart test'
  time.sleep(1)
 result=json.loads((evidence/(entry+'.json')).read_text())
 if materials:
  assert result['from_runtime']==old['runtimeId']
  if legacy:
   assert result['selected_base_runtime'] is None
   assert result['selected_archive']=='kaixin-bridge-'+json.loads((root/'attachment-batch.json').read_text())['tag'].removeprefix('student-')+'-'+target+'.tar.gz'
  else:
   assert result['selected_base_runtime']==old['runtimeId']
   assert result['selected_archive']==json.loads((root/'attachment-release.json').read_text())['archive']
 subprocess.run([str(python),'-c','import psutil,sys; p=int(sys.argv[1]); psutil.Process(p).wait(timeout=60) if psutil.pid_exists(p) else None',str(result['restarted_pid'])],check=True,timeout=70)
 after=json.loads((home/'active.json').read_text());assert after['commit']==active['commit']
 preserved=python_probe('''
import asyncio,json,os
from pathlib import Path
from deeptutor.services.session import get_session_store
from deeptutor.services.task_board import get_task_board_store
from deeptutor.services.config.model_catalog import get_model_catalog_service
fixture=json.loads((Path(os.environ['DEEPTUTOR_HOME']).parent/'attachment-fixture.json').read_text())
async def run():
 s=await get_session_store().get_session_with_messages(fixture['session_id'])
 return {'chat_preserved':any(m.get('content')=='synthetic retained learning record' for m in s['messages']),'task_preserved':any(c.id==fixture['task_id'] and c.title=='synthetic retained task' for c in get_task_board_store().read().cards),'saved_key_preserved':'fixture-only-not-a-real-key' in json.dumps(get_model_catalog_service().load())}
r=asyncio.run(run());assert all(r.values()),r;print(json.dumps(r))
''',after)
 file=evidence/(entry+'.json');report=json.loads(file.read_text());report.update(preserved);file.write_text(json.dumps(report,indent=2));shutil.rmtree(probe)
 return report
