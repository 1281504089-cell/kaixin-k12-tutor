"""Verify one exact completed Intel7 native execution before independent final postchecks."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import stat
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
REPO='1281504089-cell/kaixin-k12-tutor'
COMPLETE_SOURCE={'id':14407657263,'bytes':13410126,'sha256':'dc967707d98461e1840c80447904446067c4125d7dcabdf95994b61155cc388b','run_id':44248561243,'workflow_commit':'7a7c7e0d26f1796f35f606afe42eaa8c31599db6','job_id':134613361890,'source_lock_sha256':'7116479c7e4b3ceba3e5222258f8e2ff91eaf6f4f8dac990cd127e26174bfe97'}
SOURCE_LOCK_CANONICAL_SHA256='3e6478e6efeb8286aee44098f128fbbd57dfe21650d48166ac41e1b84aa39f0c'
MEMBERS_SHA256='38cfc01e233c3b0b56249e5c2fd733100be86d1c7dd2b2b0415e7517be49baa5'
ENTRY_FILES={'update_entry':'update-entry.json','oldest_launcher_entry':'oldest-update-entry.json','materials_launcher_entry':'materials-update-entry.json','materials_oldest_launcher_entry':'materials-oldest-update-entry.json'}
RERUN_FLAGS=('fresh_smoke_rerun','proxy_smoke_rerun','oldest_and_current_ipc_rerun','fresh_picture_ui_rerun','materials_both_variants_rerun')


def validate_source_lock(source_lock):
    if sys.flags.optimize:raise RuntimeError('Intel7 completion assertions must remain enabled')
    assert hashlib.sha256(json.dumps(source_lock,sort_keys=True,separators=(',',':')).encode()).hexdigest()==SOURCE_LOCK_CANONICAL_SHA256, 'Original Intel7 source lock changed'
    assert source_lock['target']=='macos-x64' and source_lock['candidate_tag']=='student-20261117-k12-7'
    assert source_lock['source_commit']=='fbb301fd21cf2169f834e0b548d56d201cc98365' and source_lock['launcher_build']=='20261118-updater-4'
    return source_lock


def _member_manifest():
    raw=(ROOT/'intel7-complete-members.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==MEMBERS_SHA256, 'Source-member manifest changed'
    value=json.loads(raw);assert len(value)==152
    return value


def _validate_member_bytes(files):
    expected=_member_manifest();assert set(files)==set(expected), 'Complete source must contain all 152 exact members'
    for name,row in expected.items():
        raw=files[name]
        assert type(raw) is bytes and len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'], 'Source member changed: '+name


def _extract_archive(raw):
    files={}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members=archive.infolist()
            assert len(members)==152 and len({item.filename for item in members})==152, 'Wrong or duplicate source members'
            assert sum(item.file_size for item in members)<=64*1024**2
            for item in members:
                name=item.filename
                assert name and len(name)<=240 and '/' not in name and '\\' not in name and not any(ord(ch)<32 or ord(ch)==127 for ch in name), 'Unsafe source path'
                assert not item.is_dir() and not stat.S_ISLNK(item.external_attr>>16) and not item.flag_bits&1, 'Source links/directories/encryption are not allowed'
                assert 0<item.file_size<16*1024**2 and item.compress_type in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED}
                files[name]=archive.read(item)  # Reading each member verifies its CRC.
    except (zipfile.BadZipFile,RuntimeError,ValueError) as error:
        raise AssertionError('Invalid source ZIP') from error
    return files


def validate_complete_records(source_lock, files):
    validate_source_lock(source_lock);_validate_member_bytes(files)
    def data(name):return json.loads(files[name])
    assert hashlib.sha256(files['reuse-lock.json']).hexdigest()==COMPLETE_SOURCE['source_lock_sha256'] and data('reuse-lock.json')==source_lock
    marker=data('native-reverify-run-macos-x64-44248561243.json')
    assert marker['target']=='macos-x64' and marker['run_id']==COMPLETE_SOURCE['run_id'] and marker['workflow_commit']==COMPLETE_SOURCE['workflow_commit']
    assert marker['source_commit']==source_lock['source_commit'] and marker['reuse_lock_sha256']==COMPLETE_SOURCE['source_lock_sha256'] and marker['frozen_stage_sha256']==source_lock['frozen_stage']['sha256']
    assert marker['original_failed_run']==source_lock['original_native_run'] and marker['original_failed_job']==source_lock['original_failed_job']
    entries={key:data(name) for key,name in ENTRY_FILES.items()}
    smoke=data('app.json');fresh=data('picture-fresh-ui.json');network=data('network.json');tests=data('launcher-tests.json');downloads=data('downloads.json')
    assert smoke['native_platform']=='darwin' and smoke['native_arch']=='x64' and smoke['current_core_included'] is True and smoke['fresh_profile'] is True
    assert smoke['core_commit']==source_lock['source_commit'] and smoke['runtime_id']==source_lock['included_manifest']['runtimeId']
    assert smoke['textbooks']==136 and smoke['textbook_summary_count']==12101 and smoke['pdf']['pdf_files']==136 and smoke['real_keys_used'] is False
    assert fresh['active_runtime_id']==source_lock['included_manifest']['runtimeId'] and fresh['model_calls']==0 and fresh['formal_data_used'] is False
    assert tests=={'passed':True,'native_target':'macos-x64','tests':83,'pass':83,'fail':0,'skipped':0}
    tap=files['launcher-tests.tap'].decode('utf-8')
    for field,count in [('tests',83),('pass',83),('fail',0),('skipped',0)]:assert re.search(r'^# '+field+' '+str(count)+r'$',tap,re.M), 'Native test count changed: '+field
    expected={row['name']:row for row in source_lock['candidate_files']}
    assert len(downloads)==5 and len({row['name'] for row in downloads})==5 and {row['name'] for row in downloads}==set(expected)
    for row in downloads:
        assert all(row.get(key)==value for key,value in expected[row['name']].items()) and row['anonymous_download'] is True and row['sha256_verified'] is True
    before=data('immutable-assets-before.json')
    frozen=sorted([{'name':row['name'],'id':row['id'],'size':row['bytes'],'digest':'sha256:'+row['sha256']} for row in source_lock['immutable_existing_assets']],key=lambda row:row['name'])
    assert len(before)==76 and sorted(before,key=lambda row:row['name'])==frozen
    assert network['native_platform']=='darwin' and network['native_arch']=='x64' and network['proxy_used'] is True and network['signature_verified'] is True and network['archive_checksum_verified'] is True
    assert network['api_fallback_download']=='passed' and network['direct_fetch_failed'] is True
    transport=network['interrupted_transport_fixture'];assert transport['faults']==2 and transport['recoveries']==1 and transport['verified_complete'] is True
    mixed=network['interrupted_direct_denied_api_fixture'];assert mixed['mixedFaults']==mixed['apiDenials']==mixed['mixedRecoveries']==1 and mixed['verified_complete'] is True and mixed['anonymous_direct_download'] is True
    spec=importlib.util.spec_from_file_location('intel7_completed_route_validator',ROOT/'ci-mac-reuse.py')
    reuse=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse)
    reuse.validate_native_proofs(smoke,fresh,entries['update_entry'],entries['oldest_launcher_entry'],source_lock,entries['materials_launcher_entry'],entries['materials_oldest_launcher_entry'])
    current_runtime=source_lock['included_manifest']['runtimeId'];full_runtime='1.7.1-kaixin-20261117-k12-7-macos-x64-universal';materials_runtime='1.7.1-kaixin-20261114-materials-macos-x64-universal'
    scopes={
        'update_entry':(source_lock['prior_manifest']['runtimeId'],current_runtime,source_lock['core_asset']['name'],source_lock['included_manifest']['baseRuntimeId']),
        'oldest_launcher_entry':(source_lock['prior_manifest']['runtimeId'],full_runtime,source_lock['bridge']['name'],None),
        'materials_launcher_entry':(materials_runtime,'1.7.1-kaixin-20261117-k12-7-macos-x64-base-c41831772671',source_lock['core_asset']['name'],materials_runtime),
        'materials_oldest_launcher_entry':(materials_runtime,full_runtime,source_lock['bridge']['name'],None),
    }
    for key,entry in entries.items():
        assert (entry['from_runtime'],entry['to_runtime'],entry['selected_archive'],entry['selected_base_runtime'])==scopes[key], key+' changed its native route'
        assert entry['entry']=='renderer IPC desktop:check-release' and entry['native_platform']=='darwin' and entry['native_arch']=='x64'
        assert entry['production_main_unchanged'] is True and entry['candidate_feed_routed_only_in_test'] is True
        assert entry['library_bulk_upload']['native_math_display'] is True and entry['science_formulas']['passed'] is True and len(entry['science_formulas']['views'])==16
        baseline=data(ENTRY_FILES[key]+'.math-before.json')
        assert baseline['accepted']==0 and baseline['ok'] is True and baseline['status']==200 and baseline['target']['title']==baseline['expected_title'] and baseline['requested_record'] in baseline['expected_title']
        assert baseline['target']['question'] and baseline['target']['student_work'] and baseline['deadline_ms']==30000 and baseline['main_deadline_ms']==35000
    uis=[fresh['k12_library'],*(entries[key]['k12_library'] for key in ENTRY_FILES)]
    assert len({ui['evidence_run'] for ui in uis})==5
    for ui,kind in zip(uis,['fresh','current','oldest','current','oldest']):
        assert ui['diagnostic_entry']==kind and {(view['width'],view['height']) for view in ui['views']}=={(390,844),(844,390),(1366,900),(1920,1080)}
        assert data('k12-library-'+kind+'-'+ui['evidence_run']+'.json')==ui, 'Per-route native sidecar changed'
    last=entries['materials_oldest_launcher_entry']
    for name,key in [('library-bulk.json','library_bulk_upload'),('chat-audio.json','chat_audio'),('native-science.json','science_formulas'),('quick-preview.json','quick_preview')]:assert data(name)==last[key]
    assert data('k12-library.json')==last['k12_library']
    return {'files':files,'entries':entries,'smoke':smoke,'fresh_picture_ui':fresh,'network':network,'launcher_tests':tests,'download_files':downloads}


def validate_complete_archive(source_lock, raw):
    validate_source_lock(source_lock)
    assert type(raw) is bytes and len(raw)==COMPLETE_SOURCE['bytes'] and hashlib.sha256(raw).hexdigest()==COMPLETE_SOURCE['sha256'], 'Not the exact complete native source ZIP'
    return validate_complete_records(source_lock,_extract_archive(raw))


def fetch_complete_archive(source_lock, api, gh):
    validate_source_lock(source_lock)
    source=COMPLETE_SOURCE
    meta=api('actions/artifacts/'+str(source['id']))
    assert meta['id']==source['id'] and meta['size_in_bytes']==source['bytes'] and meta['digest']=='sha256:'+source['sha256'] and meta['expired'] is False
    run=api('actions/runs/'+str(source['run_id']))
    assert run['status']=='completed' and run['conclusion']=='failure' and run['head_sha']==source['workflow_commit']
    jobs=api('actions/runs/'+str(source['run_id'])+'/jobs')['jobs']
    assert any(job['id']==source['job_id'] and job['conclusion']=='failure' for job in jobs)
    return validate_complete_archive(source_lock,gh('api','repos/'+REPO+'/actions/artifacts/'+str(source['id'])+'/zip'))


def validate_finalized_provenance(source_lock, provenance, finalization_lock):
    validate_source_lock(source_lock);p=provenance
    assert p['complete_native_execution']==finalization_lock['complete_native_execution']==COMPLETE_SOURCE
    assert (p['source_native_run'],p['source_native_job'],p['source_native_workflow_commit'])==(COMPLETE_SOURCE['run_id'],COMPLETE_SOURCE['job_id'],COMPLETE_SOURCE['workflow_commit'])
    assert type(p['postcheck_run']) is int and p['postcheck_run']>0 and p['postcheck_run']!=COMPLETE_SOURCE['run_id'] and p['verification_run']==p['postcheck_run']
    assert re.fullmatch(r'[a-f0-9]{40}',p['postcheck_workflow_commit']) and p['postcheck_workflow_commit']!=COMPLETE_SOURCE['workflow_commit'] and p['workflow_commit']==p['postcheck_workflow_commit']
    for name in (*RERUN_FLAGS,'bridge_rebuilt','installers_repackaged','existing_assets_overwritten'):assert p[name] is False, 'Reused checks must not claim a new execution: '+name
    for name in ['complete_native_records_reverified','production_launcher_byte_identical','existing_asset_metadata_before_after_unchanged','final_postchecks_completed']:assert p[name] is True
    return True
