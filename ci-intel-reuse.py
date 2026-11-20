"""Reverify exact existing Intel installers; never package, sign, or replace an asset."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import sys
if __name__ == "__main__" and os.environ.get("GITHUB_REF_NAME") == "codex/k12-intel-reverify-20261117-17-delta":
    subprocess.run([sys.executable, "ci-online17-delta-repair.py"], check=True)
    sys.exit(0)
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO = '1281504089-cell/kaixin-k12-tutor'
TARGET = 'macos-x64'

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
    assert lock['target'] == TARGET and lock['candidate_tag'] == 'student-20261117-k12-1'
    assert lock['candidate_release_id'] == 447366728 and lock['baseline_latest_id'] == 445953276
    assert lock['source_commit'] == '5ff65526b0665ae844d865ef21a88eaebbf63da2'
    assert lock['original_native_run'] == 43922470199
    assert len(lock['candidate_files']) == 4
    assert len({r['id'] for r in lock['candidate_files']}) == 4
    for row in lock['candidate_files']:
        assert Path(row['name']).name == row['name'] and row['name'].startswith('Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-1-part')
        assert row['url'] == 'https://github.com/' + REPO + '/releases/download/' + lock['candidate_tag'] + '/' + row['name']
        assert len(row['sha256']) == 64 and row['bytes'] > 0
    assert hashlib.sha256(frozen_raw).hexdigest() == lock['frozen_stage']['sha256']
    assert len(frozen_raw) == lock['frozen_stage']['bytes']
    frozen = json.loads(frozen_raw)
    assert frozen['core_commit'] == lock['source_commit'] and len(frozen['manifests']) == 36
    assert len(lock['signed_runtime_assets']) == 36
    assert lock['prior_manifest']['commit'] != lock['source_commit']
    assert lock['prior_manifest']['archive'] == lock['prior_core_asset']['name']
    assert lock['prior_manifest']['sha256'] == lock['prior_core_asset']['sha256']
    assert lock['prior_manifest']['baseRuntimeId'] == lock['included_manifest']['baseRuntimeId']
    assert lock['included_manifest']['sha256'] == lock['core_asset']['sha256']
    assert frozen['manifests']['runtime-macos-x64.json']['corePayloadSha256'] == lock['core_asset']['sha256']
    assert lock['prior_core_asset']['url'] == 'https://github.com/' + REPO + '/releases/download/' + lock['baseline_latest_tag'] + '/' + lock['prior_core_asset']['name']
    return frozen

def verify_metadata(lock):
    assert api('releases/latest')['id'] == lock['baseline_latest_id'], 'Latest changed during Intel revalidation'
    release = api('releases/tags/' + lock['candidate_tag'])
    assert release['id'] == lock['candidate_release_id'] and release['prerelease'] and not release['draft']
    assets = {a['name']: a for a in release['assets']}
    expected = [*lock['candidate_files'], lock['core_asset'],
                dict(name=lock['bridge']['name'], id=lock['bridge']['asset_id'], bytes=lock['bridge']['bytes'], sha256=lock['bridge']['sha256']),
                *lock['signed_runtime_assets']]
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
            with urlopen(Request(url, headers={'User-Agent':'Kaixin-Frozen-Intel-Revalidation','Accept':'application/octet-stream'}), timeout=90) as response, partial.open('xb') as output:
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

def verify_signatures(root, resources, lock):
    key = resources / 'app/assets/runtime-public.pem'
    assert sha(key) == lock['public_key_sha256']
    code = """import{readFile}from'node:fs/promises';import{pathToFileURL}from'node:url';import assert from'node:assert/strict';const{verifyManifest}=await import(pathToFileURL(process.argv[1]));const key=await readFile(process.argv[2]);const lock=JSON.parse(await readFile(process.argv[3]));const f=JSON.parse(await readFile(process.argv[4]));for(const m of [lock.included_manifest,lock.prior_manifest,...Object.values(f.manifests)])verifyManifest(m,key,m.arch,m.platform);console.log('PASS: installed public key verified included/prior/all36 stage manifests');"""
    run(['node','--input-type=module','-e',code,resources/'app/src/bundles.mjs',key,root/'intel-reuse-lock.json',root/'attachment-final-manifests.json'])

def verify_proxy(root, resources, evidence):
    probe = root / 'intel-reuse-network-probe.app'
    shutil.copytree(resources.parent.parent, probe, symlinks=True,
                    ignore=lambda directory,names: [n for n in names if n in {'seed','update'}] if Path(directory)==resources else [])
    qa_home = root / 'intel-reuse-proxy-home'
    qa_home.mkdir()
    try:
        copied = probe / 'Contents/Resources'
        package = copied / 'app/package.json'
        value = json.loads(package.read_text());value['main'] = 'src/proxy-smoke.cjs'
        package.write_text(json.dumps(value))
        shutil.copyfile(root/'ci-proxy-smoke.cjs', copied/'app/src/proxy-smoke.cjs')
        run(['/usr/bin/codesign','--force','--deep','--sign','-',probe])
        run([probe/'Contents/MacOS/开心动力超级学霸'],timeout=300,env={**os.environ,
            'KX_PROXY_HOME':str(qa_home),'KX_BASE_MANIFEST':str(resources/'seed/runtime.json'),
            'KX_PROXY_RESULT':str(evidence/'network.json')})
    finally:
        shutil.rmtree(probe)
        shutil.rmtree(qa_home)

def upload_new(tag, path):
    before = api('releases/tags/' + tag)
    assert not any(a['name'] == path.name for a in before['assets']), 'Refuse to overwrite existing evidence: ' + path.name
    error = None
    try:
        gh('release','upload',tag,path)
    except Exception as caught:
        error = caught
    actual = next((a for a in api('releases/tags/' + tag)['assets'] if a['name'] == path.name), None)
    assert actual and actual['digest'] == 'sha256:' + sha(path) and actual['size'] == path.stat().st_size, str(error)

def main():
    root = Path.cwd()
    lock = json.loads((root/'intel-reuse-lock.json').read_text())
    frozen = validate_lock(lock, (root/'attachment-final-manifests.json').read_bytes())
    batch = json.loads((root/'attachment-batch.json').read_text())
    assert batch['manifests'][TARGET] == lock['included_manifest']
    release = verify_metadata(lock)
    evidence = root/'fresh-evidence'/TARGET;evidence.mkdir(parents=True)
    (evidence/'reuse-lock.json').write_bytes((root/'intel-reuse-lock.json').read_bytes())
    run_id = int(os.environ['GITHUB_RUN_ID']);head = os.environ['GITHUB_SHA']
    marker = evidence/('intel-reverify-run-' + str(run_id) + '.json')
    marker.write_text(json.dumps(dict(run_id=run_id,workflow_commit=head,source_commit=lock['source_commit'],original_failed_run=lock['original_native_run'],candidate_reuse=True)))
    upload_new(lock['candidate_tag'],marker)
    work = root/'intel-reuse-work';work.mkdir()
    downloads = work/'downloads';downloads.mkdir()
    receipts = [download(row,downloads) for row in lock['candidate_files']]
    (evidence/'downloads.json').write_text(json.dumps(receipts,indent=2))
    install = work/'installed';install.mkdir()
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
    resources = app/'Contents/Resources'
    included = json.loads((resources/'update/runtime.json').read_text())
    assert included == lock['included_manifest']
    assert json.loads((resources/'seed/runtime.json').read_text())['runtimeId'] == included['baseRuntimeId']
    included_core = resources/'update'/included['archive']
    assert included_core.stat().st_size == lock['core_asset']['bytes'] and sha(included_core) == lock['core_asset']['sha256']
    for name,row in batch['shell_files'].items():assert sha(resources/'app'/name) == row['sha256']
    verify_signatures(root,resources,lock)
    shutil.rmtree(downloads)
    prior = root/'prior-update';prior.mkdir()
    download(lock['prior_core_asset'],prior)
    (prior/'runtime.json').write_text(json.dumps(lock['prior_manifest'],indent=2))
    verify_proxy(root,resources,evidence)
    environment = {**os.environ,'KX_EXPECTED_PLATFORM':'darwin','KX_EXPECTED_ARCH':'x64'}
    home = work/'全新学习目录'
    run(['node','ci-fresh-smoke.mjs',app/'Contents/MacOS/开心动力超级学霸',resources,home,evidence],env=environment,timeout=1100)
    from ci_update_probe import verify_update_entry
    oldest = verify_update_entry(root,TARGET,install,resources,home,evidence,legacy=True)
    current = verify_update_entry(root,TARGET,install,resources,home,evidence)
    verify_metadata(lock)
    report = dict(target=TARGET,input_release=lock['candidate_tag'],input_release_id=release['id'],release=batch['tag'],
        launcher_build=batch['launcher_build'],core_commit=lock['source_commit'],downloaded_from_public_github=True,
        download_files=receipts,native_install='passed',native_smoke=json.loads((evidence/'app.json').read_text()),
        network=json.loads((evidence/'network.json').read_text()),update_entry=current,oldest_launcher_entry=oldest,
        launcher_migration={'from_published_launcher':'oldest-launcher-src frozen on original candidate branch','signed_core_carrier':oldest['signed_launcher_restarted']},
        shell_files=batch['shell_files'],full_files=[dict(file=r['name'],bytes=r['bytes'],sha256=r['sha256']) for r in lock['candidate_files']],
        real_keys_used=False,real_learning_records_modified=False,
        provenance=dict(verification_run=run_id,workflow_commit=head,original_failed_run=lock['original_native_run'],original_failed_job=lock['original_failed_job'],
                        original_stage_run=lock['original_native_run'],original_stage_workflow_commit=lock['original_native_workflow_commit'],
                        frozen_stage_sha256=lock['frozen_stage']['sha256'],bridge_rebuilt=False,installers_repackaged=False,
                        existing_assets_overwritten=False,fresh_smoke_rerun=True,proxy_smoke_rerun=True,oldest_and_current_ipc_rerun=True))
    (evidence/'verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    public = evidence/'verification-macos-x64.json';public.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    upload_new(batch['tag'],public)
    print('PASS: frozen Intel candidate fresh install and both complete real update paths')

if __name__ == '__main__':
    main()
