"""One explicitly accepted original ARM8 health sample, never a wider health limit."""
import argparse,copy,hashlib,json,platform,sys,zipfile
from pathlib import Path
if sys.flags.optimize:raise RuntimeError('Native8 acceptance QA assertions must remain enabled')
TARGET='macos-arm64';TAG='student-20261117-k12-8'
SOURCE='9102686f43bff7162d3724abb86957ec6d644294'
CORE='ad637c748061b639e9c984437e3439a3d82b8e0ecb0d86ac33ad002e11443728'
RUN=44285382021;JOB=134736575809;HEAD='daaa73733855075857e89e833712d5568a459ddb'
ACCEPTANCE_SHA='5b8c3e0b6195b7c93e28f6e221431f2eb21995971c370c48bb2c7e6fe889b2e4'
ARTIFACT_SHA='6e662271d641b1766a00812b279490977a7a628e01bc134b7cad7231aa5acb39'
CANDIDATE_SHA='c5c0dddc9fd472c6c7a3287ca3fc64d33cf39ebb34a32921d9ba84ed2623c82a'
ORIGINAL_TEST_SHA='aaafccb5bf56c1f70956a923556f1c68bf698cf376848d58ae1d732f4258b154'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text())

def validate_original(acceptance,artifact,target,batch,manifest):
 assert target==TARGET and batch['tag']==TAG and batch['core_commit']==SOURCE
 assert batch['core_asset']['digest']=='sha256:'+CORE
 assert manifest==batch['manifests'][TARGET] and manifest['commit']==SOURCE and manifest['sha256']==CORE
 assert sha(acceptance)==ACCEPTANCE_SHA and sha(artifact)==ARTIFACT_SHA
 row=load(acceptance)
 assert (row['run_id'],row['job_id'],row['workflow_commit'],row['source_commit'],row['core_sha256'])==(RUN,JOB,HEAD,SOURCE,CORE)
 assert row['job_conclusion']=='failure' and row['remaining_native_checks_completed'] is False and row['publication_allowed_by_this_receipt_alone'] is False
 assert row['user_acceptance']['accepted_only_observed_health_sample'] is True and row['user_acceptance']['new_model_wait_limit'] is False
 assert row['reported_metrics']['health_max_seconds']==5.248
 with zipfile.ZipFile(artifact) as zipped:
  assert zipped.testzip() is None
  assert {v.filename for v in zipped.infolist()}=={v['path'] for v in row['artifact']['members']}
  for member in row['artifact']['members']:
   raw=zipped.read(member['path']);assert len(raw)==member['bytes'] and hashlib.sha256(raw).hexdigest()==member['sha256']
 report=row['reported_metrics']
 assert all(report[k] is True for k in ['raw_originals_verified','temporary_excluded_from_library','concurrent_library_uploads_saved','scanned_pdf_retrievable'])
 assert report['short_pdf_pages']==2 and report['sources']==3 and report['interactive_page_ready_while_indexing_seconds']==3.869
 assert report['real_api_key_used'] is False and report['cloud_models_used'] is False
 stamp={'kind':'explicit_user_acceptance_exact_original_ARM8_sample','target':TARGET,'source_commit':SOURCE,'core_sha256':CORE,'original_run_id':RUN,'original_job_id':JOB,'original_workflow_commit':HEAD,'acceptance_receipt_sha256':ACCEPTANCE_SHA,'original_artifact_sha256':ARTIFACT_SHA,'original_default_health_limit_seconds':5,'original_health_max_seconds':5.248,'original_health_gate_passed':False,'user_accepted_original_sample':True,'original_attachment_functional_scenario_reused':True,'attachment_scenario_rerun_in_new_profile':False,'remaining_checks_completed_by_this_receipt':False,'model_wait_exception':False}
 return {**copy.deepcopy(report),'explicit_health_acceptance':stamp}

