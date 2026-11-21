"""Read-only Apple Silicon acceptance against the frozen COS candidate."""
import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tempfile
import time

COMMIT = '8b56d1e7d0c4b629e4de3a1482f1b1e867b378b7'
CORE = 'bb4e751a681ecabf850f839e1389b396eab0d8bbacbc3e9d8fa74cc2a905ed8b'
PREVIOUS = '3fd985e25d4c0812b86b311f27cacf9dc9f60a61420ecf6c6e8770310ac0d6ed'
COS = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
ALIAS = 'runtime-macos-arm64-20261121-mac-integrated-2-candidate.json'
VERSION = '45.1.0'
NAME = '开心动力超级学霸'
PROBE = '// Native QA entry loaded only by the disposable Intel Electron application.\nconst assert = require(\'node:assert/strict\');\nconst { createHash } = require(\'node:crypto\');\nconst { existsSync, readFileSync, writeFileSync, appendFileSync } = require(\'node:fs\');\nconst path = require(\'node:path\');\nconst { pathToFileURL } = require(\'node:url\');\nconst { setTimeout: pause } = require(\'node:timers/promises\');\nconst { app, BrowserWindow, dialog, net, session } = require(\'electron\');\n\nconst profile = process.env.OPEN_DEEPTUTOR_TEST_HOME;\nconst output = process.env.KX_QA_RECEIPT;\nconst spec = JSON.parse(readFileSync(process.env.KX_QA_UPDATE_SPEC));\nconst stateFile = `${output}.state.json`;\nconst read = file => JSON.parse(readFileSync(file));\nconst active = () => read(path.join(profile, \'active.json\'));\nconst launcher = () => read(path.join(profile, \'launcher-update.json\'));\nconst hash = bytes => createHash(\'sha256\').update(bytes).digest(\'hex\');\nconst memory = path.join(\'data\', \'user\', \'memory\', \'L3\', \'profile.md\');\nconst memoryHash = folder => hash(readFileSync(path.join(folder, memory)));\nconst receipts = [];\nconst notices = [];\nconst stage = existsSync(stateFile) ? read(stateFile) : null;\nconst event = (kind, detail = {}) => appendFileSync(`${output}.events.jsonl`, JSON.stringify({ kind, pid: process.pid, at: Date.now(), ...detail }) + \'\\n\');\n\nasync function waitFor(description, fn, maxMs = 120000) {\n  const deadline = Date.now() + maxMs;\n  for (;;) {\n    const error = notices.find(notice => [\'warning\', \'error\'].includes(notice.type));\n    if (error) throw Error(`${error.message} ${error.detail ?? \'\'}`);\n    const result = await fn();\n    if (result) return result;\n    if (Date.now() >= deadline) throw Error(`Timed out waiting for ${description}`);\n    await pause(200);\n  }\n}\n\nfunction readyView() {\n  return waitFor(\'the learning renderer\', async () => {\n    for (const window of BrowserWindow.getAllWindows()) {\n      const view = window.contentView.children.find(child => child.webContents?.getURL().startsWith(\'http://127.0.0.1:\'));\n      if (view && await view.webContents.executeJavaScript(\'Boolean(window.kaixinDesktop?.checkForUpdates && document.body?.childElementCount)\').catch(() => false)) return { window, view };\n    }\n  }, 240000);\n}\n\nfunction mapFeed() {\n  const mirror = \'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com\';\n  const fromPartition = session.fromPartition.bind(session);\n  const installed = new WeakSet();\n  session.fromPartition = (name, ...args) => {\n    const updateSession = fromPartition(name, ...args);\n    if (!/^kaixin-updates(?:-resumed-\\d+)?$/.test(name) || installed.has(updateSession)) return updateSession;\n    installed.add(updateSession);\n    updateSession.fetch = async (input, options) => {\n      const url = new URL(input);\n      if (url.origin !== mirror || !/^\\/desktop\\/[\\w.+-]+\\.(?:json|tar\\.gz)$/.test(url.pathname)) return new Response(null, { status: 404 });\n      const filename = path.basename(url.pathname);\n      if (stage && filename === \'runtime-macos-arm64.json\') await pause(1200);\n      const response = await net.fetch(spec.origin + \'/\' + (filename === \'runtime-macos-arm64.json\' ? \'runtime-macos-arm64-20261121-mac-integrated-2-candidate.json\' : filename), options);\n      if (!response.ok || !response.body) return response;\n      const digest = createHash(\'sha256\');\n      let bytes = 0;\n      const body = response.body.pipeThrough(new TransformStream({\n        transform(chunk, controller) {\n          bytes += chunk.byteLength;\n          digest.update(chunk);\n          controller.enqueue(chunk);\n        },\n        flush() {\n          const transfer = { filename, status: response.status, bytes, sha256: digest.digest(\'hex\') };\n          if (response.status === 206) transfer.content_range = response.headers.get(\'content-range\');\n          receipts.push(transfer);\n          event(\'response-consumed\', transfer);\n        }\n      }));\n      return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });\n    };\n    return updateSession;\n  };\n}\n\nlet accepted = 0;\ndialog.showMessageBox = async (...args) => {\n  const options = args.at(-1);\n  notices.push({ type: options.type, message: options.message, detail: options.detail });\n  if (options.buttons?.length === 2 && options.detail?.includes(spec.selected.runtimeId)) {\n    accepted++;\n    return { response: 1 };\n  }\n  return { response: 0 };\n};\nconst dismissDisposed = error => { if (!/disposed|destroyed/i.test(error.message)) throw error; };\n\nasync function run() {\n  app.commandLine.appendSwitch(\'no-proxy-server\');\n  await app.whenReady();\n  mapFeed();\n  await import(pathToFileURL(path.join(__dirname, \'src/main.mjs\')));\n  const beforeView = await readyView();\n  if (process.env.KX_QA_TEST_BRIDGE === \'1\') {\n    assert.equal(process.arch, \'arm64\');\n    assert.deepEqual(active(), spec.selected);\n    writeFileSync(output, JSON.stringify({passed: true, target: \'macos-arm64\',\n      source_commit: spec.selected.commit, booted: true, runtime: active().runtimeId}));\n    app.quit();\n    return;\n  }\n  if (!stage) {\n    const before = active();\n    assert.deepEqual(before, spec.baseline);\n    const originalMemory = memoryHash(path.join(profile, \'workspace\'));\n    const started = Date.now();\n    event(\'clicked-check-for-updates\', { runtime: before.runtimeId });\n    void beforeView.view.webContents.executeJavaScript(\'window.kaixinDesktop.checkForUpdates()\').catch(error => {\n      try { dismissDisposed(error); } catch { notices.push({ type: \'error\', message: error.message }); }\n    });\n    const transaction = await waitFor(\'the completed installation journal\', () => {\n      const file = path.join(profile, \'upgrade.json\');\n      if (!existsSync(file) || active().commit !== spec.selected.commit) return;\n      const journal = read(file);\n      if (journal.phase === \'complete\') return journal;\n    }, 780000);\n    assert.deepEqual(active(), spec.selected);\n    assert.equal(transaction.previous.runtimeId, before.runtimeId);\n    assert.equal(accepted, 1);\n    assert.equal(memoryHash(path.join(profile, \'workspace\')), originalMemory);\n    assert.equal(memoryHash(transaction.backup), originalMemory);\n    let archive = receipts.find(row => row.filename === spec.archive.name);\n    if (archive?.status === 206) {\n      const bounds = /^bytes (\\d+)-(\\d+)\\/(\\d+)$/.exec(archive.content_range);\n      assert(bounds && Number(bounds[3]) === spec.archive.bytes && Number(bounds[2]) === spec.archive.bytes - 1);\n      assert.equal(archive.bytes + Number(bounds[1]), spec.archive.bytes);\n      // The production updater verifies the entire partial+suffix SHA before committing `active.json`.\n      archive = { ...archive, bytes: spec.archive.bytes, sha256: spec.archive.sha256,\n        resume_offset: Number(bounds[1]), suffix_sha256: archive.sha256, sha256_verified_by: \'native_updater\' };\n    } else {\n      assert.deepEqual(archive, { filename: spec.archive.name, status: 200, bytes: spec.archive.bytes, sha256: spec.archive.sha256 });\n    }\n    const manifest = receipts.find(row => row.filename === spec.manifest.requested && row.sha256 === spec.manifest.sha256);\n    assert(manifest && manifest.status === 200 && manifest.bytes === spec.manifest.bytes);\n    await readyView();\n    const launcherState = launcher();\n    assert.equal(launcherState.buildId, spec.launcherBuild);\n    assert.equal(launcherState.status, \'current\');\n    writeFileSync(stateFile, JSON.stringify({ before, originalMemory, started, completed: Date.now(), beforePid: process.pid, archive, manifest }));\n    event(\'reopened-app-with-existing-verified-launcher\', { launcher: launcherState.buildId });\n    app.relaunch();\n    app.quit();\n    return;\n  }\n  assert.notEqual(process.pid, stage.beforePid);\n  assert.deepEqual(active(), spec.selected);\n  const installedLauncher = await waitFor(\'installed signed launcher\', () => {\n    if (!existsSync(path.join(profile, \'launcher-update.json\'))) return;\n    const state = launcher();\n    if (state.status === \'current\' && !state.restartRequired) return state;\n  });\n  assert.equal(installedLauncher.buildId, spec.launcherBuild);\n  const descriptor = read(path.join(profile, \'runtimes\', spec.selected.runtimeId, \'launcher\', \'manifest.json\'));\n  assert.equal(descriptor.coreCommit, spec.selected.commit);\n  assert.equal(descriptor.buildId, spec.launcherBuild);\n  for (const item of descriptor.files) {\n    const file = readFileSync(path.join(__dirname, item.file));\n    assert.equal(file.byteLength, item.bytes, item.file);\n    assert.equal(hash(file), item.sha256, item.file);\n  }\n  beforeView.window.setFullScreen(true);\n  await waitFor(\'native fullscreen\', () => beforeView.window.isFullScreen());\n  const currentCheck = beforeView.view.webContents.executeJavaScript(\'window.kaixinDesktop.checkForUpdates()\');\n  await waitFor(\'the progress view inside the fullscreen window\', () => {\n    const inside = beforeView.window.contentView.children.find(child => child.webContents?.getURL().endsWith(\'/update-progress.html\'));\n    return inside && BrowserWindow.getAllWindows().length === 1 && beforeView.window.isFullScreen();\n  }, 10000);\n  event(\'progress-in-fullscreen-window\');\n  await currentCheck;\n  assert(notices.some(notice => /已是最新版本|already.*up to date/i.test(notice.message)));\n  assert.equal(BrowserWindow.getAllWindows().length, 1);\n  assert(beforeView.window.isFullScreen());\n  assert.equal(memoryHash(path.join(profile, \'workspace\')), stage.originalMemory);\n  const transaction = read(path.join(profile, \'upgrade.json\'));\n  assert.equal(transaction.phase, \'complete\');\n  assert.equal(memoryHash(transaction.backup), stage.originalMemory);\n  writeFileSync(output, JSON.stringify({ passed: true, target: \'macos-arm64\', source_commit: spec.selected.commit, from: stage.before.runtimeId, to: spec.selected.runtimeId, launcher_build: descriptor.buildId, launcher_files_verified: descriptor.files.length, signed_restart: true, progress_inside_native_fullscreen: true, fullscreen_retained_after_check: true, application_ipc_update: true, check_again_current: true, transaction_phase: transaction.phase, isolated_profile: true, learning_memory_sha256: stage.originalMemory, network: stage.archive, signed_manifest: stage.manifest, transfer_origin: \'public-versioned-cos\', disk_preflight: spec.diskPreflight, downloaded_and_switched_ms: stage.completed - stage.started, complete_ms: Date.now() - stage.started }, null, 2) + \'\\n\');\n  app.quit();\n}\n\nrun().catch(error => {\n  const detail = { error: error.stack, notices, pid: process.pid, active: active()?.runtimeId, stage: stage ? \'new-launcher\' : \'existing-launcher\' };\n  writeFileSync(`${output}.error.json`, JSON.stringify(detail, null, 2));\n  app.exit(1);\n});\n'
KEY = '-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA8QpxFW2KekaGdPipMxCi9UgADS4GG+/4T6BDxcyVa38=\n-----END PUBLIC KEY-----\n'

