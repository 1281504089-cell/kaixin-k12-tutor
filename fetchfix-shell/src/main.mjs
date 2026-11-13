import { app, BrowserWindow, WebContentsView, Menu, ipcMain, shell, dialog, session, nativeTheme, desktopCapturer, systemPreferences, net } from 'electron';
import { fork } from 'node:child_process';
import { watch } from 'node:fs';
import { mkdir, readFile, writeFile, rename, appendFile, mkdtemp, rm, access } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { installBundle, bundleConfig, bundledRelease, verifyManifest, shouldUseBundledUpdate } from './bundles.mjs';
import { externalURL } from './config.mjs';
import { resolveLanguage, translate } from './i18n.mjs';
import { WINDOWS, agentMarker, edition, targetId } from './platform.mjs';
import { killTree } from './processes.mjs';
import { snapshotWorkspace } from './workspace-snapshot.mjs';
import { findReleaseUpdate, downloadReleaseUpdate } from './release-updates.mjs';

app.setName('开心动力超级学霸');
if (WINDOWS) app.setAppUserModelId('org.kaixindongli.super-scholar');
const EDITION = edition();
const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));
const shellURL = pathToFileURL(path.join(sourceDirectory, 'index.html')).href;
// Runtimes are large and machine-specific, so Windows keeps them out of the roaming profile.
const userRoot = process.env.OPEN_DEEPTUTOR_TEST_HOME
  || path.join(WINDOWS ? process.env.LOCALAPPDATA ?? app.getPath('appData') : app.getPath('appData'), '开心动力超级学霸');
app.setPath('userData', userRoot);
const runtimeHome = path.join(userRoot, 'workspace');
const logPath = path.join(userRoot, 'logs/runtime.log');
const activeFile = path.join(userRoot, 'active.json');
const transactionFile = path.join(userRoot, 'upgrade.json');
// DeepTutor's own Settings page writes the interface language and theme here.
const interfaceFile = path.join(runtimeHome, 'data/user/settings/interface.json');
const seed = app.isPackaged ? path.join(process.resourcesPath, 'seed/runtime.json') : path.join(sourceDirectory, '../.local', targetId(), 'seed/runtime.json');
const publicKey = await readFile(path.join(sourceDirectory, '../assets/runtime-public.pem'), 'utf8');
// Chromium follows the same system proxy/PAC settings as the desktop browser.
const updateFetch = (url, options) => net.fetch(String(url), options);
// macOS draws the shell's own title bar under the traffic lights; Windows keeps its native frame and menu bar.
const HEADER_HEIGHT = WINDOWS ? 0 : 44;
const BACKGROUND = { light: '#ffffff', dark: '#161618' };
let window;
let view;
let worker;
let state = { phase: 'starting', step: 'opening' };
let ui = { language: 'zh', theme: 'light' };
let interfaceWatcher;
let interfaceTimer;
let busy = false;
let quitting = false;
let exitAllowed = false;
let active;
let releaseRequest;
let releaseCheck;
let releaseCheckScheduled = false;
let availableRelease;

function releaseSnapshot() {
  return { available: Boolean(availableRelease), runtimeId: availableRelease?.runtimeId ?? '' };
}

function publishRelease(next) {
  availableRelease = next;
  if (view && !view.webContents.isDestroyed()) view.webContents.send('desktop:release-status', releaseSnapshot());
}

const t = (key, values) => translate(ui.language, key, values);

async function writeJSON(file, data) {
  await mkdir(path.dirname(file), { recursive: true, mode: 0o700 });
  await writeFile(`${file}.tmp`, JSON.stringify(data, null, 2), { mode: 0o600 });
  await rename(`${file}.tmp`, file);
}

