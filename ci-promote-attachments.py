"""Promote only the exact three native-tested attachment installers and signed feeds."""
import hashlib,json,os,re,subprocess,time
import sys
if __name__ == "__main__" and os.environ.get("GITHUB_REF_NAME") == "codex/k12-publish-20261117-18":
    subprocess.run([sys.executable, "ci-online18-publish.py"], check=True)
    sys.exit(0)
if __name__ == "__main__" and os.environ.get("GITHUB_REF_NAME") == "codex/k12-publish-20261117-17-online":
    subprocess.run([sys.executable, "ci-online17-publish.py"], check=True)
    sys.exit(0)
from concurrent.futures import ThreadPoolExecutor
from ci_picture_fresh import validate_native_page_views, validate_native_page_api
from ci_repackage import validate_installer_files
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse

root=Path.cwd();repo='1281504089-cell/kaixin-k12-tutor'
batch=json.loads((root/'attachment-publication.json').read_text())
release_config=json.loads((root/'attachment-release.json').read_text())
assert batch.get('prepared') is True and release_config.get('prepared') is True and batch['tag']==release_config['tag'] and batch['core_commit']==release_config['source_commit'] and batch['tag'].startswith('student-20261117-'), 'Owner must prepare the exact final three-native-tested publication batch'
targets=['windows-x64','macos-x64','macos-arm64']
def gh(*args):return subprocess.check_output(['gh',*map(str,args)])
def api(path):return json.loads(gh('api','repos/'+repo+'/'+path))
def sha(file):
 with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def public(asset):
 url=asset['browser_download_url']
 expected=asset['digest'].split(':',1)[1]
 for address in (url,url+'?readback='+str(time.time_ns())):
  try:
   with urlopen(Request(address,headers={'User-Agent':'Kaixin-Publication-Readback','Accept':'application/octet-stream'}),timeout=30) as reply:
    raw=reply.read(asset['size']+1)
   assert len(raw)==asset['size'] and hashlib.sha256(raw).hexdigest()==expected, asset['name']
   return raw
  except (OSError,AssertionError):
   continue
 raw=gh('api','-H','Accept: application/octet-stream','repos/'+repo+'/releases/assets/'+str(asset['id']))
 assert len(raw)==asset['size'] and hashlib.sha256(raw).hexdigest()==expected, asset['name']
 return raw

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
   digest=sha(partial)
   assert partial.stat().st_size==asset['size'] and digest==asset['digest'].split(':')[1]
   partial.rename(destination)
   return {'anonymous_download':True,'file':destination.name,'bytes':received,'sha256':digest}
  except Exception as error:
   partial.unlink(missing_ok=True);last=error
 raise last

def verify_update_recovery(report,batch,target):
 tests=report['launcher_tests'];skipped=4 if target=='windows-x64' else 0
 expected={'student-20261117-k12-16':94,'student-20261117-k12-13':94,'student-20261117-k12-12':94,'student-20261117-k12-11':84}.get(batch['tag'],83)
 assert tests['passed'] and {key:tests[key] for key in ['tests','pass','fail','skipped']}=={'tests':expected,'pass':expected-skipped,'fail':0,'skipped':skipped}
 transport=report['network']['interrupted_transport_fixture']
 assert transport['faults']==2 and transport['recoveries']==1 and transport['verified_complete']
 mixed=report['network']['interrupted_direct_denied_api_fixture']
 assert mixed['mixedFaults']==mixed['apiDenials']==mixed['mixedRecoveries']==1 and mixed['verified_complete']
 assert mixed['anonymous_direct_download'] and mixed['injected_api_denial']
 runtime='1.7.1-kaixin-20261114-materials-'+target+'-universal'
 for name,legacy in [('materials_launcher_entry',False),('materials_oldest_launcher_entry',True)]:
  proof=report[name];assert proof['from_runtime']==runtime
  assert proof['actual_download_install_backup_restart']=='passed' and proof['check_again_current']
  assert proof['signed_launcher_restarted'] and proof['old_pid']!=proof['restarted_pid'] and proof['to_launcher']==batch['launcher_build']
  assert all(proof[k] for k in ['chat_preserved','task_preserved','saved_key_preserved'])
  assert proof['selected_base_runtime']==(None if legacy else runtime)
  assert proof['selected_archive']==('kaixin-bridge-'+batch['tag'].removeprefix('student-')+'-'+target+'.tar.gz' if legacy else 'kaixin-core-'+batch['tag'].removeprefix('student-')+'.tar.gz')

