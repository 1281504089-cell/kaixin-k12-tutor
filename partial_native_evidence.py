"""Reuse completed Intel5 checks from the exact failed-run artifact."""
import hashlib,io,json,zipfile
from ci_picture_fresh import validate_native_page_views
REPO='1281504089-cell/kaixin-k12-tutor'
ARTIFACT={'id':14363427934,'bytes':9511640,'sha256':'f58d4be0ee58e8773783bb23b4bffb3ff801a42bd07848fac0d9a2bc1539a574','run_id':44146541944,'workflow_commit':'8a190f60c5043d7a3b334635d23def9351e60e7e','job_id':134263108457,'source_lock_sha256':'36d851b7865fbdbb86355764198351cb69c72647f4842e5fcd9ca1c7087cf0d9'}
ENTRIES={'oldest_launcher_entry':{'file':'oldest-update-entry.json','bytes':95767,'sha256':'694a7e8d525ff7c6a4d665d6ce65318d25d0512e8c95e5ca339b823c508c17f6'},'update_entry':{'file':'update-entry.json','bytes':96051,'sha256':'80a73595edbab1adc8ebf2831f6686430f4d993a274820697e1b5e6752a97395'}}
FRESH={'file':'picture-fresh-ui.json','bytes':32314,'sha256':'32ebe30703713498e8f80608fa2a6ae32645c0efa770062fa234cb894e98a801'}
def validate_partial_lock(lock):
 assert lock['target']=='macos-x64' and lock['candidate_tag']=='student-20261117-k12-5'
 assert lock['source_commit']=='9328240380d13ef75435434a8c901028ea4470dc'
 assert lock['resume_artifact']==ARTIFACT and lock['reused_complete_entries']==ENTRIES
 assert 'partial_native_evidence.py' in lock['recipe_inputs_sha256']
 if 'reused_fresh_picture_ui' in lock:
  assert lock['reused_fresh_picture_ui']==FRESH
  assert lock['recipe_inputs_sha256']['ci-picture-fresh.cjs']=='11889ea909eef882f9293a98b0e558d5c6fcef6e693cd0ef8a526797128eda72'

def validate_completed_entries(lock,files):
 validate_partial_lock(lock)
 old_raw=files['reuse-lock.json'];assert hashlib.sha256(old_raw).hexdigest()==ARTIFACT['source_lock_sha256']
 old=json.loads(old_raw)
 for key in ['target','candidate_tag','candidate_release_id','source_commit','included_manifest','prior_manifest','core_asset','bridge','frozen_stage','candidate_files','signed_runtime_assets','native_pages','bank_revision','picture_count','picture_manifest_sha256','runtime_exclusion_count','runtime_exclusion_kinds','runtime_exclusion_ledger_sha256']:
  assert old[key]==lock[key], 'Completed-entry source changed: '+key
 assert old['recipe_inputs_sha256']['ci-k12-library-ui.cjs']==lock['recipe_inputs_sha256']['ci-k12-library-ui.cjs']
 entries={}
 for key,row in ENTRIES.items():
  raw=files[row['file']];assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
  value=json.loads(raw);assert value['actual_download_install_backup_restart']=='passed' and value['check_again_current']
  assert all(value[k] is True for k in ['chat_preserved','task_preserved','saved_key_preserved'])
  assert value['from_runtime']==lock['prior_manifest']['runtimeId'] and value['to_launcher']=='20261117-updater-2'
  oldest=key=='oldest_launcher_entry'
  assert value['selected_archive']==(lock['bridge']['name'] if oldest else lock['core_asset']['name'])
  assert value['selected_base_runtime']==(None if oldest else lock['included_manifest']['baseRuntimeId'])
  expected='1.7.1-kaixin-20261117-k12-5-macos-x64-universal' if oldest else lock['included_manifest']['runtimeId']
  assert value['to_runtime']==expected
  if oldest:assert value['signed_launcher_restarted'] and value['old_pid']!=value['restarted_pid']
  else:assert value['download_progress_visible'] and value['downloaded_bytes_visible']
  ui=value['k12_library'];assert ui['passed'] and ui['actualNativeRenderer'] and ui['bank_revision']==lock['bank_revision']
  validate_native_page_views(ui,lock['native_pages']['ui_fixture'])
  for view in ui['views']:assert all(view['preparedPicture'][k] for k in ['native_http_image_sha_verified','body_dom_before_image_response','second_history_restore'])
  entries[key]=value
 return entries