async function readJSON(file) {
  try { return JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

function coreVersion() {
  return active?.manifest.coreVersion ?? app.getVersion();
}

/** What the shell page shows, already in the user's language. */
function snapshot() {
  const failed = state.phase === 'error';
  return {
    phase: state.phase, theme: ui.theme, language: ui.language,
    connection: state.phase === 'ready' && state.health === 'unresponsive' ? t('connectionBusy') : '',
    title: failed ? t('errorTitle') : state.phase === 'stopped' ? t('stoppedTitle') : '',
    message: failed ? t('errorBody') : state.step ? t(state.step) : '',
    detail: failed ? state.message ?? '' : '',
    tagline: t('tagline'), retry: t('retry'), logs: t('logs'),
    edition: `${EDITION.full} v${coreVersion()}`,
  };
}

function publish() {
  if (window && !window.isDestroyed()) {
    const next = snapshot();
    window.setTitle(next.connection ? `开心动力超级学霸 · ${next.connection}` : '开心动力超级学霸');
    window.webContents.send('desktop:status', next);
  }
}

function status(next) {
  state = { ...state, ...next };
  publish();
  if (next.phase && next.phase !== 'ready') hideContent();
}

async function readInterface() {
  let saved;
  try { saved = await readJSON(interfaceFile) ?? {}; }
  catch { return ui; } // A half-written or hand-edited file keeps the current choice.
  const dark = saved.theme === 'dark' || (saved.theme === 'system' && nativeTheme.shouldUseDarkColors);
  return { language: resolveLanguage(saved.language), theme: dark ? 'dark' : 'light' };
}

async function refreshInterface() {
  const next = await readInterface();
  if (next.language === ui.language && next.theme === ui.theme) return;
  ui = next;
  buildMenu();
  window?.setBackgroundColor(BACKGROUND[ui.theme]);
  publish();
}

function watchInterface() {
  if (interfaceWatcher) return;
  try {
    // Settings are replaced atomically, so watch the folder rather than the file.
    interfaceWatcher = watch(path.dirname(interfaceFile), () => {
      clearTimeout(interfaceTimer);
      interfaceTimer = setTimeout(() => void refreshInterface(), 150);
    });
    interfaceWatcher.on('error', () => { interfaceWatcher?.close(); interfaceWatcher = undefined; });
  } catch { /* The folder appears after the core's first init; boot() tries again. */ }
}

function hideContent() {
  if (!view) return;
  window?.contentView.removeChildView(view);
  view.webContents.close();
  view = undefined;
}

function layout() {
  if (!view || !window) return;
  const bounds = window.getContentBounds();
  view.setBounds({ x: 0, y: HEADER_HEIGHT, width: bounds.width, height: Math.max(1, bounds.height - HEADER_HEIGHT) });
}

async function openContent(url) {
  hideContent();
  const origin = new URL(url).origin;
  view = new WebContentsView({ webPreferences: {
    contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true,
    partition: 'persist:deeptutor', preload: path.join(sourceDirectory, 'update-bridge.cjs'),
  } });
  const content = view.webContents;
  content.setWindowOpenHandler(({ url: target }) => {
    if (target.startsWith(origin + '/') || target.startsWith(`blob:${origin}/`)) {
      return { action: 'allow', overrideBrowserWindowOptions: {
        webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true },
      } };
    }
    if (externalURL(target)) void shell.openExternal(target);
    return { action: 'deny' };
  });
  const restrict = (event, target) => {
    if (new URL(target).origin !== origin) {
      event.preventDefault();
      if (externalURL(target)) void shell.openExternal(target);
    }
  };
  content.on('will-navigate', restrict);
  content.on('will-redirect', restrict);
  content.on('will-attach-webview', event => event.preventDefault());
  content.on('render-process-gone', () => status({ phase: 'error', step: null, message: t('pageGone') }));
  window.contentView.addChildView(view);
  layout();
  await content.loadURL(url);
}

function trustedShell(event) {
  if (event.sender !== window?.webContents || event.senderFrame !== window.webContents.mainFrame
    || event.senderFrame.url !== shellURL) throw new Error('Untrusted desktop IPC caller');
}

async function stopWorker() {
  const previous = worker;
  worker = undefined;
  if (!previous || previous.exitCode !== null) return;
  await new Promise(resolve => {
    // Windows cannot signal the worker, so a stuck worker is ended with its services.
    const force = () => { if (WINDOWS) killTree(previous.pid); else previous.kill('SIGTERM'); };
    const timer = setTimeout(force, 12000);
    previous.once('exit', () => { clearTimeout(timer); resolve(); });
    if (previous.connected) previous.send({ type: 'stop' });
    else force();
  });
}

async function launchRuntime(installed) {
  const config = bundleConfig(installed.destination, runtimeHome, installed.manifest.runtimeId, installed.manifest.baseRuntimeId);
  const child = fork(path.join(sourceDirectory, 'supervisor.mjs'), [], {
    execPath: config.nodePath, stdio: ['ignore', 'ignore', 'pipe', 'ipc'],
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '',
      DEEPTUTOR_ELECTRON_EXECUTABLE: process.execPath,
      DEEPTUTOR_ELECTRON_PROBE: path.join(sourceDirectory, 'lesson-browser.cjs'),
    },
  });
  worker = child;
  child.stderr.on('data', chunk => console.error(chunk.toString()));
  return new Promise((resolve, reject) => {
    let ready = false;
    child.on('message', next => {
      if (worker !== child || quitting) return;
      status(next);
      if (next.phase === 'ready' && !ready) { ready = true; resolve(next); }
      if (next.phase === 'error' && !ready) reject(new Error(next.message));
    });
    child.once('error', reject);
    child.once('exit', code => {
      if (worker !== child || quitting) return;
      status({ phase: 'error', step: null, message: t('workerExited', { code }) });
      if (!ready) reject(new Error(state.message));
    });
    child.send({ type: 'start', config, logPath, cachePath: path.join(userRoot, 'cache', installed.manifest.runtimeId) });
  });
}

