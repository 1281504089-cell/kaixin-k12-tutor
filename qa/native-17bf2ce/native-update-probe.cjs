// Native QA entry loaded only by the disposable Electron application.
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { existsSync, readFileSync, writeFileSync, appendFileSync } = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { setTimeout: pause } = require('node:timers/promises');
const { app, BrowserWindow, dialog, net, session } = require('electron');

const profile = process.env.OPEN_DEEPTUTOR_TEST_HOME;
const output = process.env.KX_QA_RECEIPT;
const spec = JSON.parse(readFileSync(process.env.KX_QA_UPDATE_SPEC));
const stateFile = `${output}.state.json`;
const read = file => JSON.parse(readFileSync(file));
function active() {
  try {
    return read(path.join(profile, 'active.json'));
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}
const launcher = () => read(path.join(profile, 'launcher-update.json'));
function verifyInstalledLauncher() {
  const descriptor = read(path.join(profile, 'runtimes', spec.selected.runtimeId, 'launcher', 'manifest.json'));
  assert.equal(descriptor.coreCommit, spec.selected.commit);
  assert.equal(descriptor.buildId, spec.launcherBuild);
  for (const item of descriptor.files) {
    const file = readFileSync(path.join(__dirname, item.file));
    assert.equal(file.byteLength, item.bytes, item.file);
    assert.equal(hash(file), item.sha256, item.file);
  }
  return descriptor;
}
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const memory = path.join('data', 'user', 'memory', 'L3', 'profile.md');
const memoryHash = folder => hash(readFileSync(path.join(folder, memory)));
const receipts = [];
const notices = [];
const stage = existsSync(stateFile) ? read(stateFile) : null;
const event = (kind, detail = {}) => appendFileSync(`${output}.events.jsonl`, JSON.stringify({ kind, pid: process.pid, at: Date.now(), ...detail }) + '\n');

async function waitFor(description, fn, maxMs = 120000) {
  const deadline = Date.now() + maxMs;
  for (;;) {
    const error = notices.find(notice => ['warning', 'error'].includes(notice.type));
    if (error) throw Error(`${error.message} ${error.detail ?? ''}`);
    const result = await fn();
    if (result) return result;
    if (Date.now() >= deadline) throw Error(`Timed out waiting for ${description}`);
    await pause(200);
  }
}

function readyView() {
  return waitFor('the learning renderer', async () => {
    for (const window of BrowserWindow.getAllWindows()) {
      const view = window.contentView.children.find(child => child.webContents?.getURL().startsWith('http://127.0.0.1:'));
      if (view && await view.webContents.executeJavaScript('Boolean(window.kaixinDesktop?.checkForUpdates && document.body?.childElementCount)').catch(() => false)) return { window, view };
    }
  }, 240000);
}

function mapFeed() {
  const mirror = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com';
  const fromPartition = session.fromPartition.bind(session);
  const installed = new WeakSet();
  session.fromPartition = (name, ...args) => {
    const updateSession = fromPartition(name, ...args);
    if (!/^kaixin-updates(?:-resumed-\d+)?$/.test(name) || installed.has(updateSession)) return updateSession;
    installed.add(updateSession);
    updateSession.fetch = async (input, options) => {
      const url = new URL(input);
      if (url.origin !== mirror || !/^\/desktop\/[\w.+-]+\.(?:json|tar\.gz)$/.test(url.pathname)) return new Response(null, { status: 404 });
      const filename = path.basename(url.pathname);
      if (stage && filename === `runtime-${spec.target}.json`) await pause(1200);
      const response = await net.fetch(spec.origin + '/' + filename, options);
      if (!response.ok || !response.body) return response;
      const digest = createHash('sha256');
      let bytes = 0;
      const body = response.body.pipeThrough(new TransformStream({
        transform(chunk, controller) {
          bytes += chunk.byteLength;
          digest.update(chunk);
          controller.enqueue(chunk);
        },
        flush() {
          const transfer = { filename, status: response.status, bytes, sha256: digest.digest('hex') };
          if (response.status === 206) transfer.content_range = response.headers.get('content-range');
          receipts.push(transfer);
          event('response-consumed', transfer);
        }
      }));
      return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });
    };
    return updateSession;
  };
}