def verify_native_entry_artifacts(report, evidence):
 entries={'update_entry':'update-entry','oldest_launcher_entry':'oldest-update-entry','materials_launcher_entry':'materials-update-entry','materials_oldest_launcher_entry':'materials-oldest-update-entry'}
 for key,name in entries.items():
  assert json.loads((evidence/(name+'.json')).read_text())==report[key], 'Native entry receipt differs: '+key
 # Shared UI sidecars are produced by each scenario; the final scenario owns the retained files.
 final=report['materials_oldest_launcher_entry']
 for name,key in {'library-bulk.json':'library_bulk_upload','chat-audio.json':'chat_audio','native-science.json':'science_formulas','quick-preview.json':'quick_preview'}.items():
  assert json.loads((evidence/name).read_text())==final[key], 'Final scenario sidecar differs: '+name
 return {'per_entry_receipts_verified':len(entries),'shared_sidecars_from':'materials_oldest_launcher_entry'}

def verify_complete_native_source(report,completed,source_metadata,stage_sha):
 assert set(completed['entries'])=={'update_entry','oldest_launcher_entry','materials_launcher_entry','materials_oldest_launcher_entry'}
 for key,value in completed['entries'].items():assert report[key]==value, 'Complete source entry changed: '+key
 for key,source in [('native_smoke','smoke'),('fresh_picture_ui','fresh_picture_ui'),('network','network'),('launcher_tests','launcher_tests')]:assert report[key]==completed[source], 'Complete native source changed: '+key
 post=report['native_postflight']
 for key,value in dict(passed=True,source_artifact_sha256=source_metadata['sha256'],signed_stage_sha256=stage_sha,production_launcher_files_verified=24,production_codesign_deep_strict_passed=True,immutable_assets_verified=76,public_installer_files_verified=5,signed_runtime_manifests_verified=45).items():assert post[key]==value, 'Missing actual postcheck: '+key

def stage_run_for_target(batch,target):
 assert target in {'windows-x64','macos-x64','macos-arm64'}
 mapping=batch.get('native_staging_runs')
 if mapping is not None:
  assert set(mapping)=={'windows-x64','macos-x64','macos-arm64'}, 'Missing explicit native stage target'
  row=mapping[target]
 else:row={'run_id':batch['native_staging_run'],'workflow_commit':batch['native_staging_workflow_commit']}
 assert type(row['run_id']) is int and row['run_id']>0 and re.fullmatch(r'[a-f0-9]{40}',row['workflow_commit'])
 return row