async function recoverInterruptedUpgrade() {
  const transaction = await readJSON(transactionFile);
  if (!transaction || transaction.phase !== 'testing') return;
  status({ phase: 'starting', step: 'recovering' });
  if (transaction.backup) {
    try { await rename(runtimeHome, `${runtimeHome}.interrupted-${Date.now()}`); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    await snapshotWorkspace(transaction.backup, runtimeHome);
  }
  await writeJSON(activeFile, transaction.previous);
  await writeJSON(transactionFile, { ...transaction, phase: 'recovered' });
}

async function prepareUpgrade(next, previous) {
  const backup = path.join(userRoot, 'backups', `before-${next.manifest.runtimeId}-${Date.now()}`);
  await mkdir(path.dirname(backup), { recursive: true, mode: 0o700 });
  await snapshotWorkspace(runtimeHome, backup);
  const transaction = { phase: 'testing', previous, candidate: next.manifest, backup };
  await writeJSON(transactionFile, transaction);
  return transaction;
}

async function logStartupFailure(error) {
  // Bundle extraction can fail before the supervisor creates the runtime log.
  console.error(error);
  try {
    await mkdir(path.dirname(logPath), { recursive: true });
    await appendFile(logPath, `\nDesktop startup failed: ${error.stack ?? error}\n`);
  } catch (logError) { console.error(logError); }
}

async function boot() {
  if (busy || quitting) return;
  busy = true;
  let transaction;
  try {
    status({ phase: 'starting', step: 'starting' });
    await stopWorker();
    await recoverInterruptedUpgrade();
    const savedJSON = await readJSON(activeFile);
    const saved = savedJSON ? verifyManifest(savedJSON, publicKey) : null;
    const bundled = await bundledRelease(seed, publicKey);
    const update = shouldUseBundledUpdate(saved, bundled.manifest, await readJSON(transactionFile));
    const manifestFile = saved && !update ? path.join(userRoot, 'runtimes', saved.runtimeId, 'installed.json') : bundled.file;
    if (manifestFile === bundled.file && bundled.baseFile) {
      await installBundle(bundled.baseFile, userRoot, publicKey, step => status({ step }));
    }
    active = await installBundle(manifestFile, userRoot, publicKey, step => status({ step }));
    if (quitting) return;
    if (update) {
      status({ phase: 'starting', step: 'updating' });
      transaction = await prepareUpgrade(active, saved);
    }
    const ready = await launchRuntime(active);
    if (quitting) return;
    await writeJSON(activeFile, active.manifest);
    if (transaction) await writeJSON(transactionFile, { ...transaction, phase: 'complete' });
    watchInterface();
    await refreshInterface();
    await openContent(ready.url);
    if (app.isPackaged && !releaseCheckScheduled) {
      releaseCheckScheduled = true;
      setTimeout(() => void checkRelease(false), 15000).unref();
      setInterval(() => void checkRelease(false), 4 * 60 * 60 * 1000).unref();
    }
  } catch (error) {
    await logStartupFailure(error);
    status({ phase: 'error', step: null, message: error.message });
    await stopWorker();
    if (transaction && !quitting) {
      await recoverInterruptedUpgrade();
      await dialog.showMessageBox(window, { type: 'error', message: t('updateFailed'), detail: error.message, buttons: [t('reopen')] });
      busy = false;
      await boot();
    }
  } finally { busy = false; }
}

async function applyCoreUpdate(file) {
  const next = await installBundle(file, userRoot, publicKey);
  if (next.manifest.runtimeId === active.manifest.runtimeId) return;
  let transaction;
  try {
    status({ phase: 'starting', step: 'updating' });
    await stopWorker();
    transaction = await prepareUpgrade(next, active.manifest);
    const ready = await launchRuntime(next);
    await openContent(ready.url);
    await writeJSON(activeFile, next.manifest);
    await writeJSON(transactionFile, { ...transaction, phase: 'complete' });
    active = next;
    publishRelease(null);
    buildMenu();
    publish();
  } catch (error) {
    await stopWorker();
    if (transaction) await recoverInterruptedUpgrade();
    busy = false;
    await boot();
    throw error;
  }
}

async function updateNotice(key, detail = '', type = 'info') {
  if (!quitting && window && !window.isDestroyed()) {
    await dialog.showMessageBox(window, { type, message: t(key), detail });
  }
}

async function installUpdate() {
  if (busy || quitting || !active) return;
  busy = true;
  try {
    const choice = await dialog.showOpenDialog(window, { title: t('updateTitle'), properties: ['openFile'], filters: [{ name: t('updateFilter'), extensions: ['json'] }] });
    if (choice.canceled) return;
    const confirmation = await dialog.showMessageBox(window, {
      type: 'question', buttons: [t('cancel'), t('updateConfirm')], defaultId: 0, cancelId: 0,
      message: t('updateMessage'), detail: t('updateDetail'),
    });
    if (confirmation.response === 1) await applyCoreUpdate(choice.filePaths[0]);
  } catch (error) {
    await updateNotice('updateFailed', error.message, 'error');
  } finally {
    busy = false;
  }
}

function checkRelease(interactive = true) {
  if (releaseCheck) {
    if (interactive) releaseCheck.interactive = true;
    return releaseCheck.promise;
  }
  const check = { interactive };
  releaseCheck = check;
  check.promise = performReleaseCheck(check).finally(() => { releaseCheck = undefined; });
  return check.promise;
}

async function performReleaseCheck(check) {
  if (busy || quitting || !active || state.phase !== 'ready') {
    if (check.interactive) await updateNotice('releaseBusy');
    return;
  }
  busy = true;
  const request = new AbortController();
  releaseRequest = request;
  let temporary;
  let downloading = false;
  try {
    const next = await findReleaseUpdate(targetId(), active.manifest, publicKey, updateFetch, request.signal);
    if (!next) {
      publishRelease(null);
      if (check.interactive) await updateNotice('releaseCurrent');
      return;
    }
    if (!check.interactive) {
      const transaction = await readJSON(transactionFile);
      if (!check.interactive && transaction?.phase === 'recovered' && transaction.candidate?.runtimeId === next.runtimeId) {
        publishRelease(null);
        return;
      }
    }
    if (next.baseRuntimeId) {
      const base = path.join(userRoot, 'runtimes', next.baseRuntimeId, 'installed.json');
      const present = await access(base).then(() => true, () => false);
      if (!present) {
        publishRelease(null);
        if (check.interactive) await updateNotice('releaseBaseMissing');
        return;
      }
    }
    if (quitting) return;
    publishRelease(next);
    if (!check.interactive) return;
    const confirmation = await dialog.showMessageBox(window, {
      type: 'info', message: t('releaseAvailable'), detail: t('releaseDetail', { build: next.runtimeId }),
      buttons: [t('cancel'), t('releaseInstall')], defaultId: 0, cancelId: 0,
    });
    if (confirmation.response !== 1 || quitting) return;
    downloading = true;
    temporary = await mkdtemp(path.join(userRoot, 'release-'));
    window.setProgressBar(2);
    const file = await downloadReleaseUpdate(next, temporary, progress => {
      if (!window.isDestroyed()) window.setProgressBar(progress);
    }, updateFetch, request.signal);
    if (quitting) return;
    await applyCoreUpdate(file);
    await updateNotice('releaseInstalled', next.runtimeId);
  } catch (error) {
    if (downloading) {
      await updateNotice('updateFailed', error.message, 'error');
    } else if (check.interactive) {
      console.warn('GitHub update check failed', error);
      await updateNotice('releaseCheckFailed', t('releaseCheckRetry'), 'warning');
    }
  } finally {
    if (window && !window.isDestroyed()) window.setProgressBar(-1);
    if (temporary) await rm(temporary, { recursive: true, force: true }).catch(() => {});
    releaseRequest = undefined;
    busy = false;
  }
}

function buildMenu() {
  const about = { label: t('about'), click: () => dialog.showMessageBox(window, {
    message: `${EDITION.full} v${coreVersion()}`,
    detail: t('aboutDetail', { core: active?.manifest.coreVersion ?? '—', runtime: active?.manifest.runtimeId ?? '—' }),
  }) };
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: '开心动力超级学霸', submenu: WINDOWS ? [about, { type: 'separator' }, { role: 'quit', label: t('quit') }] : [
      about,
      { label: t('checkRelease'), click: () => void checkRelease() },
      { type: 'separator' },
      { role: 'hide', label: t('hide') }, { role: 'hideOthers', label: t('hideOthers') }, { role: 'unhide', label: t('showAll') },
      { type: 'separator' },
      { role: 'quit', label: t('quit') },
    ] },
    { label: t('edit'), submenu: [
      { role: 'undo', label: t('undo') }, { role: 'redo', label: t('redo') }, { type: 'separator' },
      { role: 'cut', label: t('cut') }, { role: 'copy', label: t('copy') }, { role: 'paste', label: t('paste') },
      { role: 'selectAll', label: t('selectAll') },
    ] },
    { label: t('view'), submenu: [
      { label: t('reload'), accelerator: 'CmdOrCtrl+R', click: () => view?.webContents.reload() },
      { type: 'separator' },
      { label: t('actualSize'), accelerator: 'CmdOrCtrl+0', click: () => view?.webContents.setZoomLevel(0) },
      { label: t('zoomIn'), accelerator: 'CmdOrCtrl+Plus', click: () => view?.webContents.setZoomLevel(view.webContents.getZoomLevel() + 0.5) },
      { label: t('zoomOut'), accelerator: 'CmdOrCtrl+-', click: () => view?.webContents.setZoomLevel(view.webContents.getZoomLevel() - 0.5) },
      { type: 'separator' },
      { role: 'togglefullscreen', label: t('fullscreen') },
    ] },
    { label: t('core'), submenu: [
      { label: t('restartCore'), click: async () => {
        const choice = await dialog.showMessageBox(window, { message: t('restartConfirm'), buttons: [t('cancel'), t('restart')], defaultId: 0, cancelId: 0 });
        if (choice.response === 1) void boot();
      } },
      { label: t('checkRelease'), click: () => void checkRelease() },
      { label: t('installUpdate'), click: () => void installUpdate() }, { type: 'separator' },
      { label: t('openData'), click: () => void shell.openPath(runtimeHome) },
      { label: t('openLogs'), click: () => void shell.openPath(path.dirname(logPath)) },
    ] },
    { role: 'windowMenu', label: t('window'), submenu: WINDOWS ? [{ role: 'minimize', label: t('minimize') }] : [
      { role: 'minimize', label: t('minimize') }, { role: 'zoom', label: t('zoom') },
      { type: 'separator' }, { role: 'front', label: t('front') },
    ] },
  ]));
}

