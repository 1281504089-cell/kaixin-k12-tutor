"""Boot both final signed recovery archives with the native packaged launcher."""
import argparse
import gzip
from hashlib import file_digest
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import time

COMMIT='8b56d1e7d0c4b629e4de3a1482f1b1e867b378b7'
CORE='bb4e751a681ecabf850f839e1389b396eab0d8bbacbc3e9d8fa74cc2a905ed8b'
COS='https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
VERSION='45.1.0'
NAME='开心动力超级学霸'
PUBLIC_KEY='-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA8QpxFW2KekaGdPipMxCi9UgADS4GG+/4T6BDxcyVa38=\n-----END PUBLIC KEY-----\n'
PACKAGE='{"name": "kaixin-super-scholar", "productName": "开心动力超级学霸", "version": "1.7.1", "description": "开心动力超级学霸学生版：基于 DeepTutor 的本地学习客户端，支持 macOS 和 Windows", "license": "Apache-2.0", "type": "module", "main": "recovery-probe.cjs", "author": "开心动力"}'
PROBE="""
const assert = require('node:assert/strict');
const { readFileSync, writeFileSync } = require('node:fs');
const { pathToFileURL } = require('node:url');
const { resolve } = require('node:path');
const { setTimeout: pause } = require('node:timers/promises');
const { app, BrowserWindow } = require('electron');
const profile = process.env.OPEN_DEEPTUTOR_TEST_HOME;
const receipt = process.env.KX_NATIVE_RECEIPT;
const commit = process.env.KX_NATIVE_COMMIT;
async function run() {
  await app.whenReady();
  await import(pathToFileURL(resolve(__dirname, 'src/main.mjs')));
  const limit = Date.now() + 240000;
  do {
    for (const window of BrowserWindow.getAllWindows()) {
      const view = window.contentView.children.find(x => x.webContents?.getURL().startsWith('http://127.0.0.1:'));
      if (!view) continue;
      const booted = await view.webContents.executeJavaScript('Boolean(document.body?.childElementCount && window.kaixinDesktop?.checkForUpdates)').catch(() => false);
      if (!booted) continue;
      const active = JSON.parse(readFileSync(resolve(profile,'active.json')));
      assert.equal(active.commit,commit);
      assert.equal(active.arch,process.arch);
      assert(!active.baseRuntimeId);
      const launcher = JSON.parse(readFileSync(resolve(profile,'launcher-update.json')));
      assert.equal(launcher.buildId,'20261121-updater-8');
      assert.equal(launcher.status,'current');
      writeFileSync(receipt, JSON.stringify({passed:true,booted:true,source_commit:commit,
        target:'macos-'+process.arch,runtime:active.runtimeId,archive:active.archive,archive_sha256:active.sha256,
        core_sha256:active.corePayloadSha256,full_install_seed:true,launcher_build:launcher.buildId}));
      app.quit();
      return;
    }
    await pause(250);
  } while(Date.now()<limit);
  throw Error('Application learning renderer did not open');
}
run().catch(error=>{console.error(error);app.exit(1);});
"""

def read(path):
    return json.loads(path.read_bytes())

def digest(path):
    with path.open('rb') as file:
        return file_digest(file,'sha256').hexdigest()

def fetch(url,file,timeout=600):
    subprocess.run(['curl','-fsS','--location','--proto','=https','--proto-redir','=https',
                    '--retry','2','--connect-timeout','12','--max-time',str(timeout),url,'-o',str(file)],
                   check=True,timeout=timeout+60)