def recheck_lock_for_target(batch,target):
 old={'windows-x64':'windows-k12-4-reuse-lock.json','macos-x64':'intel-k12-4-reuse-lock.json','macos-arm64':'arm-k12-4-reuse-lock.json'}[target]
 selected=batch.get('native_rechecks',{}).get(target,{}).get('lock_file',old)
 if batch['tag']=='student-20261117-k12-11':
  assert target=='macos-x64' and selected=='intel-k12-11-reuse-lock.json'
  assert batch['core_commit']=='04fb2adc0c36e964d3a43fc4a4c9c45a877a67c0'
  assert stage_run_for_target(batch,target)=={'run_id':44362174807,'workflow_commit':'a7dadd1f1c9e803ab1aa7a6f3a111a60c63fdd30'}
  return selected
 if batch['tag']=='student-20261117-k12-7':
  assert target=='macos-x64' and selected=='intel-k12-7-reuse-lock.json'
  assert batch['core_commit']=='fbb301fd21cf2169f834e0b548d56d201cc98365'
  assert stage_run_for_target(batch,target)=={'run_id':44230306905,'workflow_commit':'0738e1ac8cfbfddb9123d097bc90598abf5827fb'}
  return selected
 if batch['tag']=='student-20261117-k12-6':
  assert target=='windows-x64' and selected=='windows-k12-6-reuse-lock.json'
  assert batch['core_commit']=='4a61cd7edcd27c6bc6f6bb9305a5a4f3af8851e2'
  staged=batch.get('native_staging_runs',{}).get(target) if batch.get('native_staging_runs') else {'run_id':batch['native_staging_run'],'workflow_commit':batch['native_staging_workflow_commit']}
  assert staged=={'run_id':44202602948,'workflow_commit':'a61f75e11a4d8a7f99cda009e3eb76e6654eb5a0'}
  return selected
 assert selected==old or batch['tag']=='student-20261117-k12-5' and target=='macos-x64' and selected=='intel-k12-5-reuse-lock.json'
 return selected

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
 resumed=None
 complete_source=None
 assert report['release']==batch['tag'] and report['core_commit']==batch['core_commit']
 staged=stage_run_for_target(batch,target)
 if batch['native_runs'][target]['run_id']==staged['run_id']:assert batch['native_runs'][target]['workflow_commit']==staged['workflow_commit']
 if batch['native_runs'][target]['run_id'] != staged['run_id'] and batch['tag'] in {'student-20261117-k12-13','student-20261117-k12-16'}:
  from ci_repackage import validate_reuse_lock
  lock_name='fresh-install-lock.json' if batch['tag']=='student-20261117-k12-16' else 'k12-13-native-recheck.json'
  lock_raw=(root/lock_name).read_bytes();lock=json.loads(lock_raw)
  accepted=batch['native_rechecks'][target];p=report['provenance']
  assert accepted['lock_file']==p['reuse_lock_file']==lock_name
  assert hashlib.sha256(lock_raw).hexdigest()==accepted['lock_sha256']==p['reuse_lock_sha256']
  run=batch['native_runs'][target]
  assert p['verification_run']==run['run_id']==accepted['run_id']
  assert p['workflow_commit']==run['workflow_commit']==accepted['workflow_commit']
  assert p['original_stage_run']==staged['run_id'] and p['original_stage_workflow_commit']==staged['workflow_commit']
  assert p['original_native_job']==lock['reuse_existing_native']['original_jobs'][target]
  assert p['frozen_stage_sha256']==batch['signed_stage_sha256']==lock['reuse_existing_native']['frozen_stage_sha256']
  assert not any(p[key] for key in ['bridge_rebuilt','installers_repackaged','existing_assets_overwritten'])
  assert all(p[key] for key in ['fresh_smoke_rerun','proxy_smoke_rerun','materials_both_variants_rerun','fresh_picture_ui_rerun'])
  native_batch=json.loads((root/'attachment-batch.json').read_text())
  validate_reuse_lock(lock,native_batch,candidate,target)
  if 'intel_scene_lock_sha256' in accepted:
   assert batch['tag']=='student-20261117-k12-16' and target=='macos-x64'
   assert p['oldest_and_current_ipc_rerun'] is False
   from runpy import run_path
   helpers=run_path(str(root/'ci-intel-k12-16-finalize.py'))
   scene_raw=(root/helpers['SCENE_LOCK']).read_bytes()
   assert hashlib.sha256(scene_raw).hexdigest()==accepted['intel_scene_lock_sha256']==p['intel_scene_lock_sha256']
   scene_lock=json.loads(scene_raw)
   assert scene_lock['tag']==batch['tag'] and scene_lock['source_commit']==batch['core_commit']
   assert scene_lock['native_lock_sha256']==p['reuse_lock_sha256']
   assert scene_lock['sources']==p['intel_scene_sources'] and set(scene_lock['sources'])==set(helpers['SCENES'])
   def read_intel_scene(item):
    scene,source=item
    _,field,entry=helpers['read_scene'](scene,source,p['reuse_lock_sha256'],native_batch)
    assert json.loads(entry)==report[field], field
   with ThreadPoolExecutor(max_workers=4) as pool:
    for _ in pool.map(read_intel_scene,scene_lock['sources'].items()):pass
  else:
   assert p['oldest_and_current_ipc_rerun'] is True
  assert sorted((r['file'],r['bytes'],r['sha256']) for r in report['full_files'])==sorted(
   (r['name'],r['bytes'],r['sha256']) for r in lock['targets'][target]['files'])
 elif batch['native_runs'][target]['run_id'] != staged['run_id']:
  assert target in {'macos-arm64','macos-x64','windows-x64'}
  lock_name=recheck_lock_for_target(batch,target)
  lock_raw=(root/lock_name).read_bytes();lock=json.loads(lock_raw)
  if batch['tag']=='student-20261117-k12-7':
   from batch7_recheck import validate_intel7_lock
   validate_intel7_lock(lock,(root/'attachment-final-manifests.json').read_bytes())
  if batch['tag']=='student-20261117-k12-6':
   import importlib.util
   spec=importlib.util.spec_from_file_location('frozen_windows6_recheck',root/'ci-mac-reuse.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
   guard.validate_windows6_lock(lock,(root/'attachment-final-manifests.json').read_bytes())
  accepted=batch['native_rechecks'][target];p=report['provenance']
  assert hashlib.sha256(lock_raw).hexdigest()==accepted['lock_sha256']==p['reuse_lock_sha256']
  assert p['reuse_lock_file']==lock_name
  assert accepted['run_id']==batch['native_runs'][target]['run_id']==p['verification_run']
  assert accepted['workflow_commit']==batch['native_runs'][target]['workflow_commit']==p['workflow_commit']
  assert lock['original_native_run']==staged['run_id']==p['original_stage_run']==p['original_failed_run']
  assert lock['original_native_workflow_commit']==staged['workflow_commit']==p['original_stage_workflow_commit']
  assert lock['original_failed_job']==p['original_failed_job']
  assert lock['source_commit']==batch['core_commit'] and lock['candidate_tag']==batch['tag']
  assert lock['frozen_stage']['sha256']==batch['signed_stage_sha256']==p['frozen_stage_sha256']
  assert all(p[k] is False for k in ['bridge_rebuilt','installers_repackaged','existing_assets_overwritten'])
  intel11=batch['tag']=='student-20261117-k12-11'
  if intel11:
   assert hashlib.sha256(lock_raw).hexdigest()=='82713206090f52bfcd5d14cbc67067b0dc76d6a9b7c634399e1843a2113fb6e3'
   assert sha(root/'k12_11_intel_evidence.py')==lock['recipe_inputs_sha256']['k12_11_intel_evidence.py']
   assert p['materials_oldest_variant_rerun'] is True and p['materials_both_variants_rerun'] is False
   assert p['existing_asset_metadata_before_after_unchanged'] is True and lock['execution_frozen'] is True
  if accepted.get('complete_native_execution'):
   from intel7_complete_evidence import COMPLETE_SOURCE,fetch_complete_archive,validate_finalized_provenance
   assert batch['tag']=='student-20261117-k12-7' and target=='macos-x64'
   assert accepted['complete_native_execution']==COMPLETE_SOURCE and accepted['finalization_lock_file']=='intel7-finalization-lock.json'
   final_raw=(root/accepted['finalization_lock_file']).read_bytes();final=json.loads(final_raw)
   assert hashlib.sha256(final_raw).hexdigest()==accepted['finalization_lock_sha256']==p['finalization_lock_sha256']
   assert final['frozen'] is True and final['candidate_tag']==batch['tag'] and final['source_commit']==batch['core_commit']
   assert final['source_lock_file']==lock_name and final['source_lock_sha256']==hashlib.sha256(lock_raw).hexdigest()
   validate_finalized_provenance(lock,p,final)
   complete_source=fetch_complete_archive(lock,api,gh)
   verify_complete_native_source(report,complete_source,COMPLETE_SOURCE,batch['signed_stage_sha256'])
  else:
   assert 'complete_native_execution' not in p
   assert p['fresh_smoke_rerun'] is True and p['proxy_smoke_rerun'] is True
   assert p['materials_both_variants_rerun'] is (not intel11)
  if 'resume_artifact' in lock:
   if intel11:
    from k12_11_intel_evidence import fetch_partial_archive
   else:
    from partial_native_evidence import fetch_partial_archive
   resumed=fetch_partial_archive(lock,api,gh)
   assert p['oldest_and_current_ipc_rerun'] is False and p['partial_artifact_source_verified'] is True
   assert p['partial_artifact_sha256']==lock['resume_artifact']['sha256'] and p['completed_entry_receipts_reused']==lock['reused_complete_entries']
   for key,value in resumed['entries'].items():assert report[key]==value, 'Completed entry differs from its original source artifact'
   if 'reused_fresh_picture_ui' in lock:
    assert p['fresh_picture_ui_rerun'] is False and p['completed_fresh_picture_ui_reused']==lock['reused_fresh_picture_ui']
    assert report['fresh_picture_ui']==resumed['fresh_picture_ui'], 'Fresh UI differs from its exact completed source receipt'
   else:assert p['fresh_picture_ui_rerun'] is True
  elif complete_source is None:assert p['oldest_and_current_ipc_rerun'] is True
  if 'resume_artifact' not in lock and complete_source is None:assert p['fresh_picture_ui_rerun'] is True
  assert sorted((r['file'],r['bytes'],r['sha256']) for r in report['full_files'])==sorted((r['name'],r['bytes'],r['sha256']) for r in lock['candidate_files'])
 assert report['launcher_build']==batch['launcher_build'] and report['shell_files']==batch['shell_files']
 verify_update_recovery(report,batch,target)
 assert report['native_install']=='passed' and not report['real_keys_used'] and not report['real_learning_records_modified']
 assert report['network']['proxy_connections']>0 and report['network']['api_fallback_download']=='passed'
 smoke=report['native_smoke'];assert smoke['current_core_included'] and smoke['pdf']['pdf_files']==136
 validate_native_page_api(smoke['k12_api'],batch['native_pages'])
 assert smoke['k12_api']['prepared_picture_bindings']==batch['picture_count']
 assert smoke['k12_api']['prepared_picture_manifest_sha256']==batch['picture_manifest_sha256']
 fresh=report['fresh_picture_ui'];assert fresh['passed'] and fresh['production_launcher_source_byte_identical'] and fresh['qa_code_only_in_disposable_copy']
 if batch['tag']=='student-20261117-k12-16':
  citation=fresh['desktop_citation']
  assert citation['passed'] and citation['reopened_history'] and citation['history']['noFalseOriginal'] and citation['history']['noFooter'] and citation['history']['selectionPreserved']
  assert citation['pdf']=={'realViewer':True,'textLayer':True,'initialPage':3} and re.fullmatch(r'[a-f0-9]{64}',citation['raw_pdf_sha256'])
 for ui in [fresh['k12_library'],*[report[key]['k12_library'] for key in ['update_entry','oldest_launcher_entry','materials_launcher_entry','materials_oldest_launcher_entry']]]:
  validate_native_page_views(ui,batch['native_pages']['ui_fixture'])
  assert ui['passed'] and ui['actualNativeRenderer'] and len(ui['views'])==4
  for view in ui['views']:
   assert all(view['preparedPicture'][key] for key in ['native_http_image_sha_verified','body_dom_before_image_response','second_history_restore'])
 assert smoke['k12_api']['passed'] and smoke['k12_api']['model_calls']==0 and smoke['k12_api']['teacher_fields_absent']
 assert all(smoke['k12_api'][key] for key in ['fts_search_passed','fts_empty_query_passed','item_quality_metadata_matched'])
 assert smoke['k12_api']['runtime_isolated_count']==batch['runtime_exclusion_count'] and smoke['k12_api']['physical_readable_count']-smoke['k12_api']['effective_readable_count']==batch['runtime_exclusion_count']
 assert smoke['k12_api']['runtime_exclusion_kinds']==batch['runtime_exclusion_kinds'] and smoke['k12_api']['runtime_exclusion_ledger_sha256']==batch['runtime_exclusion_ledger_sha256']
 for field in ['update_entry','oldest_launcher_entry','materials_launcher_entry','materials_oldest_launcher_entry']:
  k12=report[field]['k12_library'];assert k12['passed'] and k12['actualNativeRenderer'] and k12['model_calls']==0 and len(k12['views'])==4
  assert k12['bank_revision']==smoke['k12_api']['bank_revision']
 study=smoke['study_reports'];assert study['passed'] and len(study['cases'])==9 and study['real_model_calls']==0
 assert all(all(row[k] for k in ['generation_failure_rejected','audit_failure_rejected','legacy_fallback_hidden_and_export_blocked','reviewed_fixture_available_and_word_exported','chat_and_reading_records_preserved']) for row in study['cases'])
 preview=report['update_entry']['quick_preview'];assert preview['passed'] and len(preview['views'])==4 and preview['conversationSwitchCleared'] and all(v['cardWithinMessagePane'] for v in preview['views'])
 assert len(smoke['local_spoken_stt'])==2 and all(r['spoken_audio_decoded'] for r in smoke['local_spoken_stt'])
 native_evidence=work/('evidence-'+target)
 gh('run','download',batch['native_runs'][target]['run_id'],'--name','attachments-'+target,'--dir',native_evidence)
 assert json.loads((native_evidence/'verified.json').read_text())==report
 if complete_source:
  for name,raw in complete_source['files'].items():assert (native_evidence/name).read_bytes()==raw, 'Original complete native evidence changed: '+name
 if resumed:
  for name,raw in resumed['files'].items():
   copied='completed-source-reuse-lock.json' if name=='reuse-lock.json' else name
   assert (native_evidence/copied).read_bytes()==raw, 'Reused native evidence was modified: '+name
 report['artifact_scene_binding']=verify_native_entry_artifacts(report,native_evidence)
 attachment=json.loads((native_evidence/'attachments.json').read_text())
 from native8_health_publication import validate_health_publication
 validate_health_publication(batch,target,report,attachment)
 for size in ['390x844','1366x900']:
  screenshot=native_evidence/('quick-preview-'+size+'.png');raw=screenshot.read_bytes();assert len(raw)>1000 and raw.startswith(b'\x89PNG\r\n\x1a\n')
  public_screenshot=work/('quick-preview-'+target+'-'+size+'.png');public_screenshot.write_bytes(raw);gh('release','upload',batch['tag'],public_screenshot,'--clobber')
 assert all(attachment[k] for k in ['raw_originals_verified','temporary_excluded_from_library','concurrent_library_uploads_saved','scanned_pdf_retrievable'])
 assert attachment['short_pdf_pages']==2 and attachment['interactive_page_ready_while_indexing_seconds']<20
 report['attachment_uploads']=attachment
 update=report['update_entry'];assert update['actual_download_install_backup_restart']=='passed' and update['check_again_current']
 legacy=report['oldest_launcher_entry'];assert legacy['actual_download_install_backup_restart']=='passed' and legacy['signed_launcher_restarted'] and legacy['check_again_current']
 assert legacy['old_pid']!=legacy['restarted_pid'] and legacy['to_launcher']==batch['launcher_build']
 assert update['download_progress_visible'] and update['downloaded_bytes_visible'] and update['to_launcher']==batch['launcher_build']
 bulk=update['library_bulk_upload'];assert bulk['saved_files']==21 and all(bulk[k] for k in ['multiple','library_retention','originals_byte_identical','original_preview_opened','held_real_chunk','chat_and_settings_navigation','appended_while_active','completed_in_chat','document_not_reloaded','draft_preserved','picker_reference_byte_identical','no_duplicate_upload_or_new_chat','html_safe_preview','source_toggle','native_math_display'])
 audio=update['chat_audio'];assert audio['passed'] and len(audio['productionCards'])==2
 assert audio['selection']['chatRequests']==0 and audio['selection']['errorShown']
 assert all(card['sha256']==audio['productionCards'][0]['sha256'] for card in audio['productionCards'])
 science=update['science_formulas'];assert science['passed'] and len(science['views'])==16 and len(science['originalEdits'])>=18 and science['cleanup']['debuggerDetached'] and science['cleanup']['deviceMetricsCleared']
 assert bulk['device_speech']['diagnosticOnly'] and 'nativeEnded' in bulk['device_speech']['diagnostic']
 assert all(update[k] for k in ['chat_preserved','task_preserved','saved_key_preserved'])
 validate_installer_files(report['full_files'],target,batch['tag'])
 for row in report['full_files']:
  actual=assets[row['file']];assert actual['digest']=='sha256:'+row['sha256'] and actual['size']==row['bytes']
 full_files+=report['full_files'];proofs[target]=report
assert 13 <= len(full_files) <= 15

cos_native_proofs={}
if batch['tag'] in {'student-20261117-k12-12','student-20261117-k12-13','student-20261117-k12-16'}:
 mirror=release_config['update_mirror_base']
 assert mirror=='https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
 cos=json.loads((root/'COS-BATCH-READBACK.json').read_text())
 assert cos['tag']==batch['tag'] and cos['source_commit']==batch['core_commit'] and cos['cos_mirror']==mirror
 assert {row['name'] for row in cos['manifests']}==set(batch['manifests'])
 def verify_cos_manifest(row):
  raw=(json.dumps(batch['manifests'][row['name']],indent=2)+'\n').encode()
  assert row['bytes']==len(raw) and row['sha256']==hashlib.sha256(raw).hexdigest()
  with urlopen(Request(mirror+row['name'],headers={'Cache-Control':'no-cache'}),timeout=30) as reply:
   assert reply.status==200 and reply.geturl()==mirror+row['name'] and reply.read(len(raw)+1)==raw
 with ThreadPoolExecutor(max_workers=6) as pool:
  for _ in pool.map(verify_cos_manifest,cos['manifests']):pass
 assert {row['name'] for row in cos['archives']}==set(batch['archives'])
 for row in cos['archives']:
  expected=batch['archives'][row['name']]
  assert row['sha256']==expected['sha256'] and row['bytes']==expected['bytes'] and row['complete_sha256_verified']
  with urlopen(Request(mirror+row['name'],headers={'Range':'bytes=0-0','Accept-Encoding':'identity'}),timeout=30) as reply:
   assert reply.status==206 and reply.geturl()==mirror+row['name'] and reply.headers['Content-Range']=='bytes 0-0/'+str(row['bytes'])
   assert reply.headers['ETag']==row['etag'] and len(reply.read(2))==1
 if batch['tag']=='student-20261117-k12-12':
  from cos_native_publication import validate_cos_native
  pinned=batch['cos_native_run']
  route_run=api('actions/runs/'+str(pinned['run_id']))
  assert route_run['head_sha']==pinned['workflow_commit'] and route_run['conclusion']=='success'
  assert route_run['head_branch']=='codex/k12-cos-native-20261117-12'
  route_jobs=api('actions/runs/'+str(pinned['run_id'])+'/jobs')['jobs']
  assert len(route_jobs)==len(targets)==3 and all(job['conclusion']=='success' for job in route_jobs)
  for target in targets:
   assert sum(job['name'].startswith('cos-native ('+target+',') for job in route_jobs)==1
   path=work/('cos-native-'+target)
   gh('run','download',pinned['run_id'],'--name','cos-native-'+target,'--dir',path)
   cos_native_proofs[target]=validate_cos_native(path,batch,target,proofs[target]['full_files'],cos)
 else:
  raw=(root/'LOCAL-COS-UPDATE.json').read_bytes()
  assert hashlib.sha256(raw).hexdigest()==batch['local_cos_update_sha256']
  observed=json.loads(raw)
  network=observed['network']
  assert observed['source_commit']==batch['core_commit'] and observed['transaction_phase']=='complete'
  assert all(observed[k] for k in ['application_ipc_update','profile_isolated','check_again_current'])
  assert observed['physical_interface']=='en7' and observed['tls_passthrough'] is True
  assert observed['staged_compatibility_manifest'] is False
  selected=next(x for x in batch['manifests'].values() if x['runtimeId']==observed['to'])
  prior_runtime_part = '-k12-13-' if batch['tag']=='student-20261117-k12-16' else '-k12-12-'
  assert selected['platform']=='darwin' and selected['arch']=='x64' and prior_runtime_part in observed['from']
  assert network['host']=='kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com'
  assert network['route']=='cos' and network['status']==200 and network['cache'] is False
  assert network['asset']==selected['archive'] and network['sha256']==selected['sha256']
  assert network['bytes']==batch['archives'][selected['archive']]['bytes']
  slider=observed['offline_slider']
  assert slider['canvas'] and slider['first']==2 and slider['second']==4

stable_assets={a['name']:a for a in api('releases/tags/core-updates')['assets']}
for name,expected in batch['expected_previous'].items():
 actual=stable_assets[name];assert actual['digest']=='sha256:'+expected,'Live feed changed: '+name
 raw=public(actual);(previous/name).write_bytes(raw)
 retained=work/('before-attachments-'+name);retained.write_bytes(raw);gh('release','upload',batch['tag'],retained,'--clobber')

# Download and hash the exact core and three native archives before switching any default.
def verify_public_archive(entry):
 name,row=entry
 actual=assets[name];assert actual['digest']=='sha256:'+row['sha256'] and actual['size']==row['bytes']
 return download_public_archive(actual,work/name)
with ThreadPoolExecutor(max_workers=4) as pool:
 anonymous_archives=list(pool.map(verify_public_archive,batch['archives'].items()))
assert len(anonymous_archives)==len(batch['archives'])==4
for name,manifest in batch['manifests'].items():(work/name).write_text(json.dumps(manifest,indent=2)+'\n')
subprocess.run(['python','bootstrap_source.py','--with-updates'],check=True)
subprocess.run(['node','student-source/apps/desktop/scripts/check-update-batch.mjs',str(work)],check=True)

staged=[]
for name,row in batch['archives'].items():
 if name in stable_assets:assert stable_assets[name]['digest']=='sha256:'+row['sha256']
 else:staged.append(work/name)
for name in batch['manifests']:
 if name not in batch['expected_previous']:
  if name in stable_assets:assert public(stable_assets[name])==(work/name).read_bytes()
  else:staged.append(work/name)
if staged:gh('release','upload','core-updates',*staged)
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
 return {**batch,'published_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'release_repository_commit':os.environ['GITHUB_SHA'],'release_id':latest['id'],'release_url':latest['html_url'],'full_files':full_files,'proofs':proofs,'cos_native_proofs':cos_native_proofs,'stable_manifests_read_back':list(batch['manifests']),'anonymous_archives':anonymous_archives,'physical_user_devices_tested':False,'private_key_uploaded':False}
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
