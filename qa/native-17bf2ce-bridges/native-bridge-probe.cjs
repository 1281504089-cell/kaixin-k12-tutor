const assert = require('node:assert/strict');
const { readFileSync, writeFileSync } = require('node:fs');
const { join, resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const { setTimeout: pause } = require('node:timers/promises');
const { app, BrowserWindow } = require('electron');

async function run() {
  const home = process.env.OPEN_DEEPTUTOR_TEST_HOME;
  const output = process.env.KX_BRIDGE_EVIDENCE;
  assert(home && output);
  const manifest = JSON.parse(readFileSync(resolve(__dirname, '../seed/runtime.json')));
  const descriptor = JSON.parse(readFileSync(resolve(__dirname, 'manifest.json')));
  await import(pathToFileURL(join(__dirname, 'src/entry.mjs')));
  await app.whenReady();
  const deadline = Date.now() + 850_000;
  while (Date.now() < deadline) {
    for (const window of BrowserWindow.getAllWindows()) {
      const view = window.contentView.children.find(child => /^http:\/\/127\.0\.0\.1:\d+\//.test(child.webContents?.getURL() || ''));
      if (!view || !window.isVisible()) continue;
      const contents = view.webContents;
      const renderer = await contents.executeJavaScript(`Boolean(
        document.body?.innerText.trim() && window.kaixinDesktop?.checkForUpdates
      )`).catch(() => false);
      if (!renderer) continue;
      const origin = new URL(contents.getURL()).origin;
      const language = await fetch(origin + '/api/settings/ui', {signal: AbortSignal.timeout(8_000)}).then(response => response.json());
      assert.equal(language.language, 'zh');
      assert.deepEqual(JSON.parse(readFileSync(join(home, 'active.json'))), manifest);
      assert.equal(manifest.arch, process.arch);
      const launcher = JSON.parse(readFileSync(join(home, 'launcher-update.json')));
      assert.equal(launcher.buildId, descriptor.buildId);
      assert.equal(launcher.status, 'current');
      const png = (await contents.capturePage()).toPNG();
      assert(png.length > 1_000, 'The learning window screenshot is empty');
      writeFileSync(join(output, 'bridge-window.png'), png);
      writeFileSync(join(output, 'bridge-window.json'), JSON.stringify({
        native_window: true, learning_renderer: true, update_control: true,
        boot_commit: manifest.commit, bridge_sha256: manifest.sha256,
        core_sha256: manifest.corePayloadSha256, runtime: manifest.runtimeId,
        platform: process.platform, arch: process.arch, electron: process.versions.electron,
        launcher: launcher.buildId, selected_view: new URL(contents.getURL()).pathname,
      }, null, 2) + '\n');
      app.quit();
      return;
    }
    await pause(350);
  }
  throw new Error('Learning renderer did not open in a native visible window');
}
run().catch(error => { console.error(error); app.exit(1); });