def read(path):
    return json.loads(path.read_bytes())

def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')

def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream,'sha256').hexdigest()

def download(url, dest, timeout=600):
    subprocess.run(['curl','-fsS','--location','--proto','=https','--proto-redir','=https',
                     '--retry','2','--connect-timeout','12','--max-time',str(timeout),url,'-o',str(dest)],
                   check=True,timeout=timeout+60)

def checked_launcher(resources, runtime, expected_commit):
    launcher = resources/'app'
    shutil.copytree(runtime/'launcher', launcher)
    (launcher/'assets').mkdir(exist_ok=True)
    (launcher/'assets/runtime-public.pem').write_text(KEY, encoding='utf-8')
    node = """
import assert from 'node:assert/strict';
import { createHash, verify } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [root, commit] = process.argv.slice(1);
const { canonicalManifest } = await import(pathToFileURL(root + '/src/bundles.mjs'));
const key = readFileSync(root + '/assets/runtime-public.pem');
const manifest=JSON.parse(readFileSync(root + '/manifest.json'));
assert(verify(null, Buffer.from(canonicalManifest(manifest)),key,Buffer.from(manifest.signature,'base64')));
assert.equal(manifest.coreCommit,commit);
assert.equal(manifest.buildId,'20261121-updater-8');
for (const i of manifest.files) {
  const bytes=readFileSync(root+'/'+i.file);
  assert.equal(bytes.length,i.bytes,i.file);
  assert.equal(createHash('sha256').update(bytes).digest('hex'),i.sha256,i.file);
}
"""
    subprocess.run(['node','--input-type=module','-e',node,str(launcher),expected_commit],check=True)

