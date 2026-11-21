const assert = require('node:assert/strict');
const {appendFileSync, existsSync, readFileSync, writeFileSync} = require('node:fs');
const {createHash} = require('node:crypto');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {setTimeout: pause} = require('node:timers/promises');
const {app, BrowserWindow, dialog, session} = require('electron');

const read = file => JSON.parse(readFileSync(file));
const spec = read(process.env.KX_DIAGRAM_PROBE);
const home = process.env.OPEN_DEEPTUTOR_TEST_HOME;
const report = spec.report;
const phase = report + '.download';
const memory = path.join('data','user','memory','L3','profile.md');
const hash = data => createHash('sha256').update(data).digest('hex');
const original = () => hash(readFileSync(path.join(home,'workspace',memory)));
let accept = 0;
let checkMessage = '';
const attempts = [];
const files = new Map();
const anchors = new Map();

dialog.showMessageBox = async (...args) => {
  const options = args.at(-1);
  checkMessage = options.message;
  if (options.type === 'error' || options.type === 'warning') throw new Error(options.detail || options.message);
  if (options.buttons?.length === 2 && options.detail?.includes(spec.selected.runtimeId)) return {response:++accept};
  return {response:0};
};

function monitor() {
  const originalPartition = session.fromPartition.bind(session);
  const observed = new WeakSet();
  session.fromPartition = (partition, ...args) => {
    const actual = originalPartition(partition,...args);
    if (!partition.startsWith('kaixin-updates') || observed.has(actual)) return actual;
    observed.add(actual);
    const fetch = actual.fetch.bind(actual);
    actual.fetch = async (input, settings) => {
      const url = new URL(input);
      const name = path.posix.basename(url.pathname);
      attempts.push({origin:url.origin,name});
      let expected;
      if (spec.channel === 'cos' && url.origin === spec.cosOrigin) {
        if (name === spec.defaultFile) url.pathname = '/desktop/' + spec.alias;
        expected = spec.cosOrigin;
      } else if (spec.channel === 'github' && url.origin === spec.cosOrigin) {
        return new Response(null,{status:503});
      } else if (spec.channel === 'github' && url.origin === 'https://github.com') {
        url.pathname = url.pathname.replace('/download/core-updates/','/download/'+spec.tag+'/');
        expected = 'https://github.com';
      } else {
        return new Response(null,{status:404});
      }
      assert.equal(url.origin,expected);
      const response = await fetch(url.href, settings);
      if (!response.ok || !response.body) return response;
      const digest = createHash('sha256');
      let bytes = 0;
      let first = null;
      const body = response.body.pipeThrough(new TransformStream({
        transform(chunk, controller) {
          if (first === null && chunk.byteLength) first = Buffer.from(chunk.subarray(0, 1)).toString('hex');
          if (name === spec.delta.name && !files.has(name)) appendFileSync(spec.delta_output, chunk);
          bytes += chunk.byteLength; digest.update(chunk); controller.enqueue(chunk);
        },
        flush() {
          files.set(name,{bytes,sha256:digest.digest('hex')});
          anchors.set(name, { verified: true, url: url.href, first_byte: first,
            version: response.headers.get('x-cos-version-id'), etag: response.headers.get('etag'),
            last_modified: response.headers.get('last-modified') });
        }
      }));
      return new Response(body,{status:response.status, headers:response.headers});
    };
    return actual;
  };
}

async function waitFor(check, description, budget=240000) {
  const deadline = Date.now()+budget;
  do {
    const result = await check();
    if (result) return result;
    await pause(200);
  } while (Date.now()<deadline);
  throw Error('Timed out waiting for '+description);
}

function saveReport(value) {
  writeFileSync(report + ".tmp", JSON.stringify(value));
  require("node:fs").renameSync(report + ".tmp", report);
}

function ready() {
  return waitFor(async () => {
    for (const window of BrowserWindow.getAllWindows()) {
      const view = window.contentView.children.find(x=>x.webContents?.getURL().startsWith('http://127.0.0.1:'));
      if (view && await view.webContents.executeJavaScript('Boolean(document.body?.childElementCount && window.kaixinDesktop?.checkForUpdates)').catch(()=>false)) return view;
    }
  },'learning UI');
}

async function run() {
  await app.whenReady();
  monitor();
  await import(pathToFileURL(path.join(__dirname,'src','main.mjs')));
  const view = await ready();
  const before = read(path.join(home,'active.json'));
  const marker = path.join(home,'upgrade.json');
  const after = existsSync(phase) && read(phase);
  if (after) {
    assert.notEqual(process.pid,after.pid);
    assert.deepEqual(before,spec.selected);
    const action = read(path.join(home, 'launcher-update.json'));
    assert.equal(action.buildId, spec.descriptor.buildId);
    assert.equal(action.restartRequired, false);
    for (const row of spec.descriptor.files) {
      assert.equal(hash(readFileSync(path.join(__dirname, row.file))), row.sha256, row.file);
    }
    assert.equal(original(),after.memory);
    await view.webContents.executeJavaScript('window.kaixinDesktop.checkForUpdates()');
    assert.match(checkMessage,/已是最新版本|already.*up to date/i);
    saveReport({...after,passed:true,checked_again:true,restarted:true,signed_launcher_applied:true,reopened_pid:process.pid});
    app.quit();
    return;
  }
  assert.deepEqual(before,spec.baseline);
  const originalMemory = original();
  void view.webContents.executeJavaScript('window.kaixinDesktop.checkForUpdates()').catch(error=>appendFileSync(report+'.ipc',String(error)));
  const tx = await waitFor(() => {
    if (!existsSync(marker)) return;
    const journal = read(marker);
    if (journal.phase==='complete' && journal.candidate?.commit===spec.selected.commit) return journal;
  },'signed update transaction',780000);
  assert.equal(accept,1);
  assert.deepEqual(read(path.join(home,'active.json')),spec.selected);
  assert.equal(original(),originalMemory);
  assert.equal(hash(readFileSync(path.join(tx.backup,memory))),originalMemory);
  assert.deepEqual(files.get(spec.delta.name),{bytes:spec.delta.bytes,sha256:spec.delta.sha256});
  assert.deepEqual(files.get(spec.manifest.name),{bytes:spec.manifest.bytes,sha256:spec.manifest.sha256});
  assert(!attempts.some(row=>row.name===spec.selected.archive));
  if (spec.channel==='github') assert(attempts.some(row=>row.origin===spec.cosOrigin));
  const updated = await ready();
  await waitFor(() => {
    const file = path.join(home, 'launcher-update.json');
    if (existsSync(file)) {
      const staged = read(file);
      if (staged.status === 'ready' && staged.buildId === spec.descriptor.buildId) return staged;
    }
  }, 'signed launcher pending restart', 120000);
  writeFileSync(phase,JSON.stringify({target:spec.target,commit:spec.selected.commit,channel:spec.channel,
    memory:originalMemory,delta:spec.delta,pid:process.pid,manifest:spec.manifest,attempts,
    delta_anchor: {...anchors.get(spec.delta.name), ...files.get(spec.delta.name)} }));
  const response = await updated.webContents.executeJavaScript(
    "fetch('/api/student/desktop-update/restart', {method:'POST',headers:{'x-kaixin-desktop-action':'restart'}}).then(async r=>[r.status, await r.json()])"
  );
  assert.deepEqual(response, [200, {scheduled:true}]);
}

run().catch(error=>{writeFileSync(report+'.error', error.stack+'\n'+JSON.stringify({attempts,checkMessage})); app.exit(1);});
