const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {existsSync, readdirSync, readFileSync, writeFileSync} = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {setTimeout: pause} = require('node:timers/promises');
const {app, BrowserWindow, dialog, net, session} = require('electron');

const read = file => JSON.parse(readFileSync(file));
const spec = read(process.env.KX_QA_SPEC);
const home = process.env.OPEN_DEEPTUTOR_TEST_HOME;
const phase = spec.result + '.phase';
const restarted = existsSync(phase);
const recordText = '# 升级验收\n\n我的学习记录：我会用正斜率判断一次函数递增。\n';
const recordPhrase = '我会用正斜率判断一次函数递增';
const workspace = path.join(home,'workspace');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const memoryBytes = (folder, relative) => readFileSync(path.join(folder, relative));
const receipt = new Map();
const attempts = [];
const notices = [];
let accepted = 0;
const allowed = new Set([spec.cos.stable, spec.cos.selected, spec.cos.delta.archive]);
const cosOrigin = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com';

function restrainTransport() {
  const partition = session.fromPartition.bind(session);
  const configured = new WeakSet();
  session.fromPartition = (name, ...args) => {
    const current = partition(name, ...args);
    if (!name.startsWith('kaixin-updates') || configured.has(current)) return current;
    configured.add(current);
    current.fetch = async (request, options) => {
      const url = new URL(request);
      const filename = path.posix.basename(url.pathname);
      attempts.push(filename);
      if (url.origin !== cosOrigin || url.pathname !== '/desktop/' + filename || !allowed.has(filename)) {
        return new Response(null, {status:404});
      }
      const response = await net.fetch(spec.origin + '/' + filename, options);
      if (!response.ok) return response;
      const data = Buffer.from(await response.arrayBuffer());
      receipt.set(filename, {bytes:data.length, sha256:hash(data)});
      return new Response(data, {status:response.status, headers:response.headers});
    };
    return current;
  };
}

dialog.showMessageBox = async (...args) => {
  const info = args.at(-1);
  notices.push({type:info.type, message:info.message, detail:info.detail});
  if (info.buttons?.length === 2 && info.detail?.includes(spec.selected.runtimeId)) {
    accepted++;
    return {response:1};
  }
  return {response:0};
};

async function waitFor(label, inspect, timeout=240000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const error = notices.find(row => row.type === 'warning' || row.type === 'error');
    if (error) throw Error(error.message + ' ' + (error.detail || ''));
    const found = await inspect();
    if (found) return found;
    await pause(220);
  }
  throw Error('Timeout waiting for ' + label);
}

const active = () => read(path.join(home, 'active.json'));
const journal = () => read(path.join(home, 'upgrade.json'));
function ready() {
  return waitFor('native learning window', async () => {
    for (const window of BrowserWindow.getAllWindows()) {
      const view = window.contentView.children.find(child => child.webContents?.getURL().startsWith('http://127.0.0.1:'));
      if (view && await view.webContents.executeJavaScript('Boolean(window.kaixinDesktop?.checkForUpdates && document.body?.childElementCount)').catch(() => false)) return view.webContents;
    }
  });
}

async function seedRecord(contents) {
  const script = `fetch('/api/memory/doc/L3/profile', {
    method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({content:${JSON.stringify(recordText)}})
  }).then(async r => ({status:r.status, saved:r.ok && (await r.json()).saved}))`;
  assert.deepEqual(await contents.executeJavaScript(script), {status:200,saved:true});
  const suffix = path.join('L3','profile.md');
  const matches = readdirSync(workspace,{recursive:true}).filter(file =>
    file.endsWith(suffix) && memoryBytes(workspace,file).toString('utf8').includes(recordPhrase));
  assert.equal(matches.length, 1, 'Locate the test record actually written by the application');
  return matches[0];
}

async function visibleRecord(contents) {
  const record = await contents.executeJavaScript(
    "fetch('/api/memory/doc/L3/profile', {cache:'no-store'}).then(async r => ({status:r.status, content:r.ok ? (await r.json()).content : null}))"
  );
  assert.equal(record.status, 200, 'learning memory endpoint');
  assert(record.content.includes(recordPhrase));
  return hash(record.content);
}

