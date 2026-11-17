"""Promote only the exact three native-tested attachment installers and signed feeds."""
import hashlib,json,os,subprocess,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse

root=Path.cwd();repo='1281504089-cell/kaixin-k12-tutor'
batch=json.loads((root/'attachment-publication.json').read_text())
assert batch.get('prepared') is True and batch['tag']=='student-20261117-k12-2', 'Owner must prepare the exact final three-native-tested publication batch'
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

def download_public_archive(asset,destination):
 partial=destination.with_name(destination.name+'.partial')
 for url in [asset['browser_download_url'],asset['url']+'?readback='+str(time.time_ns())]:
  try:
   with urlopen(Request(url,headers={'User-Agent':'Kaixin-Anonymous-Archive-Readback','Accept':'application/octet-stream'}),timeout=90) as response,partial.open('xb') as output:
    final=urlparse(response.geturl());assert final.scheme=='https' and final.hostname in {'github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}
    received=0
    while chunk:=response.read(8*1024**2):
     received+=len(chunk);assert received<=asset['size'],'Oversized public archive'
     output.write(chunk)
   assert partial.stat().st_size==asset['size'] and sha(partial)==asset['digest'].split(':')[1]
   partial.rename(destination)
   return {'anonymous_download':True,'file':destination.name,'bytes':received,'sha256':sha(destination)}
  except Exception as error:
   partial.unlink(missing_ok=True);last=error
 raise last

assert set(batch['native_runs'])==set(targets)
for target,proof in batch['native_runs'].items():
 run=api('actions/runs/'+str(proof['run_id']))
 assert run['status']=='completed' and run['head_sha']==proof['workflow_commit']
 jobs=api('actions/runs/'+str(proof['run_id'])+'/jobs')['jobs']
 assert any(j['conclusion']=='success' and j['name'].startswith('native ('+target+',') for j in jobs)
core_run=api('actions/runs/'+str(batch['core_run']));assert core_run['status']=='completed' and core_run['conclusion']=='success' and core_run['head_sha']==batch['core_workflow_commit']
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
 assert smoke['k12_api']['prepared_picture_bindings']==batch['picture_count']
 assert smoke['k12_api']['prepared_picture_manifest_sha256']==batch['picture_manifest_sha256']
 fresh=report['fresh_picture_ui'];assert fresh['passed'] and fresh['production_launcher_source_byte_identical'] and fresh['qa_code_only_in_disposable_copy']
 for ui in [fresh['k12_library'],*[report[key]['k12_library'] for key in ['update_entry','oldest_launcher_entry']]]:
  assert ui['passed'] and ui['actualNativeRenderer'] and len(ui['views'])==4
  for view in ui['views']:
   assert all(view['preparedPicture'][key] for key in ['native_http_image_sha_verified','body_dom_before_image_response','second_history_restore'])
 assert smoke['k12_api']['passed'] and smoke['k12_api']['model_calls']==0 and smoke['k12_api']['teacher_fields_absent']
 assert all(smoke['k12_api'][key] for key in ['fts_search_passed','fts_empty_query_passed','item_quality_metadata_matched'])
 assert smoke['k12_api']['runtime_isolated_count']==batch['runtime_exclusion_count'] and smoke['k12_api']['physical_readable_count']-smoke['k12_api']['effective_readable_count']==batch['runtime_exclusion_count']
 assert smoke['k12_api']['runtime_exclusion_kinds']==batch['runtime_exclusion_kinds'] and smoke['k12_api']['runtime_exclusion_ledger_sha256']==batch['runtime_exclusion_ledger_sha256']
 for field in ['update_entry','oldest_launcher_entry']:
  k12=report[field]['k12_library'];assert k12['passed'] and k12['actualNativeRenderer'] and k12['model_calls']==0 and len(k12['views'])==4
  assert k12['bank_revision']==smoke['k12_api']['bank_revision']
 study=smoke['study_reports'];assert study['passed'] and len(study['cases'])==9 and study['real_model_calls']==0
 assert all(all(row[k] for k in ['generation_failure_rejected','audit_failure_rejected','legacy_fallback_hidden_and_export_blocked','reviewed_fixture_available_and_word_exported','chat_and_reading_records_preserved']) for row in study['cases'])
 preview=report['update_entry']['quick_preview'];assert preview['passed'] and len(preview['views'])==4 and preview['conversationSwitchCleared'] and all(v['cardWithinMessagePane'] for v in preview['views'])
 assert len(smoke['local_spoken_stt'])==2 and all(r['spoken_audio_decoded'] for r in smoke['local_spoken_stt'])
 native_evidence=work/('evidence-'+target)
 gh('run','download',batch['native_runs'][target]['run_id'],'--name','attachments-'+target,'--dir',native_evidence)
 assert json.loads((native_evidence/'verified.json').read_text())==report
 for size in ['390x844','1366x900']:
  screenshot=native_evidence/('quick-preview-'+size+'.png');raw=screenshot.read_bytes();assert len(raw)>1000 and raw.startswith(b'\x89PNG\r\n\x1a\n')
  public_screenshot=work/('quick-preview-'+target+'-'+size+'.png');public_screenshot.write_bytes(raw);gh('release','upload',batch['tag'],public_screenshot,'--clobber')
 attachment=json.loads((native_evidence/'attachments.json').read_text())
 assert all(attachment[k] for k in ['raw_originals_verified','temporary_excluded_from_library','concurrent_library_uploads_saved','scanned_pdf_retrievable'])
 assert attachment['short_pdf_pages']==2 and attachment['interactive_page_ready_while_indexing_seconds']<20
 report['attachment_uploads']=attachment
 update=report['update_entry'];assert update['actual_download_install_backup_restart']=='passed' and update['check_again_current']
 legacy=report['oldest_launcher_entry'];assert legacy['actual_download_install_backup_restart']=='passed' and legacy['signed_launcher_restarted'] and legacy['check_again_current']
 assert legacy['old_pid']!=legacy['restarted_pid'] and legacy['to_launcher']==batch['launcher_build']
 assert update['download_progress_visible'] and update['downloaded_bytes_visible'] and update['to_launcher']==batch['launcher_build']
 bulk=update['library_bulk_upload'];assert bulk['saved_files']==21 and all(bulk[k] for k in ['multiple','library_retention','originals_byte_identical','original_preview_opened','held_real_chunk','chat_and_settings_navigation','appended_while_active','completed_in_chat','document_not_reloaded','draft_preserved','picker_reference_byte_identical','no_duplicate_upload_or_new_chat','html_safe_preview','source_toggle','native_math_display'])
 assert json.loads((native_evidence/'library-bulk.json').read_text())==bulk
 audio=update['chat_audio'];assert audio['passed'] and len(audio['productionCards'])==2
 assert audio['selection']['chatRequests']==0 and audio['selection']['errorShown']
 assert all(card['sha256']==audio['productionCards'][0]['sha256'] for card in audio['productionCards'])
 assert json.loads((native_evidence/'chat-audio.json').read_text())==audio
 science=update['science_formulas'];assert science['passed'] and len(science['views'])==16 and len(science['originalEdits'])>=18 and science['cleanup']['debuggerDetached'] and science['cleanup']['deviceMetricsCleared']
 assert bulk['device_speech']['diagnosticOnly'] and 'nativeEnded' in bulk['device_speech']['diagnostic']
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
anonymous_archives=[]
for name,row in batch['archives'].items():
 actual=assets[name];assert actual['digest']=='sha256:'+row['sha256'] and actual['size']==row['bytes']
 anonymous_archives.append(download_public_archive(actual,work/name))
 assert (work/name).stat().st_size==row['bytes'] and sha(work/name)==row['sha256']
assert len(anonymous_archives)==len(batch['archives'])==4
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
from publication_transaction import publish_transaction
class GitHubPublication:
 def release(self,tag):return api('releases/tags/'+tag)
 def latest(self):return api('releases/latest')
 def tag_sha(self,tag):return api('git/ref/tags/'+tag)['object']['sha']
 def asset_bytes(self,tag,name):
  asset=next((a for a in self.release(tag)['assets'] if a['name']==name),None)
  return public(asset) if asset else None
 def upload_bytes(self,tag,name,raw):
  directory=work/'transaction-upload';directory.mkdir(exist_ok=True)
  file=directory/name;file.write_bytes(raw)
  gh('release','upload',tag,file,'--clobber')
 def delete_asset(self,tag,name):
  asset=next((a for a in self.release(tag)['assets'] if a['name']==name),None)
  if asset:gh('api','-X','DELETE','repos/'+repo+'/releases/assets/'+str(asset['id']))
 def set_tag(self,tag,commit):gh('api','-X','PATCH','repos/'+repo+'/git/refs/tags/'+tag,'-f','sha='+commit,'-F','force=true')
 def edit_release(self,release_id,fields,latest):
  payload={**fields,'make_latest':'true' if latest else 'false'}
  file=work/'release-edit.json';file.write_text(json.dumps(payload))
  gh('api','-X','PATCH','repos/'+repo+'/releases/'+str(release_id),'--input',file)
def make_receipt(latest):
 return {**batch,'published_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'release_repository_commit':os.environ['GITHUB_SHA'],'release_id':latest['id'],'release_url':latest['html_url'],'full_files':full_files,'proofs':proofs,'stable_manifests_read_back':list(batch['manifests']),'anonymous_archives':anonymous_archives,'physical_user_devices_tested':False,'private_key_uploaded':False}
def check_immutable():
 current={a['name']:a for a in api('releases/tags/core-updates')['assets']}
 for name in batch['manifests']:
  if name not in batch['expected_previous']:assert public(current[name])==(work/name).read_bytes()
 for name,row in batch['archives'].items():assert current[name]['digest']=='sha256:'+row['sha256'] and current[name]['size']==row['bytes']
 return True
receipt=publish_transaction(GitHubPublication(),tag=batch['tag'],commit=os.environ['GITHUB_SHA'],
 pointers={name:(work/name).read_bytes() for name in batch['expected_previous']},
 previous={name:(previous/name).read_bytes() for name in batch['expected_previous']},
 installation=(root/'INSTALLATION.txt').read_bytes(),receipt_file=root/'PUBLICATION-RECEIPT.json',
 receipt_factory=make_receipt,journal_file=root/'PUBLICATION-TRANSACTION.json',
 title=batch.get('title','开心动力超级学霸 · 题库与资料来源 2026-11-17'),notes=(root/'RELEASE-NOTES.md').read_text(),
 expected_latest_id=batch['expected_latest_release_id'],check_immutable=check_immutable)
print(json.dumps({'published':True,'tag':batch['tag'],'release_id':receipt['release_id'],'platforms':targets}))