def run_probe(executable, work, profile, spec, evidence, label, native=False):
    target = evidence/(label+'.json')
    specification = work/(label+'-spec.json')
    write(specification, spec)
    env = dict(os.environ, OPEN_DEEPTUTOR_TEST_HOME=str(profile),
               KX_QA_RECEIPT=str(target), KX_QA_UPDATE_SPEC=str(specification),
               KX_QA_TEST_BRIDGE='1' if native else '0')
    with (evidence/(label+'.log')).open('wb') as log:
        process = subprocess.Popen([str(executable)],cwd=work,stdout=log,stderr=subprocess.STDOUT,env=env)
        try:
            deadline = time.monotonic()+1000
            error = Path(str(target)+'.error.json')
            while not target.exists():
                assert not error.exists(), error.read_text() if error.exists() else ''
                runtime_log = profile/'logs/runtime.log'
                if runtime_log.is_file():
                    startup = runtime_log.read_text(errors='replace')
                    assert 'Desktop startup failed:' not in startup, startup[-4500:]
                assert time.monotonic() < deadline, 'No receipt from native Apple Silicon app'
                time.sleep(1)
        finally:
            runtime_log = profile/'logs/runtime.log'
            if runtime_log.is_file():
                shutil.copyfile(runtime_log, evidence/(label+'-runtime.log'))
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
    result=read(target)
    assert result['passed'] and result['target']=='macos-arm64' and result['source_commit']==COMMIT
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',required=True)
    target=parser.parse_args().target
    evidence=Path.cwd()/f'fresh-evidence/{target}'
    evidence.mkdir(parents=True)
    if target != 'macos-arm64':
        write(evidence/'local-intel.json',{'notice':'Intel acceptance runs on the local physical Mac.'})
        return
    write(evidence/'qa-inputs.json',dict(expected_commit=COMMIT, core_sha256=CORE))
    assert platform.machine() == 'arm64' and platform.system() == 'Darwin'
    work=Path(tempfile.mkdtemp(prefix='kaixin-mac-arm-qa.'))
    stable=work/'runtime-macos-arm64.json'
    download(COS+stable.name,stable)
    assert digest(stable)==PREVIOUS
    old=read(stable)
    previous_archive=work/old['archive']
    print('Fetching verified previous Apple Silicon runtime from COS',flush=True)
    download(COS+previous_archive.name,previous_archive,1200)
    assert digest(previous_archive)==old['sha256']
    profile=work/'delta-profile'
    old_runtime=profile/'runtimes'/old['runtimeId']
    old_runtime.mkdir(parents=True)
    subprocess.run(['/usr/bin/tar','-xzf',str(previous_archive),'-C',str(old_runtime)], check=True,timeout=420)
    previous_archive.unlink()
    assert (old_runtime/'BUILD_COMMIT').read_text().strip()==old['commit']
    write(old_runtime/'installed.json',old)
    write(profile/'active.json',old)
    memory=profile/'workspace/data/user/memory/L3/profile.md'
    memory.parent.mkdir(parents=True)
    memory.write_text('Synthetic Apple Silicon learning profile\n')
    print('Preparing native Electron and verifying previous launcher',flush=True)
    electron_source=f'https://github.com/electron/electron/releases/download/v{VERSION}/'
    checksums=work/'SHASUMS256.txt'
    vendor=work/f'electron-v{VERSION}-darwin-arm64.zip'
    download(electron_source+checksums.name,checksums)
    pins={line.split()[1].lstrip('*'):line.split()[0] for line in checksums.read_text().splitlines() if line.strip()}
    download(electron_source+vendor.name,vendor)
    assert digest(vendor)==pins[vendor.name]
    subprocess.run(['/usr/bin/ditto','-x','-k',str(vendor),str(work)],check=True,timeout=150)
    vendor.unlink()
    app=work/'Electron.app'
    resources=app/'Contents/Resources'
    (resources/'default_app.asar').unlink(missing_ok=True)
    (resources/'seed').mkdir()
    shutil.copyfile(stable, resources/'seed/runtime.json')
    checked_launcher(resources,old_runtime,old['commit'])
    metadata=app/'Contents/Info.plist'
    app_config=plistlib.loads(metadata.read_bytes())
    executable=app/'Contents/MacOS'/NAME
    (executable.parent/'Electron').rename(executable)
    app_config.update(CFBundleExecutable=NAME,CFBundleIdentifier='org.kaixindongli.super-scholar',
                      CFBundleName=NAME,CFBundleDisplayName=NAME)
    metadata.write_bytes(plistlib.dumps(app_config,sort_keys=False))
    (resources/'app/package.json').write_text('{"name": "kaixin-super-scholar", "productName": "开心动力超级学霸", "version": "1.7.1", "description": "开心动力超级学霸学生版：基于 DeepTutor 的本地学习客户端，支持 macOS 和 Windows", "license": "Apache-2.0", "type": "module", "main": "update-probe.cjs", "author": "开心动力"}')
    (resources/'app/update-probe.cjs').write_text(PROBE,encoding='utf-8')
    subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(app)],check=True,timeout=120)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,timeout=120)
    draft=work/ALIAS
    print('Waiting on versioned candidate manifest in COS',flush=True)
    deadline=time.monotonic()+2400
    while True:
        try:
            download(COS+ALIAS,draft,20)
            break
        except subprocess.CalledProcessError:
            if time.monotonic()>=deadline:
                raise
            time.sleep(20)
    candidate=read(draft)
    assert candidate['commit']==COMMIT and candidate['corePayloadSha256']==CORE
    assert candidate['arch']=='arm64' and candidate['platform']=='darwin'
    compat=next(x['file'] for x in candidate['compatibleBaseManifests'] if x['baseRuntimeId']==old['runtimeId'])
    selected_path=work/compat
    download(COS+compat,selected_path)
    selected=read(selected_path)
    delta=selected['coreDelta']
    assert selected['commit']==COMMIT and selected['sha256']==CORE
    assert delta['fromCoreSha256']==old['corePayloadSha256'] and delta['toCoreSha256']==CORE
    print('Running real renderer update from COS and checking restart and memory',flush=True)
    result=run_probe(executable,work,profile,
        dict(origin=COS.rstrip('/'), baseline=old, selected=selected, launcherBuild='20261121-updater-8',
             archive=dict(name=delta['archive'],bytes=delta['bytes'],sha256=delta['sha256']),
             manifest=dict(requested=compat,bytes=selected_path.stat().st_size,sha256=digest(selected_path)),
             diskPreflight=dict(free_bytes=shutil.disk_usage(work).free)),evidence,'matching-delta')
    assert result['network']['sha256']==delta['sha256'] and result['check_again_current']
    print('Verifying standalone Apple Silicon fallback archive and native launch',flush=True)
    bridge=work/candidate['archive']
    download(COS+bridge.name,bridge,1200)
    assert digest(bridge)==candidate['sha256']
    bridge_profile=work/'bridge-profile'
    bridge_runtime=bridge_profile/'runtimes'/candidate['runtimeId']
    bridge_runtime.mkdir(parents=True)
    subprocess.run(['/usr/bin/tar','-xzf',str(bridge),'-C',str(bridge_runtime)],check=True,timeout=420)
    bridge.unlink()
    assert (bridge_runtime/'BUILD_COMMIT').read_text().strip()==COMMIT
    write(bridge_runtime/'installed.json',candidate)
    write(bridge_profile/'active.json',candidate)
    runtime_python=bridge_runtime/'python/bin/python3'
    subprocess.run([str(runtime_python),'-c','import platform; assert platform.machine()=="arm64"'],check=True,timeout=60)
    bridge_result=run_probe(executable,work,bridge_profile,
        dict(origin=COS.rstrip('/'),baseline=candidate,selected=candidate,launcherBuild='20261121-updater-8'),
        evidence,'standalone-bridge',native=True)
    write(evidence/'ARM-NATIVE-PASSED.json',
        dict(passed=True,target=target,source_commit=COMMIT,core_sha256=CORE,bridge_sha256=candidate['sha256'],
             native_machine=platform.machine(),run_id=int(os.environ['GITHUB_RUN_ID']),matching_delta=result,
             standalone_bridge=bridge_result,cos_candidate_sha256=digest(draft)))
    print((evidence/'ARM-NATIVE-PASSED.json').read_text(),flush=True)

if __name__=='__main__':
    main()