async function main() {
  app.commandLine.appendSwitch('no-proxy-server');
  await app.whenReady();
  restrainTransport();
  const {verifyManifest, compatibleCoreDelta} = await import(pathToFileURL(path.join(__dirname,'src','bundles.mjs')));
  const key = readFileSync(path.join(__dirname, 'assets/runtime-public.pem'));
  for (const manifest of [spec.baseline, spec.current, spec.selected]) verifyManifest(manifest, key);
  const delta = compatibleCoreDelta(spec.selected, spec.baseline);
  assert.deepEqual(delta, spec.cos.delta);

  await import(pathToFileURL(path.join(__dirname, 'src', 'main.mjs')));
  const window = await ready();
  if (restarted) {
    const before = read(phase);
    assert.notEqual(process.pid, before.pid);
    assert.deepEqual(active(), spec.selected);
    const launcher = read(path.join(home, 'launcher-update.json'));
    assert.equal(launcher.buildId, spec.launcher);
    assert.equal(launcher.status, 'current');
    assert.equal(launcher.restartRequired, false);
    const descriptor = read(path.join(home,'runtimes',spec.selected.runtimeId,'launcher','manifest.json'));
    assert.equal(descriptor.coreCommit, spec.selected.commit);
    for (const row of descriptor.files) assert.equal(hash(readFileSync(path.join(__dirname,row.file))),row.sha256);
    assert.equal(hash(memoryBytes(workspace,before.record_path)), before.disk_sha256);
    assert.equal(await visibleRecord(window), before.record_sha256);
    assert.equal(hash(memoryBytes(journal().backup,before.record_path)), before.disk_sha256);
    await window.executeJavaScript('window.kaixinDesktop.checkForUpdates()');
    assert(notices.some(row=>/已是最新版本|already.*up to date/i.test(row.message)));
    assert(attempts.every(name=>allowed.has(name)));
    writeFileSync(spec.result, JSON.stringify({passed:true,target:spec.target,current_commit:spec.selected.commit,
      from_runtime:spec.baseline.runtimeId,to_runtime:spec.selected.runtimeId,
      updater:'packaged native Electron',archive_transport:'runner-local loopback',signed_update:true,restarted:true,
      check_again_current:true,learning_record_reopened:true,workspace_backup_verified:true,
      previous_process:before.pid,restarted_process:process.pid,learning_record_sha256:before.record_sha256,
      delta_bytes:before.delta.bytes,delta_sha256:before.delta.sha256},null,2)+'\n');
    app.quit();
    return;
  }

  assert.deepEqual(active(), spec.baseline);
  const recordPath = await seedRecord(window);
  const afterSeed = await visibleRecord(window);
  const diskHash = hash(memoryBytes(workspace,recordPath));
  void window.executeJavaScript('window.kaixinDesktop.checkForUpdates()').catch(error => {
    if (!/disposed|destroyed/i.test(error.message)) notices.push({type:'error',message:error.message});
  });
  const update = await waitFor('completed update journal', () => {
    const file = path.join(home, 'upgrade.json');
    if (existsSync(file) && active().commit === spec.selected.commit && journal().phase === 'complete') return journal();
  }, 900000);
  assert.deepEqual(active(), spec.selected);
  assert.equal(update.previous.runtimeId, spec.baseline.runtimeId);
  assert.equal(accepted,1);
  assert.deepEqual(receipt.get(spec.cos.delta.archive),{bytes:spec.cos.delta.bytes, sha256:spec.cos.delta.sha256});
  assert.equal(receipt.get(spec.cos.stable).sha256,spec.cos.stable_sha256);
  assert.equal(receipt.get(spec.cos.selected).sha256,spec.cos.selected_sha256);
  assert(attempts.every(name=>allowed.has(name)));
  assert.equal(hash(memoryBytes(update.backup,recordPath)),diskHash);
  await ready();
  writeFileSync(phase, JSON.stringify({pid:process.pid,record_path:recordPath,disk_sha256:diskHash,record_sha256:afterSeed,delta:receipt.get(spec.cos.delta.archive)}));
  app.relaunch();
  app.quit();
}

main().catch(error => {
  writeFileSync(spec.result.replace(/\.json$/,'.error.txt'), error.stack + '\n' + JSON.stringify({attempts,notices}));
  app.exit(1);
});
