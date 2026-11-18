"""Reverify exact existing three-platform installers; never package, sign, or replace an asset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO = '1281504089-cell/kaixin-k12-tutor'
TARGETS = {
    'windows-x64': {'lock':'windows-k12-4-reuse-lock.json','arch':'x64','failed_job':133889530356,'platform':'win32','machine':'AMD64'},
    'macos-arm64': {'lock':'arm-k12-4-reuse-lock.json','arch':'arm64','brand':'Apple-Silicon','failed_job':133889530428,'platform':'darwin','machine':'arm64'},
    'macos-x64': {'lock':'intel-k12-4-reuse-lock.json','arch':'x64','brand':'Intel','failed_job':133889530064,'platform':'darwin','machine':'x86_64'},
}

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, **kwargs)

def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)])

def api(path):
    return json.loads(gh('api', 'repos/' + REPO + '/' + path))


# Batch6 is a Windows-only recheck of existing bytes, isolated from legacy4/5 contracts.
def validate_windows6_lock(lock, frozen_raw):
    if sys.flags.optimize:raise RuntimeError('Windows6 QA assertions must remain enabled')
    assert lock.get('execution_frozen') is True, 'Windows6 QA recipe not yet owner-frozen; do not execute'
    assert lock['target']=='windows-x64' and lock['candidate_tag']=='student-20261117-k12-6'
    assert lock['candidate_release_id']==449332202 and lock['baseline_latest_id']==448283800 and lock['baseline_latest_tag']=='student-20261117-k12-4'
    assert lock['source_commit']=='4a61cd7edcd27c6bc6f6bb9305a5a4f3af8851e2' and lock['launcher_build']=='20261118-updater-3'
    assert lock['original_native_run']==44202602948 and lock['original_native_workflow_commit']=='a61f75e11a4d8a7f99cda009e3eb76e6654eb5a0'
    assert lock['original_failed_job']==134460266527 and lock['stage_delivery_commit']=='ca2b5e1ce71a75e4673b9d68319c44d1c6be80d0'
    assert not any(key in lock for key in ['resume_artifact','reused_complete_entries','reused_fresh_picture_ui']), 'Batch6 must rerun fresh and all four complete update paths'
    assert lock['frozen_stage']=={'bytes':43033,'sha256':'b27fe66424ff3ff3475d03d199a626b4d3667f56e2ccc6fd0f51f7b394b40c89','manifests':45}
    assert len(frozen_raw)==43033 and hashlib.sha256(frozen_raw).hexdigest()==lock['frozen_stage']['sha256']
    frozen=json.loads(frozen_raw)
    assert frozen['core_commit']==lock['source_commit'] and len(frozen['manifests'])==45
    anchors={'candidate_files': '5964b29f756b60b526c7e14649fb56a42693874dbb99243074719e376627c823', 'immutable_existing_assets': '44a1cdd9001f45412baad7d4d0602bed85e6e99b8e35065d63653f750b02a8f1', 'prior_manifest': '7658b18daa9af86fdac8c11692059bc648d65c484102693999ddfdce354ec915', 'prior_manifest_asset': '08104b20095c4d7ee5db79d5e8895e34d1f881f7383ece7ca7c94854696c5fe5', 'prior_core_asset': '206b7d4543633c0937028bcbe63b4c05da5ebf8e132b110cd6fb2633a2cec272', 'baseline_feeds': '46c637d6a2c397c56c0267a5795258f086e49f87f4577f270065bab141d1d5f8', 'native_pages': 'de5098675fbb005ff4d3207a4a7da9b218819f894bb9329e10ddaf085267f884'}
    for key,expected in anchors.items():
        actual=hashlib.sha256(json.dumps(lock[key],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        assert actual==expected, 'Batch6 immutable identity changed: '+key
    assert lock['locked_existing_assets_count']==76
    immutable={row['name']:row for row in lock['immutable_existing_assets']}
    assert len(immutable)==76 and len({r['id'] for r in immutable.values()})==76
    assert len(lock['candidate_files'])==5 and len(lock['signed_runtime_assets'])==45
    assert {r['name'] for r in lock['signed_runtime_assets']}==set(frozen['manifests'])
    assert len({r['id'] for r in lock['signed_runtime_assets']})==45
    assert lock['core_asset']=={'name':'kaixin-core-20261117-k12-6.tar.gz','id':761097765,'bytes':837565345,'sha256':'97c3a9e50a3a0e1be88ed6855abab381cfe5689b9580b70ec287f7b6827867e6','url':'https://github.com/'+REPO+'/releases/download/student-20261117-k12-6/kaixin-core-20261117-k12-6.tar.gz'}
    assert lock['bridge']=={'name':'kaixin-bridge-20261117-k12-6-windows-x64.tar.gz','id':761194073,'bytes':1958627156,'sha256':'c52bc767964938fabf14436d88029be38b0c800a13d79557408bd0da31abebcb','url':'https://github.com/'+REPO+'/releases/download/student-20261117-k12-6/kaixin-bridge-20261117-k12-6-windows-x64.tar.gz'}
    for row in [*lock['candidate_files'],lock['core_asset'],lock['bridge'],*lock['signed_runtime_assets']]:
        assert row==immutable[row['name']] and Path(row['name']).name==row['name']
        assert row['url']=='https://github.com/'+REPO+'/releases/download/student-20261117-k12-6/'+row['name']
        assert re.fullmatch(r'[a-f0-9]{64}',row['sha256']) and row['bytes']>0
    assert all(m['commit']==lock['source_commit'] and m['corePayloadSha256']==lock['core_asset']['sha256'] for m in frozen['manifests'].values())
    assert lock['included_manifest']==frozen['manifests']['runtime-windows-x64-20261117-k12-6-20261112.json']
    included,prior=lock['included_manifest'],lock['prior_manifest']
    assert included['platform']=='win32' and included['arch']=='x64' and included['sha256']==lock['core_asset']['sha256']
    assert prior['baseRuntimeId']==included['baseRuntimeId']=='1.7.1-04276f68a-x64'
    assert prior['archive']==lock['prior_core_asset']['name'] and prior['sha256']==lock['prior_core_asset']['sha256']
    bridge=frozen['manifests']['runtime-windows-x64.json']
    assert bridge['archive']==lock['bridge']['name'] and bridge['sha256']==lock['bridge']['sha256'] and bridge.get('baseRuntimeId') is None
    assert lock['public_key_sha256']=='aed6f122112b2dcd78e98e9811c48dcaa779d0ab7a9150acadca36255603e062'
    assert lock['picture_count']==294 and lock['picture_manifest_sha256']=='3983e0c365daef3e15e3352323e1b5ec19d7be42de924744094c20567477cd10'
    assert lock['runtime_exclusion_count']==17 and lock['runtime_exclusion_kinds']=={'bad_asset_sha256':16,'bad_payload_sha256':1}
    assert lock['runtime_exclusion_ledger_sha256']=='d83de01f607be564213c007a6613ca81b3adea2821ef1de83147a298d3f71522'
    assert lock['bank_revision']=='26065ed727a40eab0e29711fd52c00233848e5cd2dd0baabd7f20fff2700c4ee'
    assert lock['launcher_tests']=={'tests':82,'pass':78,'fail':0,'skipped':4}
    required={'ci-materials-ui.cjs','native-materials-fixture.py','attachment-final-manifests.json','ci-mac-reuse.py','ci_update_probe.py','ci-update-flow.cjs','ci-k12-library-ui.cjs','ci_picture_fresh.py','ci-picture-fresh.cjs','native-k12-fixture.py','ci-fresh-smoke.mjs','ci-proxy-smoke.cjs','source-manifest.json','bootstrap_source.py','release_source.py','launcher-manifest.json','attachment-batch.json','materials-upgrade-lock.json','oldest-launcher-fingerprint.json'}
    assert required.issubset(lock['recipe_inputs_sha256'])
    for name,digest in lock['recipe_inputs_sha256'].items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name
        assert isinstance(digest,str) and re.fullmatch(r'[a-f0-9]{64}',digest), 'Owner must freeze final QA input: '+name
    return frozen

def validate_lock(lock, frozen_raw):
    if lock.get('candidate_tag')=='student-20261117-k12-6':return validate_windows6_lock(lock,frozen_raw)
    assert lock['target'] in TARGETS and lock['candidate_tag'] in {'student-20261117-k12-4','student-20261117-k12-5'}
    newer=lock['candidate_tag']=='student-20261117-k12-5'
    if newer:
        assert lock['target']=='macos-x64', 'Only the explicitly frozen failed Intel stage may use this recheck'
        assert {'ci-mac-reuse.py','ci_update_probe.py','ci-update-flow.cjs','ci-k12-library-ui.cjs','ci_picture_fresh.py','native-k12-fixture.py'}.issubset(lock['recipe_inputs_sha256'])
        assert all(re.fullmatch(r'[a-f0-9]{64}',value) for value in lock['recipe_inputs_sha256'].values())
        assert lock['prior_manifest_asset']['url']=='https://github.com/'+REPO+'/releases/download/student-20261117-k12-4/runtime-macos-x64-20261117-k12-4-20261112.json'
        if 'resume_artifact' in lock:
            from partial_native_evidence import validate_partial_lock
            validate_partial_lock(lock)
    target=lock['target'];spec=TARGETS[target]
    assert lock['candidate_release_id'] == (448792391 if newer else 448283800) and lock['baseline_latest_id'] == (448283800 if newer else 447749595)
    assert lock['source_commit'] == ('9328240380d13ef75435434a8c901028ea4470dc' if newer else '2af326481943f7e072036637ba186aa829dce39d')
    assert lock['original_native_run'] == (44132557405 if newer else 44039243704)
    assert lock['original_native_workflow_commit'] == ('5a76064003f5544b2a665ae4ef952538f969cb7f' if newer else '6970e2923f7a0bc260a83d1b2dc9466cc8f5f843')
    assert lock['original_failed_job'] == (134213284667 if newer else spec['failed_job'])
    assert lock['stage_delivery_commit'] == ('4792a1edcc960149b68da314b2ed075141646a14' if newer else 'dc4e0f5d29f8b07222ecc62780f39ce4f820ec20')
    expected_files = 5 if target.startswith('windows') or newer else 4
    assert len(lock['candidate_files']) == len({r['id'] for r in lock['candidate_files']}) == expected_files
    stem = 'Kaixin-Super-Scholar-Windows-v1.7.1-' if target.startswith('windows') else 'Kaixin-Super-Scholar-MacOS-'+spec['brand']+'-v1.7.1-'+lock['candidate_tag'].removeprefix('student-')+'-part'
    expected_names = {stem+'Setup.exe', *(stem+'Runtime.00'+str(i) for i in range(1,5))} if target.startswith('windows') else {stem+'.dmg',*(stem+f'.{i:03d}.dmgpart' for i in range(2,expected_files+1))}
    assert {r['name'] for r in lock['candidate_files']} == expected_names
    for row in lock['candidate_files']:
        assert Path(row['name']).name == row['name'] and row['name'].startswith(stem)
        assert row['url'] == 'https://github.com/' + REPO + '/releases/download/' + lock['candidate_tag'] + '/' + row['name']
        assert len(row['sha256']) == 64 and row['bytes'] > 0
    assert hashlib.sha256(frozen_raw).hexdigest() == lock['frozen_stage']['sha256']
    assert len(frozen_raw) == lock['frozen_stage']['bytes']
    assert lock['frozen_stage'] == ({'bytes':43033,'sha256':'e710fbbeb73959d8ec9841b70f059db01be7df9fdebe018a816db4c5ec2bfa14','manifests':45} if newer else {'bytes':40111,'sha256':'4feedfad84343983983b3738f678799d272a96a0c7b4789b566e23951a928c18','manifests':42})
    frozen = json.loads(frozen_raw)
    assert frozen['core_commit'] == lock['source_commit'] and len(frozen['manifests']) == lock['frozen_stage']['manifests']
    assert len(lock['signed_runtime_assets']) == lock['frozen_stage']['manifests']
    assert {r['name'] for r in lock['signed_runtime_assets']} == set(frozen['manifests'])
    assert len({r['id'] for r in lock['signed_runtime_assets']}) == lock['frozen_stage']['manifests']
    assert all(m['commit'] == lock['source_commit'] and m['corePayloadSha256'] == lock['core_asset']['sha256'] for m in frozen['manifests'].values())
    assert lock['included_manifest']['platform'] == spec['platform'] and lock['included_manifest']['arch'] == spec['arch']
    assert lock['prior_manifest'].get('baseRuntimeId'), 'A full runtime cannot substitute for the prior small core'
    assert lock['prior_manifest']['platform'] == spec['platform'] and lock['prior_manifest']['arch'] == spec['arch']
    assert lock['prior_manifest']['commit'] != lock['source_commit']
    assert lock['prior_manifest']['archive'] == lock['prior_core_asset']['name']
    assert lock['prior_manifest']['sha256'] == lock['prior_core_asset']['sha256']
    assert lock['prior_manifest']['baseRuntimeId'] == lock['included_manifest']['baseRuntimeId']
    assert lock['included_manifest']['sha256'] == lock['core_asset']['sha256']
    assert frozen['manifests']['runtime-'+target+'.json']['corePayloadSha256'] == lock['core_asset']['sha256']
    assert frozen['manifests']['runtime-'+target+'.json']['archive'] == lock['bridge']['name']
    assert frozen['manifests']['runtime-'+target+'.json']['sha256'] == lock['bridge']['sha256']
    assert lock['picture_count'] == 294 and lock['runtime_exclusion_count'] == 17
    assert lock['picture_manifest_sha256'] == '3983e0c365daef3e15e3352323e1b5ec19d7be42de924744094c20567477cd10'
    assert lock['runtime_exclusion_kinds'] == {'bad_asset_sha256':16,'bad_payload_sha256':1}
    immutable = {row['name']:row for row in lock['immutable_existing_assets']}
    assert len(immutable) == len(lock['immutable_existing_assets'])
    assert len(immutable) == lock['locked_existing_assets_count']
    for row in [*lock['candidate_files'],lock['core_asset'],lock['bridge'],*lock['signed_runtime_assets']]:
        assert row == immutable[row['name']], 'Required asset missing or inconsistent in immutable metadata'
        assert Path(row['name']).name == row['name'] and re.fullmatch(r'[a-f0-9]{64}',row['sha256']) and row['bytes'] > 0
        assert row['url'] == 'https://github.com/' + REPO + '/releases/download/' + lock['candidate_tag'] + '/' + row['name']
    assert lock['prior_core_asset']['url'] == 'https://github.com/' + REPO + '/releases/download/' + lock['baseline_latest_tag'] + '/' + lock['prior_core_asset']['name']
    return frozen

def verify_metadata(lock):
    assert api('releases/latest')['id'] == lock['baseline_latest_id'], 'Latest changed during frozen Mac revalidation'
    release = api('releases/tags/' + lock['candidate_tag'])
    assert release['id'] == lock['candidate_release_id'] and release['prerelease'] and not release['draft']
    if lock['candidate_tag']=='student-20261117-k12-6':assert release['tag_name']==lock['candidate_tag']
    assets = {a['name']: a for a in release['assets']}
    expected = lock['immutable_existing_assets']
    for row in expected:
        actual = assets[row['name']]
        assert actual['id'] == row['id'] and actual['size'] == row['bytes'] and actual['digest'] == 'sha256:' + row['sha256'], row['name']
    stable = {a['name']:a for a in api('releases/tags/core-updates')['assets']}
    for name,digest in lock['baseline_feeds'].items():assert stable[name]['digest'] == 'sha256:' + digest, 'Stable feed changed: ' + name
    return release

def download(row, directory):
    file = directory / row['name']
    errors = []
    routes = [row['url'], 'https://api.github.com/repos/' + REPO + '/releases/assets/' + str(row['id']) + '?readback=' + str(time.time_ns())]
    for url in routes:
        partial = file.with_suffix(file.suffix + '.partial')
        try:
            with urlopen(Request(url, headers={'User-Agent':'Kaixin-Frozen-Mac-Revalidation','Accept':'application/octet-stream'}), timeout=90) as response, partial.open('xb') as output:
                final_url = urlparse(response.geturl())
                assert final_url.scheme == 'https' and final_url.hostname in {'github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}
                received = 0
                while chunk := response.read(8 * 1024**2):
                    received += len(chunk)
                    assert received <= row['bytes'], 'Oversized immutable download: ' + row['name']
                    output.write(chunk)
            assert partial.stat().st_size == row['bytes'] and sha(partial) == row['sha256'], row['name']
            partial.rename(file)
            return {**row, 'anonymous_download':True, 'sha256_verified':True}
        except Exception as error:
            partial.unlink(missing_ok=True)
            errors.append(str(error))
    raise RuntimeError('Both anonymous routes failed: ' + row['name'] + ': ' + '; '.join(errors))

def verify_signatures(root, resources, lock, signed_downloads):
    key = resources / 'app/assets/runtime-public.pem'
    assert sha(key) == lock['public_key_sha256']
    code = """import{readFile}from'node:fs/promises';import{pathToFileURL}from'node:url';import path from'node:path';import assert from'node:assert/strict';const{verifyManifest}=await import(pathToFileURL(process.argv[1]));const key=await readFile(process.argv[2]);const lock=JSON.parse(await readFile(process.argv[3]));const f=JSON.parse(await readFile(process.argv[4]));for(const m of [lock.included_manifest,lock.prior_manifest,...Object.values(f.manifests)])verifyManifest(m,key,m.arch,m.platform);for(const row of lock.signed_runtime_assets){const actual=JSON.parse(await readFile(path.join(process.argv[5],row.name)));assert.deepEqual(actual,f.manifests[row.name]);}console.log('PASS: installed public key verified included/prior/all immutable downloaded stage manifests');"""
    run(['node','--input-type=module','-e',code,resources/'app/src/bundles.mjs',key,root/('windows-k12-6-reuse-lock.json' if lock['candidate_tag']=='student-20261117-k12-6' else 'intel-k12-5-reuse-lock.json' if lock['candidate_tag']=='student-20261117-k12-5' else TARGETS[lock['target']]['lock']),root/'attachment-final-manifests.json',signed_downloads])

def verify_proxy(root, resources, evidence, target):
    mac=target.startswith('macos')
    probe = root / (target+'-reuse-network-probe'+('.app' if mac else ''))
    shutil.copytree(resources.parent.parent if mac else resources.parent, probe, symlinks=True,
                    ignore=lambda directory,names: [n for n in names if n in {'seed','update'}] if Path(directory)==resources else [])
    qa_home = root / (target+'-reuse-proxy-home')
    qa_home.mkdir()
    try:
        copied = probe / ('Contents/Resources' if mac else 'resources')
        package = copied / 'app/package.json'
        value = json.loads(package.read_text());value['main'] = 'src/proxy-smoke.cjs'
        package.write_text(json.dumps(value))
        shutil.copyfile(root/'ci-proxy-smoke.cjs', copied/'app/src/proxy-smoke.cjs')
        if mac:run(['/usr/bin/codesign','--force','--deep','--sign','-',probe])
        run([probe/('Contents/MacOS/开心动力超级学霸' if mac else '开心动力超级学霸.exe')],timeout=300,env={**os.environ,
            'KX_PROXY_HOME':str(qa_home),'KX_BASE_MANIFEST':str(resources/'seed/runtime.json'),
            'KX_PROXY_RESULT':str(evidence/'network.json')})
    finally:
        shutil.rmtree(probe)
        shutil.rmtree(qa_home)

def upload_new(tag, path, target):
    assert target in TARGETS and tag in {'student-20261117-k12-4','student-20261117-k12-5','student-20261117-k12-6'}
    if tag=='student-20261117-k12-6':assert target=='windows-x64'
    if tag=='student-20261117-k12-5':assert target=='macos-x64'
    assert path.name == 'verification-'+target+'.json' or re.fullmatch(r'native-reverify-run-'+re.escape(target)+r'-[0-9]+\.json', path.name), 'Only this Mac target\'s new evidence may be uploaded'
    before = api('releases/tags/' + tag)
    assert not any(a['name'] == path.name for a in before['assets']), 'Refuse to overwrite existing evidence: ' + path.name
    error = None
    try:
        gh('release','upload',tag,path,'--repo',REPO)
    except Exception as caught:
        error = caught
    actual = next((a for a in api('releases/tags/' + tag)['assets'] if a['name'] == path.name), None)
    assert actual and actual['digest'] == 'sha256:' + sha(path) and actual['size'] == path.stat().st_size, str(error)

def validate_native_proofs(smoke, fresh, current, oldest, lock, materials, materials_oldest):
    if lock['candidate_tag']=='student-20261117-k12-6':
        for entry in [current,oldest,materials,materials_oldest]:
            assert entry['actual_download_install_backup_restart']=='passed' and entry['check_again_current'] is True and entry['to_launcher']=='20261118-updater-3'
            assert all(entry[k] is True for k in ['chat_preserved','task_preserved','saved_key_preserved'])
    api_proof = smoke['k12_api']
    for field, expected in [('prepared_picture_bindings',lock['picture_count']),('prepared_picture_manifest_sha256',lock['picture_manifest_sha256']),('runtime_isolated_count',lock['runtime_exclusion_count']),('runtime_exclusion_kinds',lock['runtime_exclusion_kinds']),('runtime_exclusion_ledger_sha256',lock['runtime_exclusion_ledger_sha256']),('bank_revision',lock['bank_revision']),('model_calls',0)]:
        assert api_proof[field] == expected, field
    assert api_proof['passed'] is True
    if 'native_pages' in lock:
        from ci_picture_fresh import validate_native_page_api
        validate_native_page_api(api_proof,lock['native_pages'])
    assert fresh['passed'] is True and fresh['production_launcher_source_byte_identical'] is True and fresh['qa_code_only_in_disposable_copy'] is True
    for ui in (fresh['k12_library'], current['k12_library'], oldest['k12_library'],materials['k12_library'],materials_oldest['k12_library']):
        assert ui['passed'] is True and ui['actualNativeRenderer'] is True and ui['bank_revision'] == lock['bank_revision'] and len(ui['views']) == 4
        if 'native_pages' in lock:
            from ci_picture_fresh import validate_native_page_views
            validate_native_page_views(ui,lock['native_pages']['ui_fixture'])
        for view in ui['views']:
            assert all(view['preparedPicture'][key] is True for key in ('native_http_image_sha_verified','body_dom_before_image_response','second_history_restore'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, choices=tuple(TARGETS))
    parser.add_argument('--release-tag',choices=('student-20261117-k12-4','student-20261117-k12-5','student-20261117-k12-6'),default='student-20261117-k12-4')
    args=parser.parse_args();target=args.target
    six=args.release_tag=='student-20261117-k12-6'
    if six:assert target=='windows-x64' and not sys.flags.optimize, 'Only normal nonoptimized Windows6 QA is allowed'
    if args.release_tag=='student-20261117-k12-5':assert target=='macos-x64'
    spec = TARGETS[target]
    assert sys.platform == spec['platform'] and platform.machine() == spec['machine'], 'The selected platform must be tested on its actual native runner'
    mac=target.startswith('macos')
    root = Path.cwd()
    lock_file = root/('windows-k12-6-reuse-lock.json' if six else 'intel-k12-5-reuse-lock.json' if args.release_tag=='student-20261117-k12-5' else spec['lock'])
    lock = json.loads(lock_file.read_text())
    assert lock['target'] == target
    frozen = validate_lock(lock, (root/'attachment-final-manifests.json').read_bytes())
    if six:
        assert re.fullmatch(r'[a-f0-9]{64}',os.environ.get('KX_REUSE_LOCK_SHA256','')) and sha(lock_file)==os.environ['KX_REUSE_LOCK_SHA256'], 'Owner-frozen raw lock SHA required'
        assert os.environ.get('GITHUB_REF_NAME','').startswith('codex/k12-windows6-reverify-20261118-')
        assert int(os.environ['GITHUB_RUN_ID'])!=lock['original_native_run'] and re.fullmatch(r'[a-f0-9]{40}',os.environ['GITHUB_SHA'])
        assert all(not (root/name).exists() for name in ['windows-x64-reuse-work','prior-update','materials-baseline','student-source','launcher-tests-windows-x64']), 'Use a new disposable synthesis directory; never resume accepted requests'
    batch = json.loads((root/'attachment-batch.json').read_text())
    for name,digest in lock['recipe_inputs_sha256'].items(): assert sha(root/name) == digest, 'Frozen recipe input changed: ' + name
    assert batch['manifests'][target] == lock['included_manifest']
    if six:
        assert batch['tag']==lock['candidate_tag'] and batch['core_commit']==lock['source_commit'] and batch['launcher_build']==lock['launcher_build']
        assert json.loads((root/'launcher-manifest.json').read_text())['buildId']==lock['launcher_build']
    release = verify_metadata(lock)
    assert not any(a['name'] == 'verification-'+target+'.json' for a in release['assets']), 'Verification already exists; do not replace it'
    completed = None
    if 'resume_artifact' in lock:
        from partial_native_evidence import fetch_partial_archive
        completed = fetch_partial_archive(lock, api, gh)
    evidence = root/'fresh-evidence'/target;evidence.mkdir(parents=True)
    names={row['name'] for row in lock['immutable_existing_assets']}
    before=[{k:a[k] for k in ('name','id','size','digest')} for a in release['assets'] if a['name'] in names]
    before.sort(key=lambda row:row['name'])
    (evidence/'immutable-assets-before.json').write_text(json.dumps(before,indent=2))
    (evidence/'reuse-lock.json').write_bytes(lock_file.read_bytes())
    if completed:
        for name,raw in completed['files'].items():
            destination=evidence/('completed-source-reuse-lock.json' if name=='reuse-lock.json' else name)
            assert not destination.exists()
            destination.write_bytes(raw)
    run_id = int(os.environ['GITHUB_RUN_ID']);head = os.environ['GITHUB_SHA']
    marker = evidence/('native-reverify-run-'+target+'-' + str(run_id) + '.json')
    marker.write_text(json.dumps(dict(target=target,run_id=run_id,workflow_commit=head,source_commit=lock['source_commit'],original_failed_run=lock['original_native_run'],original_failed_job=lock['original_failed_job'],reuse_lock_file=lock_file.name,reuse_lock_sha256=sha(lock_file),frozen_stage_sha256=lock['frozen_stage']['sha256'],candidate_reuse=True)))
    upload_new(lock['candidate_tag'],marker,target)
    work = root/(target+'-reuse-work');work.mkdir()
    signed_downloads=work/'signed-manifests';signed_downloads.mkdir()
    for row in lock['signed_runtime_assets']: download(row,signed_downloads)
    downloads = work/'downloads';downloads.mkdir()
    receipts = [download(row,downloads) for row in lock['candidate_files']]
    (evidence/'downloads.json').write_text(json.dumps(receipts,indent=2))
    install = work/'installed';install.mkdir()
    if mac:
        mount = work/'mount';mount.mkdir()
        image = next(downloads.glob('*-part.dmg'))
        run(['/usr/bin/hdiutil','verify',image],timeout=300)
        attached = False
        try:
            run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-noautoopen','-mountpoint',mount,image],timeout=300)
            attached = True
            app = install/'开心动力超级学霸.app'
            run(['/usr/bin/ditto',mount/app.name,app])
        finally:
            detached = subprocess.run(['/usr/bin/hdiutil','detach',str(mount)],capture_output=True)
            if attached:assert detached.returncode == 0, detached.stderr.decode(errors='replace')
        run(['/usr/bin/codesign','--verify','--deep','--strict',app])
        resources=app/'Contents/Resources';executable=app/'Contents/MacOS/开心动力超级学霸'
    else:
        installer=next(downloads.glob('*-Setup.exe'))
        setup=subprocess.run('"'+str(installer)+'" /S /D='+str(install),timeout=900)
        assert setup.returncode==0,'Windows installer failed'
        resources=install/'resources';executable=install/'开心动力超级学霸.exe'
    included = json.loads((resources/'update/runtime.json').read_text())
    assert included == lock['included_manifest']
    assert json.loads((resources/'seed/runtime.json').read_text())['runtimeId'] == included['baseRuntimeId']
    included_core = resources/'update'/included['archive']
    assert included_core.stat().st_size == lock['core_asset']['bytes'] and sha(included_core) == lock['core_asset']['sha256']
    for name,row in batch['shell_files'].items():assert sha(resources/'app'/name) == row['sha256']
    assert {file.name for file in (resources/'app/src').iterdir()} == {Path(name).name for name in batch['shell_files']}
    verify_signatures(root,resources,lock,signed_downloads)
    shutil.rmtree(downloads)
    prior = root/'prior-update';prior.mkdir()
    download(lock['prior_core_asset'],prior)
    prior_signed=work/'prior-signed';prior_signed.mkdir()
    download(lock['prior_manifest_asset'],prior_signed)
    prior_raw=(prior_signed/lock['prior_manifest_asset']['name']).read_bytes()
    assert json.loads(prior_raw) == lock['prior_manifest']
    (prior/'runtime.json').write_bytes(prior_raw)
    verify_proxy(root,resources,evidence,target)
    test_root = root / ('launcher-tests-' + target)
    shutil.copytree(resources / 'app/src', test_root / 'src')
    shutil.copytree(root / 'fetchfix-tests', test_root / 'test')
    if not (root / 'student-source').is_dir():
        subprocess.run(['python', 'bootstrap_source.py', '--with-updates'], check=True)
    for folder in ['scripts', 'platforms']:
        shutil.copytree(root / 'student-source/apps/desktop' / folder, test_root / folder)
    shutil.copytree(root / 'student-source/apps/desktop/assets', test_root / 'assets')
    tests = subprocess.run(['node', '--test', '--test-reporter=tap', *[str(p) for p in (test_root / 'test').glob('*.test.mjs')]], capture_output=True, text=True)
    (evidence / 'launcher-tests.tap').write_text(tests.stdout + tests.stderr)
    print(tests.stdout, flush=True)
    tests.check_returncode()
    counts = {key: int(re.search(r'^# ' + key + r' (\d+)$', tests.stdout, re.M).group(1)) for key in ['tests','pass','fail','skipped']}
    assert counts['tests'] >= 81 and counts['fail'] == 0
    if six:assert counts==lock['launcher_tests'], 'Windows6 exact launcher test counts changed'
    (evidence / 'launcher-tests.json').write_text(json.dumps({'passed':True,'native_target':target,**counts},indent=2))
    environment = {**os.environ,'KX_EXPECTED_PLATFORM':spec['platform'],'KX_EXPECTED_ARCH':spec['arch']}
    home = work/'全新学习目录'
    run(['node','ci-fresh-smoke.mjs',executable,resources,home,evidence],env=environment,timeout=1100)
    from ci_picture_fresh import verify_picture_fresh
    reused_fresh = completed is not None and 'fresh_picture_ui' in completed
    fresh_picture_ui = completed['fresh_picture_ui'] if reused_fresh else verify_picture_fresh(root,target,install,resources,home,evidence)
    from ci_update_probe import verify_update_entry
    oldest = completed['entries']['oldest_launcher_entry'] if completed else verify_update_entry(root,target,install,resources,home,evidence,legacy=True)
    current = completed['entries']['update_entry'] if completed else verify_update_entry(root,target,install,resources,home,evidence)
    materials=verify_update_entry(root,target,install,resources,home,evidence,materials=True)
    materials_oldest=verify_update_entry(root,target,install,resources,home,evidence,materials=True,legacy=True)
    smoke=json.loads((evidence/'app.json').read_text())
    validate_native_proofs(smoke,fresh_picture_ui,current,oldest,lock,materials,materials_oldest)
    for name,row in batch['shell_files'].items(): assert sha(resources/'app'/name) == row['sha256'], 'Production launcher changed'
    assert sha(root/'attachment-final-manifests.json') == lock['frozen_stage']['sha256']
    if mac:run(['/usr/bin/codesign','--verify','--deep','--strict',app])
    final_release=verify_metadata(lock)
    after=[{k:a[k] for k in ('name','id','size','digest')} for a in final_release['assets'] if a['name'] in names]
    after.sort(key=lambda row:row['name'])
    assert before == after, 'Existing candidate metadata changed during native verification'
    (evidence/'immutable-assets-after.json').write_text(json.dumps(after,indent=2))
    report = dict(target=target,input_release=lock['candidate_tag'],input_release_id=release['id'],release=batch['tag'],
        launcher_build=batch['launcher_build'],core_commit=lock['source_commit'],downloaded_from_public_github=True,
        download_files=receipts,native_install='passed',native_smoke=smoke,fresh_picture_ui=fresh_picture_ui,
        network=json.loads((evidence/'network.json').read_text()),launcher_tests=json.loads((evidence/'launcher-tests.json').read_text()),update_entry=current,oldest_launcher_entry=oldest,materials_launcher_entry=materials,materials_oldest_launcher_entry=materials_oldest,
        launcher_migration={'from_published_launcher':'oldest-launcher-src frozen on original candidate branch','signed_core_carrier':oldest['signed_launcher_restarted']},
        shell_files=batch['shell_files'],full_files=[dict(file=r['name'],bytes=r['bytes'],sha256=r['sha256']) for r in lock['candidate_files']],
        real_keys_used=False,real_learning_records_modified=False,
        provenance=dict(verification_run=run_id,workflow_commit=head,original_failed_run=lock['original_native_run'],original_failed_job=lock['original_failed_job'],
                        original_stage_run=lock['original_native_run'],original_stage_workflow_commit=lock['original_native_workflow_commit'],
                        frozen_stage_sha256=lock['frozen_stage']['sha256'],bridge_rebuilt=False,installers_repackaged=False,
                        existing_assets_overwritten=False,fresh_smoke_rerun=True,proxy_smoke_rerun=True,oldest_and_current_ipc_rerun=not bool(completed),
                        fresh_picture_ui_rerun=not reused_fresh,materials_both_variants_rerun=True,production_launcher_byte_identical=True,reuse_lock_file=lock_file.name,reuse_lock_sha256=sha(lock_file),existing_asset_metadata_before_after_unchanged=True))
    if completed:report['provenance'].update(completed_entry_receipts_reused=lock['reused_complete_entries'],partial_artifact_sha256=lock['resume_artifact']['sha256'],partial_artifact_source_verified=True)
    if reused_fresh:report['provenance']['completed_fresh_picture_ui_reused']=lock['reused_fresh_picture_ui']
    (evidence/'verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    public = evidence/('verification-'+target+'.json');public.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    upload_new(batch['tag'],public,target)
    print('PASS: frozen '+target+' candidate fresh install and all four complete real update paths')

if __name__ == '__main__':
    main()
