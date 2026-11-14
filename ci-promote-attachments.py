"""Promote only the exact three native-tested attachment installers and signed feeds."""
import hashlib,json,os,subprocess,time
from pathlib import Path
from urllib.request import Request,urlopen

root=Path.cwd();repo='1281504089-cell/kaixin-k12-tutor'
batch=json.loads((root/'attachment-publication.json').read_text())
targets=['windows-x64','macos-x64','macos-arm64']
def gh(*args):return subprocess.check_output(['gh',*map(str,args)])
def api(path):return json.loads(gh('api','repos/'+repo+'/'+path))
def sha(file):
 with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def public(asset):
 for url in [asset['browser_download_url'],asset['url']+'?readback='+str(time.time_ns())]:
  try:
   raw=urlopen(Request(url,headers={'User-Agent':'Kaixin-Publication-Readback','Accept':'application/octet-stream'}),timeout=60).read()
   assert hashlib.sha256(raw).hexdigest()==asset['digest'].split(':')[1]
   return raw
  except Exception as error:last=error
 raise last

assert set(batch['native_runs'])==set(targets)
for target,proof in batch['native_runs'].items():
 run=api('actions/runs/'+str(proof['run_id']))
 assert run['status']=='completed' and run['head_sha']==proof['workflow_commit']
 jobs=api('actions/runs/'+str(proof['run_id'])+'/jobs')['jobs']
 assert any(j['conclusion']=='success' and j['name'].startswith('native ('+target+',') for j in jobs)
assert api('actions/runs/'+str(batch['core_run']))['conclusion']=='success'
assert api('releases/latest')['id']==batch['expected_latest_release_id']
candidate=api('releases/tags/'+batch['tag']);assert candidate['prerelease'] and not candidate['draft']
assets={a['name']:a for a in candidate['assets']};proofs={};full_files=[]
work=root/'publication-work';work.mkdir();previous=work/'previous';previous.mkdir()
for target in targets:
 report=json.loads(public(assets['verification-'+target+'.json']))
 assert report['release']==batch['tag'] and report['core_commit']==batch['core_commit']
 assert report['launcher_build']==batch['launcher_build'] and report['shell_files']==batch['shell_files']
 assert report['native_install']=='passed' and not report['real_keys_used'] and not report['real_learning_records_modified']
 assert report['network']['proxy_connections']>0 and report['network']['api_fallback_download']=='passed'
 smoke=report['native_smoke'];assert smoke['current_core_included'] and smoke['pdf']['pdf_files']==136
 study=smoke['study_reports'];assert study['passed'] and len(study['cases'])==9 and study['real_model_calls']==0
 assert all(all(row[k] for k in ['generation_failure_rejected','audit_failure_rejected','legacy_fallback_hidden_and_export_blocked','reviewed_fixture_available_and_word_exported','chat_and_reading_records_preserved']) for row in study['cases'])
 assert len(smoke['local_spoken_stt'])==2 and all(r['spoken_audio_decoded'] for r in smoke['local_spoken_stt'])
 native_evidence=work/('evidence-'+target)
 gh('run','download',batch['native_runs'][target]['run_id'],'--name','attachments-'+target,'--dir',native_evidence)
 assert json.loads((native_evidence/'verified.json').read_text())==report
 attachment=json.loads((native_evidence/'attachments.json').read_text())
 assert all(attachment[k] for k in ['raw_originals_verified','temporary_excluded_from_library','concurrent_library_uploads_saved','scanned_pdf_retrievable'])
 assert attachment['short_pdf_pages']==2 and attachment['interactive_page_ready_while_indexing_seconds']<20
 report['attachment_uploads']=attachment
 update=report['update_entry'];assert update['actual_download_install_backup_restart']=='passed' and update['check_again_current']
 assert all(update[k] for k in ['chat_preserved','task_preserved','saved_key_preserved'])
 for row in report['full_files']:
  actual=assets[row['file']];assert actual['digest']=='sha256:'+row['sha256'] and actual['size']==row['bytes']
 full_files+=report['full_files'];proofs[target]=report
assert len(full_files)==13

stable_assets={a['name']:a for a in api('releases/tags/core-updates')['assets']}
for name,expected in batch['expected_previous'].items():
 actual=stable_assets[name];assert actual['digest']=='sha256:'+expected,'Live feed changed: '+name
 raw=public(actual);(previous/name).write_bytes(raw)
 retained=work/('before-attachments-'+name);retained.write_bytes(raw);gh('release','upload',batch['tag'],retained,'--clobber')

# Download and hash all three exact native archives before switching any default.
for name,row in batch['archives'].items():
 actual=assets[name];assert actual['digest']=='sha256:'+row['sha256'] and actual['size']==row['bytes']
 gh('release','download',batch['tag'],'--pattern',name,'--dir',work)
 assert (work/name).stat().st_size==row['bytes'] and sha(work/name)==row['sha256']
for name,manifest in batch['manifests'].items():(work/name).write_text(json.dumps(manifest,indent=2)+'\n')
subprocess.run(['python','bootstrap_source.py','--with-updates'],check=True)
subprocess.run(['node','student-source/apps/desktop/scripts/check-update-batch.mjs',str(work)],check=True)

for name,row in batch['archives'].items():
 if name in stable_assets:assert stable_assets[name]['digest']=='sha256:'+row['sha256']
 else:gh('release','upload','core-updates',work/name)
for name in batch['manifests']:
 if name not in batch['expected_previous']:
  if name in stable_assets:assert public(stable_assets[name])==(work/name).read_bytes()
  else:gh('release','upload','core-updates',work/name)
switched=[]
try:
 current={a['name']:a for a in api('releases/tags/core-updates')['assets']}
 for name,expected in batch['expected_previous'].items():
  assert current[name]['digest']=='sha256:'+expected
  gh('release','upload','core-updates',work/name,'--clobber');switched.append(name)
 readback={a['name']:a for a in api('releases/tags/core-updates')['assets']}
 for name in batch['manifests']:assert public(readback[name])==(work/name).read_bytes()
 for name,row in batch['archives'].items():assert readback[name]['digest']=='sha256:'+row['sha256'] and readback[name]['size']==row['bytes']
except Exception:
 for name in switched:gh('release','upload','core-updates',previous/name,'--clobber')
 raise

gh('release','upload',batch['tag'],root/'INSTALLATION.txt','--clobber')
gh('api','-X','PATCH','repos/'+repo+'/git/refs/tags/'+batch['tag'],'-f','sha='+os.environ['GITHUB_SHA'],'-F','force=true')
gh('release','edit',batch['tag'],'--prerelease=false','--latest=true','--title','开心动力超级学霸 · 全科复盘真实性修复 2026-11-14','--notes-file',root/'RELEASE-NOTES.md')
latest=api('releases/latest');assert latest['tag_name']==batch['tag'] and not latest['prerelease']
receipt={**batch,'published_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'release_repository_commit':os.environ['GITHUB_SHA'],'release_id':latest['id'],'release_url':latest['html_url'],'full_files':full_files,'proofs':proofs,'stable_manifests_read_back':list(batch['manifests']),'physical_user_devices_tested':False,'private_key_uploaded':False}
receipt_file=root/'PUBLICATION-RECEIPT.json';receipt_file.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');gh('release','upload',batch['tag'],receipt_file,'--clobber')
print(json.dumps({'published':True,'tag':batch['tag'],'release_id':latest['id'],'platforms':targets}))