if (!app.requestSingleInstanceLock()) { app.quit(); }
else {
  app.on('second-instance', () => { window?.show(); window?.focus(); });
  app.on('before-quit', event => {
    if (exitAllowed) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    releaseRequest?.abort();
    status({ phase: 'stopping', step: 'stopping' });
    void stopWorker().finally(() => { exitAllowed = true; app.quit(); });
  });
  app.on('window-all-closed', () => app.quit());
  // Electron waits for ESM evaluation before emitting ready; do not await ready
  // at module scope or the packaged application deadlocks before its first window.
  app.whenReady().then(async () => {
  ui = await readInterface();
  nativeTheme.on('updated', () => void refreshInterface());
  const coreSession = session.fromPartition('persist:deeptutor');
  // The web UI reads this marker to name the client, e.g. "开心动力超级学霸（Mac · Apple 芯片）".
  coreSession.setUserAgent(`${coreSession.getUserAgent()} ${agentMarker(app.getVersion())}`);
  const mac = process.platform === 'darwin';
  const microphoneFile = path.join(userRoot, 'microphone-permission.json');
  let microphoneAllowed = !mac && (await readJSON(microphoneFile).catch(() => false)) === true;
  let microphoneRequest;
  const cameraFile = path.join(userRoot, 'camera-permission.json');
  let cameraAllowed = !mac && (await readJSON(cameraFile).catch(() => false)) === true;
  let cameraRequest;
  const trustedMedia = (contents, details) => Boolean(state.url && contents === view?.webContents &&
    details.isMainFrame && details.requestingUrl?.startsWith(state.url + '/'));
  const hasMicrophonePermission = () => mac
    ? systemPreferences.getMediaAccessStatus('microphone') === 'granted'
    : microphoneAllowed;
  const hasCameraPermission = () => mac
    ? systemPreferences.getMediaAccessStatus('camera') === 'granted'
    : cameraAllowed;
  const confirmMedia = async (message, detail = '') => {
    const result = await dialog.showMessageBox(window, {
      type: 'question', message, detail, buttons: [t('deny'), t('allow')], defaultId: 0, cancelId: 0,
    });
    return result.response === 1;
  };
  const requestMicrophone = async () => {
    if (mac) return systemPreferences.askForMediaAccess('microphone');
    if (!await confirmMedia(t('microphonePrompt'), t('microphoneRemember'))) return false;
    microphoneAllowed = true;
    await writeJSON(microphoneFile, true).catch(error => console.warn('Could not save microphone permission', error));
    return true;
  };
  const requestCamera = async () => {
    if (mac) return systemPreferences.askForMediaAccess('camera');
    if (!await confirmMedia(t('mediaPrompt'))) return false;
    cameraAllowed = true;
    await writeJSON(cameraFile, true).catch(error => console.warn('Could not save camera permission', error));
    return true;
  };
  coreSession.setPermissionCheckHandler((contents, permission, _origin, details) =>
    permission === 'clipboard-sanitized-write' || (permission === 'media' && trustedMedia(contents, details) &&
      (details.mediaType === 'audio' ? hasMicrophonePermission() : details.mediaType === 'video' && hasCameraPermission())));
  coreSession.setPermissionRequestHandler(async (contents, permission, callback, details) => {
    if (permission === 'clipboard-sanitized-write') return callback(true);
    if (!trustedMedia(contents, details)) return callback(false);
    if (permission === 'display-capture') {
      return callback(details.mediaTypes?.length === 1 && details.mediaTypes[0] === 'video');
    }
    if (permission !== 'media') return callback(false);
    let allowed = false;
    try {
      if (details.mediaTypes?.length === 1 && details.mediaTypes[0] === 'audio') {
        allowed = hasMicrophonePermission();
        if (!allowed) {
          microphoneRequest ??= requestMicrophone().finally(() => { microphoneRequest = undefined; });
          allowed = await microphoneRequest;
        }
      } else if (details.mediaTypes?.length === 1 && details.mediaTypes[0] === 'video') {
        allowed = hasCameraPermission();
        if (!allowed) {
          cameraRequest ??= requestCamera().finally(() => { cameraRequest = undefined; });
          allowed = await cameraRequest;
        }
      } else {
        allowed = await confirmMedia(t('mediaPrompt'));
      }
    } catch (error) {
      console.warn('Could not request media permission', error);
    }
    callback(allowed && trustedMedia(contents, details));
  });
  coreSession.setDisplayMediaRequestHandler(async (request, callback) => {
    // Electron serializes the requesting origin with a trailing slash.
    const trusted = () => Boolean(state.url && URL.canParse(request.securityOrigin) &&
      new URL(request.securityOrigin).origin === state.url &&
      request.frame && request.frame === view?.webContents.mainFrame);
    let selected = null;
    if (request.userGesture && request.videoRequested && !request.audioRequested && trusted()) {
      try {
        const sources = mac && systemPreferences.getMediaAccessStatus('screen') === 'denied' ? [] :
          await desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 0, height: 0 } })
            .catch(error => {
              if (mac && systemPreferences.getMediaAccessStatus('screen') !== 'granted') return [];
              throw error;
            });
        if (trusted() && window && !window.isDestroyed() && !sources.length) {
          if (mac && systemPreferences.getMediaAccessStatus('screen') !== 'granted') {
            const result = await dialog.showMessageBox(window, {
              type: 'info', message: t('chooseShareScope'), detail: t('screenPermissionHelp'),
              buttons: [t('shareTutorPage'), t('openScreenSettings'), t('cancel')], defaultId: 0, cancelId: 2,
            });
            if (result.response === 0) {
              selected = request.frame;
            } else if (result.response === 1) {
              await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture');
            }
          } else {
            await dialog.showMessageBox(window, { type: 'info', message: t('screenSourcesUnavailable') });
          }
        } else if (sources.length && trusted() && window && !window.isDestroyed()) {
          const menu = Menu.buildFromTemplate([
            { label: t('chooseDisplaySource'), enabled: false },
            { type: 'separator' },
            ...sources.map(source => ({ label: source.name, click: () => { selected = source; } })),
            { type: 'separator' },
            { label: t('deny') },
          ]);
          await new Promise(resolve => menu.popup({ window, callback: () => setImmediate(resolve) }));
        }
      } catch (error) {
        await logStartupFailure(new Error('Unable to open the screen-sharing picker', { cause: error }));
        if (trusted() && window && !window.isDestroyed()) {
          await dialog.showMessageBox(window, { type: 'info', message: t('screenSourcesUnavailable') }).catch(() => {});
        }
      }
    }
    try {
      callback(selected && trusted() ? { video: selected } : null);
    } catch {
      // The requesting frame may have closed while its picker was open.
    }
  });
  window = new BrowserWindow({
    title: '开心动力超级学霸', width: 1360, height: 920, minWidth: 900, minHeight: 620,
    backgroundColor: BACKGROUND[ui.theme],
    ...(WINDOWS ? { icon: path.join(sourceDirectory, '../assets/icon.ico') } : { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 18, y: 16 } }),
    webPreferences: { preload: path.join(sourceDirectory, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.on('resize', layout);
  window.on('close', event => { if (!exitAllowed) { event.preventDefault(); app.quit(); } });
  for (const [channel, handler] of Object.entries({
    status: () => snapshot(),
    restart: () => { void boot(); },
    logs: async () => { await mkdir(path.dirname(logPath), { recursive: true }); await shell.openPath(path.dirname(logPath)); },
  })) ipcMain.handle(`desktop:${channel}`, (event, ...args) => { trustedShell(event); return handler(...args); });
  const trustedUpdateCaller = event => {
    if (!view || event.sender !== view.webContents || event.senderFrame !== view.webContents.mainFrame
      || !state.url || new URL(event.senderFrame.url).origin !== state.url) {
      throw new Error('Untrusted desktop update caller');
    }
  };
  ipcMain.handle('desktop:get-release-status', event => {
    trustedUpdateCaller(event);
    return releaseSnapshot();
  });
  ipcMain.handle('desktop:check-release', async event => {
    trustedUpdateCaller(event);
    await checkRelease();
  });
  buildMenu();
  watchInterface();
  await window.loadURL(shellURL);
  void boot();
  }).catch(async error => {
    await logStartupFailure(error);
    dialog.showErrorBox('开心动力超级学霸', error.message);
    exitAllowed = true;
    app.quit();
  });
}
