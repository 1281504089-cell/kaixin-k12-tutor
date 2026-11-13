// Test-only entry in a disposable Electron copy; production modules remain unchanged.
const { app, BrowserWindow, dialog } = require('electron');
const { readFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const home = process.env.OPEN_DEEPTUTOR_TEST_HOME;
const output = process.env.KX_UPDATE_FLOW_RESULT;
const before = JSON.parse(readFileSync(path.join(home, 'active.json')));
let installed = false, current = false, accepted = 0, invokeError = '';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
dialog.showMessageBox = async (...args) => {
  const options = args.at(-1);
  if (options.message === '发现开心动力超级学霸新版') {
    accepted++;
    return { response: 1 };
  }
  if (options.message === '更新已安装') installed = true;
  else if (options.message === '已是最新版本') current = true;
  else if (options.type === 'error' || options.type === 'warning') {
    throw new Error(options.message + ': ' + options.detail);
  }
  return { response: 0 };
};
dialog.showErrorBox = (title, detail) => { console.error(title + ': ' + detail); app.exit(1); };
const timer = setTimeout(() => { console.error('Native update flow timed out'); app.exit(1); }, 900000);
async function content() {
  for (const window of BrowserWindow.getAllWindows()) {
    const found = window.contentView.children.find(view => view.webContents?.getURL().startsWith('http://127.0.0.1:'));
    if (found && await found.webContents.executeJavaScript('Boolean(window.kaixinDesktop?.checkForUpdates)').catch(() => false)) return found.webContents;
  }
}
(async () => {
  try {
    await import(pathToFileURL(path.join(__dirname, 'main.mjs')));
    await app.whenReady();
    let view;
    while (!(view = await content())) await pause(500);
    void view.executeJavaScript('window.kaixinDesktop.checkForUpdates()').catch(error => { invokeError = error.message; });
    while (!installed) await pause(500);
    const after = JSON.parse(readFileSync(path.join(home, 'active.json')));
    assert.notEqual(after.runtimeId, before.runtimeId);
    assert.ok(after.builtAt > (before.builtAt ?? 0));
    assert.equal(accepted, 1);
    const transaction = JSON.parse(readFileSync(path.join(home, 'upgrade.json')));
    assert.equal(transaction.phase, 'complete');
    assert.equal(transaction.previous.runtimeId, before.runtimeId);
    await pause(500);
    view = await content();
    assert.ok(view, 'Updated page did not expose the trusted desktop bridge');
    await view.executeJavaScript('window.kaixinDesktop.checkForUpdates()');
    assert.equal(current, true);
    writeFileSync(output, JSON.stringify({
      native_platform: process.platform, native_arch: process.arch,
      entry: 'renderer IPC desktop:check-release', native_dialogs_auto_confirmed: true,
      production_main_unchanged: true, from_runtime: before.runtimeId, to_runtime: after.runtimeId,
      actual_download_install_backup_restart: 'passed', transaction: transaction.phase,
      check_again_current: true, old_renderer_closed_after_update: Boolean(invokeError),
    }, null, 2));
    clearTimeout(timer);
    app.quit();
  } catch (error) {
    console.error(error.message);
    clearTimeout(timer);
    app.exit(1);
  }
})();