def validate_embedded(stamp,target,batch):
 if stamp is None:return
 assert target==TARGET and batch['tag']==TAG and batch['core_commit']==SOURCE and batch['core_asset']['digest']=='sha256:'+CORE
 assert stamp=={'kind':'explicit_user_acceptance_exact_original_ARM8_sample','target':TARGET,'source_commit':SOURCE,'core_sha256':CORE,'original_run_id':RUN,'original_job_id':JOB,'original_workflow_commit':HEAD,'acceptance_receipt_sha256':ACCEPTANCE_SHA,'original_artifact_sha256':ARTIFACT_SHA,'original_default_health_limit_seconds':5,'original_health_max_seconds':5.248,'original_health_gate_passed':False,'user_accepted_original_sample':True,'original_attachment_functional_scenario_reused':True,'attachment_scenario_rerun_in_new_profile':False,'remaining_checks_completed_by_this_receipt':False,'model_wait_exception':False}

def validate_reuse(lock,batch,release,target):
 assert lock.get('execution_frozen') is True and target==TARGET and set(lock['targets'])=={TARGET}
 assert lock['tag']==batch['tag']==release['tag_name']==TAG and lock['release_id']==release['id']==449810016
 assert lock['core_commit']==batch['core_commit']==SOURCE and lock['core_sha256']==CORE==batch['core_asset']['digest'][7:]
 assert release['prerelease'] is True and release['draft'] is False
 assert sha('native8-arm-candidate-files.json')==CANDIDATE_SHA and sha('native8-arm-health-acceptance.json')==ACCEPTANCE_SHA and sha('native8-arm-health-original.zip')==ARTIFACT_SHA
 assert lock['reuse_existing_native']['original_installer_assets'][TARGET]==load('native8-arm-candidate-files.json')['candidate_files']
 reuse=lock['reuse_existing_native'];assert reuse['kind']=='ARM8_exact_accepted_original_health_continuation'
 assert reuse['baseline_latest_id']==449471487 and reuse['original_native_run']==RUN and reuse['original_failed_job']==JOB and reuse['original_native_workflow_commit']==HEAD
 assert reuse['health_acceptance_sha256']==ACCEPTANCE_SHA and reuse['candidate_metadata_sha256']==CANDIDATE_SHA
 assert reuse['prior_manifests'][TARGET]['commit']=='fbb301fd21cf2169f834e0b548d56d201cc98365'
 assert reuse['prior_core_asset']['sha256']=='4c37b944c868861ebaee446d86c94d7d045c3d81224dcee5eeb3b8876deff892'
 original=reuse['original_installer_assets'][TARGET];assert len(original)==4 and len({v['id'] for v in original})==4
 expected={v['name']:v for v in lock['targets'][TARGET]['files']};assert set(expected)=={v['name'] for v in original}
 assets={v['name']:v for v in release['assets']}
 for row in original:
  assert row['url']=='https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/'+TAG+'/'+row['name']
  actual=assets[row['name']];assert (actual['id'],actual['size'],actual['digest'])==(row['id'],row['bytes'],'sha256:'+row['sha256'])
  assert expected[row['name']]=={k:row[k] for k in ['name','bytes','sha256']}
 assert not any(name in assets for name in ['kaixin-bridge-20261117-k12-8-'+TARGET+'.tar.gz','attachment-stage-'+TARGET+'.json','verification-'+TARGET+'.json']), 'A prior stage needs an explicit frozen-stage continuation; never overwrite it'
 from ci_repackage import validate_installer_files
 validate_installer_files([{'file':v['name'],'bytes':v['bytes']} for v in original],target,TAG)

def verify_remote_identity(run,job,artifact):
 assert run['id']==RUN and run['head_sha']==HEAD
 assert job['id']==JOB and job['run_id']==RUN and job['head_sha']==HEAD and job['status']=='completed' and job['conclusion']=='failure'
 assert job['name'].startswith('native (macos-arm64,')
 assert artifact['id']==14419846998 and artifact['size_in_bytes']==10539 and artifact['digest']=='sha256:'+ARTIFACT_SHA

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--acceptance',required=True);ap.add_argument('--artifact',required=True);ap.add_argument('--target',required=True);ap.add_argument('--batch',required=True);ap.add_argument('--manifest',required=True);ap.add_argument('--out',required=True);args=ap.parse_args()
 assert sys.platform=='darwin' and platform.machine()=='arm64'
 assert sha('ci-attachment-native.py')==ORIGINAL_TEST_SHA, 'Original strict5-second test must stay unchanged'
 result=validate_original(args.acceptance,args.artifact,args.target,load(args.batch),load(args.manifest))
 output=Path(args.out);assert not output.exists(),'Do not replace an earlier attachment receipt';output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
