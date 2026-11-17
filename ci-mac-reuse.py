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

def validate_lock(lock, frozen_raw):
    assert lock['target'] in TARGETS and lock['candidate_tag'] == 'student-20261117-k12-4'
    target=lock['target'];spec=TARGETS[target]
    assert lock['candidate_release_id'] == 448283800 and lock['baseline_latest_id'] == 447749595
    assert lock['source_commit'] == '2af326481943f7e072036637ba186aa829dce39d'
    assert lock['original_native_run'] == 44039243704
    assert lock['original_native_workflow_commit'] == '6970e2923f7a0bc260a83d1b2dc9466cc8f5f843'
    assert lock['original_failed_job'] == spec['failed_job']
    assert lock['stage_delivery_commit'] == 'dc4e0f5d29f8b07222ecc62780f39ce4f820ec20'
    expected_files = 5 if target.startswith('windows') else 4
    assert len(lock['candidate_files']) == len({r['id'] for r in lock['candidate_files']}) == expected_files
    stem = 'Kaixin-Super-Scholar-Windows-v1.7.1-' if target.startswith('windows') else 'Kaixin-Super-Scholar-MacOS-'+spec['brand']+'-v1.7.1-20261117-k12-4-part'
    expected_names = {stem+'Setup.exe', *(stem+'Runtime.00'+str(i) for i in range(1,5))} if target.startswith('windows') else {stem + suffix for suffix in ('.dmg','.002.dmgpart','.003.dmgpart','.004.dmgpart')}
    assert {r['name'] for r in lock['candidate_files']} == expected_names
    for row in lock['candidate_files']:
        assert Path(row['name']).name == row['name'] and row['name'].startswith(stem)
        assert row['url'] == 'https://github.com/' + REPO + '/releases/download/' + lock['candidate_tag'] + '/' + row['name']
        assert len(row['sha256']) == 64 and row['bytes'] > 0
    assert hashlib.sha256(frozen_raw).hexdigest() == lock['frozen_stage']['sha256']
    assert len(frozen_raw) == lock['frozen_stage']['bytes']
    assert lock['frozen_stage'] == {'bytes':40111,'sha256':'4feedfad84343983983b3738f678799d272a96a0c7b4789b566e23951a928c18','manifests':42}
    frozen = json.loads(frozen_raw)
    assert frozen['core_commit'] == lock['source_commit'] and len(frozen['manifests']) == 42
    assert len(lock['signed_runtime_assets']) == 42
    assert {r['name'] for r in lock['signed_runtime_assets']} == set(frozen['manifests'])
    assert len({r['id'] for r in lock['signed_runtime_assets']}) == 42
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
    code = """import{readFile}from'node:fs/promises';import{pathToFileURL}from'node:url';import path from'node:path';import assert from'node:assert/strict';const{verifyManifest}=await import(pathToFileURL(process.argv[1]));const key=await readFile(process.argv[2]);const lock=JSON.parse(await readFile(process.argv[3]));const f=JSON.parse(await readFile(process.argv[4]));for(const m of [lock.included_manifest,lock.prior_manifest,...Object.values(f.manifests)])verifyManifest(m,key,m.arch,m.platform);for(const row of lock.signed_runtime_assets){const actual=JSON.parse(await readFile(path.join(process.argv[5],row.name)));assert.deepEqual(actual,f.manifests[row.name]);}console.log('PASS: installed public key verified included/prior/all42 immutable downloaded stage manifests');"""
    run(['node','--input-type=module','-e',code,resources/'app/src/bundles.mjs',key,root/TARGETS[lock['target']]['lock'],root/'attachment-final-manifests.json',signed_downloads])

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
    assert target in TARGETS and tag == 'student-20261117-k12-4'
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
    api_proof = smoke['k12_api']
    for field, expected in [('prepared_picture_bindings',lock['picture_count']),('prepared_picture_manifest_sha256',lock['picture_manifest_sha256']),('runtime_isolated_count',lock['runtime_exclusion_count']),('runtime_exclusion_kinds',lock['runtime_exclusion_kinds']),('runtime_exclusion_ledger_sha256',lock['runtime_exclusion_ledger_sha256']),('bank_revision',lock['bank_revision']),('model_calls',0)]:
        assert api_proof[field] == expected, field
    assert api_proof['passed'] is True
    assert fresh['passed'] is True and fresh['production_launcher_source_byte_identical'] is True and fresh['qa_code_only_in_disposable_copy'] is True
    for ui in (fresh['k12_library'], current['k12_library'], oldest['k12_library'],materials['k12_library'],materials_oldest['k12_library']):
        assert ui['passed'] is True and ui['actualNativeRenderer'] is True and ui['bank_revision'] == lock['bank_revision'] and len(ui['views']) == 4
        for view in ui['views']:
            assert all(view['preparedPicture'][key] is True for key in ('native_http_image_sha_verified','body_dom_before_image_response','second_history_restore'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, choices=tuple(TARGETS))
    target = parser.parse_args().target
    spec = TARGETS[target]
    assert sys.platform == spec['platform'] and platform.machine() == spec['machine'], 'The selected platform must be tested on its actual native runner'
    mac=target.startswith('macos')
    root = Path.cwd()
    lock_file = root/spec['lock']
    lock = json.loads(lock_file.read_text())
    assert lock['target'] == target
    frozen = validate_lock(lock, (root/'attachment-final-manifests.json').read_bytes())
    batch = json.loads((root/'attachment-batch.json').read_text())
    for name,digest in lock['recipe_inputs_sha256'].items(): assert sha(root/name) == digest, 'Frozen recipe input changed: ' + name
    assert batch['manifests'][target] == lock['included_manifest']
    release = verify_metadata(lock)
    assert not any(a['name'] == 'verification-'+target+'.json' for a in release['assets']), 'Verification already exists; do not replace it'
    evidence = root/'fresh-evidence'/target;evidence.mkdir(parents=True)
    names={row['name'] for row in lock['immutable_existing_assets']}
    before=[{k:a[k] for k in ('name','id','size','digest')} for a in release['assets'] if a['name'] in names]
    before.sort(key=lambda row:row['name'])
    (evidence/'immutable-assets-before.json').write_text(json.dumps(before,indent=2))
    (evidence/'reuse-lock.json').write_bytes(lock_file.read_bytes())
    run_id = int(os.environ['GITHUB_RUN_ID']);head = os.environ['GITHUB_SHA']
    marker = evidence/('native-reverify-run-'+target+'-' + str(run_id) + '.json')
    marker.write_text(json.dumps(dict(target=target,run_id=run_id,workflow_commit=head,source_commit=lock['source_commit'],original_failed_run=lock['original_native_run'],original_failed_job=lock['original_failed_job'],reuse_lock_file=spec['lock'],reuse_lock_sha256=sha(lock_file),frozen_stage_sha256=lock['frozen_stage']['sha256'],candidate_reuse=True)))
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
    (evidence / 'launcher-tests.json').write_text(json.dumps({'passed':True,'native_target':target,**counts},indent=2))
    environment = {**os.environ,'KX_EXPECTED_PLATFORM':spec['platform'],'KX_EXPECTED_ARCH':spec['arch']}
    home = work/'全新学习目录'
    run(['node','ci-fresh-smoke.mjs',executable,resources,home,evidence],env=environment,timeout=1100)
    from ci_picture_fresh import verify_picture_fresh
    fresh_picture_ui = verify_picture_fresh(root,target,install,resources,home,evidence)
    from ci_update_probe import verify_update_entry
    oldest = verify_update_entry(root,target,install,resources,home,evidence,legacy=True)
    current = verify_update_entry(root,target,install,resources,home,evidence)
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
                        existing_assets_overwritten=False,fresh_smoke_rerun=True,proxy_smoke_rerun=True,oldest_and_current_ipc_rerun=True,
                        fresh_picture_ui_rerun=True,materials_both_variants_rerun=True,production_launcher_byte_identical=True,reuse_lock_file=spec['lock'],reuse_lock_sha256=sha(lock_file),existing_asset_metadata_before_after_unchanged=True))
    (evidence/'verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    public = evidence/('verification-'+target+'.json');public.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    upload_new(batch['tag'],public,target)
    print('PASS: frozen '+target+' candidate fresh install and all four complete real update paths')

if __name__ == '__main__':
    main()