def launcher_files(archive, destination):
    dst=destination/'src'
    dst.mkdir(parents=True)
    with gzip.open(archive,'rb') as data, tarfile.open(fileobj=data,mode='r|') as tar:
        for member in tar:
            name=member.name.removeprefix('./')
            if name=='launcher/manifest.json':
                (destination/'manifest.json').write_bytes(tar.extractfile(member).read())
            if name.startswith('launcher/src/'):
                assert member.isfile() and '/' not in name.removeprefix('launcher/src/')
                (dst/Path(name).name).write_bytes(tar.extractfile(member).read())
    assert (destination/'manifest.json').is_file()
    (destination/'assets').mkdir()
    (destination/'assets/runtime-public.pem').write_text(PUBLIC_KEY)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',required=True)
    target=parser.parse_args().target
    arch=target.removeprefix('macos-')
    assert arch in ('arm64','x64')
    assert platform.machine()=={'arm64':'arm64','x64':'x86_64'}[arch]
    evidence=Path.cwd()/f'fresh-evidence/{target}'
    evidence.mkdir(parents=True)
    work=Path(tempfile.mkdtemp(prefix='kaixin-mac-cos-recovery.'))
    print(f'Preparing native macOS {arch} Electron',flush=True)
    vendor=work/f'electron-v{VERSION}-darwin-{arch}.zip'
    origin=f'https://github.com/electron/electron/releases/download/v{VERSION}/'
    checksum=work/'SHASUMS256.txt'
    fetch(origin+checksum.name,checksum)
    known={row.split()[1].lstrip('*'):row.split()[0] for row in checksum.read_text().splitlines() if row.strip()}
    fetch(origin+vendor.name,vendor)
    assert digest(vendor)==known[vendor.name]
    subprocess.run(['/usr/bin/ditto','-x','-k',str(vendor),str(work)],check=True,timeout=150)
    vendor.unlink()
    app=work/'Electron.app'
    resources=app/'Contents/Resources'
    (resources/'default_app.asar').unlink(missing_ok=True)
    seed=resources/'seed'
    seed.mkdir()
    alias=f'runtime-{target}-20261121-mac-integrated-2-recovery-r2.json'
    manifest=seed/'runtime.json'
    print('Waiting for the exact signed recovery candidate',flush=True)
    deadline=time.monotonic()+2700
    while True:
        try:
            fetch(COS+alias,manifest,20)
            break
        except subprocess.CalledProcessError:
            if time.monotonic()>=deadline:
                raise
            time.sleep(12)
    document=read(manifest)
    assert document['commit']==COMMIT and document['arch']==arch and document['platform']=='darwin'
    assert document['corePayloadSha256']==CORE and '-r2-' in document['archive']
    archive=seed/document['archive']
    print(f'Downloading {archive.name} from COS',flush=True)
    fetch(COS+archive.name,archive,1200)
    assert digest(archive)==document['sha256']
    app_resource=resources/'app'
    launcher_files(archive,app_resource)
    (app_resource/'package.json').write_text(PACKAGE)
    (app_resource/'recovery-probe.cjs').write_text(PROBE)
    metadata=app/'Contents/Info.plist'
    config=plistlib.loads(metadata.read_bytes())
    executable=app/'Contents/MacOS'/NAME
    (executable.parent/'Electron').rename(executable)
    config.update(CFBundleExecutable=NAME,CFBundleIdentifier='org.kaixindongli.super-scholar',
                  CFBundleName=NAME,CFBundleDisplayName=NAME)
    metadata.write_bytes(plistlib.dumps(config,sort_keys=False))
    subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(app)],check=True,timeout=120)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,timeout=120)
    print('Running a clean native install through the packaged app',flush=True)
    profile=work/'isolated-profile'
    profile.mkdir()
    result_file=evidence/'RECOVERY-NATIVE-PASSED.json'
    env=dict(os.environ,OPEN_DEEPTUTOR_TEST_HOME=str(profile),KX_NATIVE_RECEIPT=str(result_file),KX_NATIVE_COMMIT=COMMIT)
    try:
        with (evidence/'recovery-boot.log').open('wb') as log:
            subprocess.run([str(executable)],env=env,check=True,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=550)
    finally:
        log=profile/'logs/runtime.log'
        if log.exists():
            shutil.copyfile(log,evidence/'runtime.log')
    result=read(result_file)
    assert result['passed'] and result['full_install_seed'] and result['archive_sha256']==document['sha256']
    assert result['target']==target and result['core_sha256']==CORE and result['source_commit']==COMMIT
    result.update(cos_candidate_sha256=digest(manifest),native_machine=platform.machine(),run_id=int(os.environ['GITHUB_RUN_ID']))
    result_file.write_text(json.dumps(result)+'\n')
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    main()