def validate_completed_fresh(lock,files):
 validate_partial_lock(lock)
 assert lock['reused_fresh_picture_ui']==FRESH
 old_raw=files['reuse-lock.json'];assert hashlib.sha256(old_raw).hexdigest()==ARTIFACT['source_lock_sha256']
 old=json.loads(old_raw)
 for name in ['ci_picture_fresh.py','native-k12-fixture.py']:
  assert old['recipe_inputs_sha256'][name]==lock['recipe_inputs_sha256'][name]
 raw=files[FRESH['file']];assert len(raw)==FRESH['bytes'] and hashlib.sha256(raw).hexdigest()==FRESH['sha256']
 value=json.loads(raw)
 assert value['passed'] and value['production_launcher_source_byte_identical'] and value['qa_code_only_in_disposable_copy']
 assert value['active_runtime_id']==lock['included_manifest']['runtimeId']
 assert value['k12_library']['diagnostic_entry']=='fresh' and value['k12_library']['model_calls']==0
 validate_native_page_views(value['k12_library'],lock['native_pages']['ui_fixture'])
 return value

def validate_partial_archive(lock,raw):
 validate_partial_lock(lock)
 assert len(raw)==ARTIFACT['bytes'] and hashlib.sha256(raw).hexdigest()==ARTIFACT['sha256']
 reuse_fresh='reused_fresh_picture_ui' in lock
 required={'reuse-lock.json',*(v['file'] for v in ENTRIES.values())};files={}
 if reuse_fresh:required.add(FRESH['file'])
 with zipfile.ZipFile(io.BytesIO(raw)) as archive:
  prefixes=('k12-oldest-','k12-current-')+(('k12-fresh-','k12-library-fresh-') if reuse_fresh else ())
  selected=[i for i in archive.infolist() if i.filename in required or i.filename.startswith(prefixes) and i.filename.endswith(('.json','.png','.html'))]
  assert len({i.filename for i in selected})==len(selected)
  assert sum(i.file_size for i in selected)<64*1024**2
  for item in selected:
   assert '/' not in item.filename and '\\' not in item.filename and item.file_size<16*1024**2
   files[item.filename]=archive.read(item)
 assert required.issubset(files)
 result={'entries':validate_completed_entries(lock,files),'files':files}
 if reuse_fresh:result['fresh_picture_ui']=validate_completed_fresh(lock,files)
 return result

def fetch_partial_archive(lock,api,gh):
 validate_partial_lock(lock)
 meta=api('actions/artifacts/'+str(ARTIFACT['id']))
 assert meta['id']==ARTIFACT['id'] and meta['size_in_bytes']==ARTIFACT['bytes'] and meta['digest']=='sha256:'+ARTIFACT['sha256'] and not meta['expired']
 run=api('actions/runs/'+str(ARTIFACT['run_id']))
 assert run['status']=='completed' and run['conclusion']=='failure' and run['head_sha']==ARTIFACT['workflow_commit']
 jobs=api('actions/runs/'+str(ARTIFACT['run_id'])+'/jobs')['jobs']
 assert any(j['id']==ARTIFACT['job_id'] and j['conclusion']=='failure' for j in jobs)
 return validate_partial_archive(lock,gh('api','repos/'+REPO+'/actions/artifacts/'+str(ARTIFACT['id'])+'/zip'))