let accepted = 0;
dialog.showMessageBox = async (...args) => {
  const options = args.at(-1);
  notices.push({ type: options.type, message: options.message, detail: options.detail });
  if (options.buttons?.length === 2 && options.detail?.includes(spec.selected.runtimeId)) {
    accepted++;
    return { response: 1 };
  }
  return { response: 0 };
};
const dismissDisposed = error => { if (!/disposed|destroyed/i.test(error.message)) throw error; };

async function run() {
  app.commandLine.appendSwitch('no-proxy-server');
  await app.whenReady();
  mapFeed();
  await import(pathToFileURL(path.join(__dirname, 'src/main.mjs')));
  const expected = stage ? spec.selected : spec.baseline;
  await waitFor('the signed runtime to be activated', () => {
    const manifest = active();
    return manifest?.runtimeId === expected.runtimeId ? manifest : null;
  }, 900000);
  const beforeView = await readyView();
  if (!stage) {
    const before = active();
    assert.deepEqual(before, spec.baseline);
    const originalMemory = memoryHash(path.join(profile, 'workspace'));
    const started = Date.now();
    event('clicked-check-for-updates', { runtime: before.runtimeId });
    void beforeView.view.webContents.executeJavaScript('window.kaixinDesktop.checkForUpdates()').catch(error => {
      try { dismissDisposed(error); } catch { notices.push({ type: 'error', message: error.message }); }
    });
    const transaction = await waitFor('the completed installation journal', () => {
      const file = path.join(profile, 'upgrade.json');
      if (!existsSync(file) || active()?.commit !== spec.selected.commit) return;
      const journal = read(file);
      if (journal.phase === 'complete') return journal;
    }, 780000);
    assert.deepEqual(active(), spec.selected);
    assert.equal(transaction.previous.runtimeId, before.runtimeId);
    assert.equal(accepted, 1);
    assert.equal(memoryHash(path.join(profile, 'workspace')), originalMemory);
    assert.equal(memoryHash(transaction.backup), originalMemory);
    let archive = receipts.find(row => row.filename === spec.archive.name);
    if (archive?.status === 206) {
      const bounds = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(archive.content_range);
      assert(bounds && Number(bounds[3]) === spec.archive.bytes && Number(bounds[2]) === spec.archive.bytes - 1);
      assert.equal(archive.bytes + Number(bounds[1]), spec.archive.bytes);
      // The production updater verifies the entire partial+suffix SHA before committing `active.json`.
      archive = { ...archive, bytes: spec.archive.bytes, sha256: spec.archive.sha256,
        resume_offset: Number(bounds[1]), suffix_sha256: archive.sha256, sha256_verified_by: 'native_updater' };
    } else {
      assert.deepEqual(archive, { filename: spec.archive.name, status: 200, bytes: spec.archive.bytes, sha256: spec.archive.sha256 });
    }
    const manifest = receipts.find(row => row.filename === spec.manifest.requested && row.sha256 === spec.manifest.sha256);
    assert(manifest && manifest.status === 200 && manifest.bytes === spec.manifest.bytes);
    const { view } = await readyView();
    const launcherState = await waitFor('the signed launcher status', () => {
      if (!existsSync(path.join(profile, 'launcher-update.json'))) return;
      const state = launcher();
      if (state.buildId === spec.launcherBuild && ['ready', 'current'].includes(state.status)) return state;
      if (state.buildId === spec.launcherBuild && state.status === 'failed') throw Error(state.error);
    });
    const restartMode = launcherState.status === 'ready' ? 'launcher-update' : 'unchanged-launcher';
    assert.equal(launcherState.restartRequired, restartMode === 'launcher-update');
    writeFileSync(stateFile, JSON.stringify({
      before, originalMemory, started, completed: Date.now(), beforePid: process.pid, archive, manifest, restartMode
    }));
    if (restartMode === 'unchanged-launcher') {
      verifyInstalledLauncher();
      event('reopened-unchanged-signed-launcher', { launcher: launcherState.buildId });
      app.relaunch();
      app.quit();
      return;
    }
    const button = await waitFor('the actual launcher restart button', () =>
      view.webContents.executeJavaScript(`(() => {
        const button = [...document.querySelectorAll('button')].find(node =>
          !node.disabled && node.textContent.trim() === '重新打开完成更新');
        if (!button) return null;
        const rect = button.getBoundingClientRect();
        if (!rect.width || !rect.height) return null;
        const x = Math.round(rect.x + rect.width / 2);
        const y = Math.round(rect.y + rect.height / 2);
        return button.contains(document.elementFromPoint(x, y)) ? { x, y } : null;
      })()`));
    event('clicked-restart-signed-launcher', { launcher: launcherState.buildId });
    view.webContents.focus();
    view.webContents.sendInputEvent({ type: 'mouseDown', ...button, button: 'left', clickCount: 1 });
    view.webContents.sendInputEvent({ type: 'mouseUp', ...button, button: 'left', clickCount: 1 });
    const until = Date.now() + 150000;
    while (Date.now() < until) {
      await pause(250);
      const state = launcher();
      if (state.status === 'failed') throw Error(state.error);
    }
    throw Error('The visible restart command did not close the original application');
  }
  assert.notEqual(process.pid, stage.beforePid);
  assert.deepEqual(active(), spec.selected);
  const installedLauncher = await waitFor('installed signed launcher', () => {
    if (!existsSync(path.join(profile, 'launcher-update.json'))) return;
    const state = launcher();
    if (state.status === 'current' && !state.restartRequired) return state;
  });
  assert.equal(installedLauncher.buildId, spec.launcherBuild);
  const descriptor = verifyInstalledLauncher();
  const macOS = process.platform === 'darwin';
  if (macOS) beforeView.window.setFullScreen(true);
  if (macOS) await waitFor('native fullscreen', () => beforeView.window.isFullScreen());
  const currentCheck = beforeView.view.webContents.executeJavaScript('window.kaixinDesktop.checkForUpdates()');
  await waitFor('the platform update progress view', () => {
    if (!macOS) return BrowserWindow.getAllWindows().some(window =>
      window.webContents.getURL().endsWith('/update-progress.html'));
    const inside = beforeView.window.contentView.children.find(child => child.webContents?.getURL().endsWith('/update-progress.html'));
    return inside && BrowserWindow.getAllWindows().length === 1 && beforeView.window.isFullScreen();
  }, 10000);
  event('progress-in-native-window');
  await currentCheck;
  assert(notices.some(notice => /已是最新版本|already.*up to date/i.test(notice.message)));
  assert.equal(BrowserWindow.getAllWindows().length, 1);
  if (macOS) assert(beforeView.window.isFullScreen());
  assert.equal(memoryHash(path.join(profile, 'workspace')), stage.originalMemory);
  const transaction = read(path.join(profile, 'upgrade.json'));
  assert.equal(transaction.phase, 'complete');
  assert.equal(memoryHash(transaction.backup), stage.originalMemory);
  writeFileSync(output, JSON.stringify({ passed: true, target: spec.target, reopened_pid: process.pid, source_commit: spec.selected.commit, from: stage.before.runtimeId, to: spec.selected.runtimeId, launcher_build: descriptor.buildId, launcher_files_verified: descriptor.files.length, signed_restart: true, restart_mode: stage.restartMode, platform_progress_window: true, fullscreen_retained_after_check: macOS, application_ipc_update: true, check_again_current: true, transaction_phase: transaction.phase, isolated_profile: true, learning_memory_sha256: stage.originalMemory, network: stage.archive, signed_manifest: stage.manifest, transfer_origin: spec.transferOrigin, disk_preflight: spec.diskPreflight, downloaded_and_switched_ms: stage.completed - stage.started, complete_ms: Date.now() - stage.started }, null, 2) + '\n');
  app.quit();
}

run().catch(error => {
  let runtimeId;
  try { runtimeId = active()?.runtimeId; } catch { /* Preserve the original failure. */ }
  const detail = { error: error.stack, notices, launcher_state: existsSync(path.join(profile, 'launcher-update.json')) ? launcher() : null, pid: process.pid, active: runtimeId, stage: stage ? 'new-launcher' : 'existing-launcher' };
  writeFileSync(`${output}.error.json`, JSON.stringify(detail, null, 2));
  app.exit(1);
});
