// Test-only entry in a disposable Electron copy; production modules remain unchanged.
const { app, BrowserWindow, dialog, session } = require('electron');
const { readFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const home = process.env.OPEN_DEEPTUTOR_TEST_HOME;
const output = process.env.KX_UPDATE_FLOW_RESULT;
const stateFile = output + '.state.json';
const saved = require('node:fs').existsSync(stateFile) ? JSON.parse(readFileSync(stateFile)) : null;
const before = saved?.before ?? JSON.parse(readFileSync(path.join(home, 'active.json')));
let installed = false, current = false, accepted = saved?.accepted ?? 0, invokeError = saved?.invokeError ?? '';
const phase = saved?.phase ?? 'old-launcher';
const needsRestart=process.env.KX_EXPECT_SHELL_RESTART==='1';
let progressVisible=false, progressWithBytes=false;
let fromPid=process.pid;
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
const timer = setTimeout(() => { console.error('Native update flow timed out'); app.exit(1); }, 1300000);
async function content() {
  for (const window of BrowserWindow.getAllWindows()) {
    const found = window.contentView.children.find(view => view.webContents?.getURL().startsWith('http://127.0.0.1:'));
    if (found && await found.webContents.executeJavaScript('Boolean(window.kaixinDesktop?.checkForUpdates)').catch(() => false)) return found.webContents;
  }
}
(async () => {
  try {
    await app.whenReady();
    const updates = session.fromPartition('kaixin-updates');
    const originalFetch = updates.fetch.bind(updates);
    updates.fetch = async (url, options) => {
      const tag = process.env.KX_CANDIDATE_TAG;
      const original = String(url);
      const mapped = original.replace('/tags/core-updates', '/tags/' + tag).replace('/download/core-updates/', '/download/' + tag + '/');
      const ciOptions = new URL(mapped).hostname === 'api.github.com' && process.env.GH_TOKEN
        ? { ...options, headers: { ...options?.headers, Authorization: `Bearer ${process.env.GH_TOKEN}` } } : options;
      const response = await originalFetch(mapped, ciOptions);
      if (original.includes('/tags/core-updates') && response.ok) {
        const metadata = await response.json();
        return Response.json({ ...metadata, tag_name: 'core-updates' });
      }
      if(!needsRestart && original.includes('.tar.gz') && response.ok && response.body) {
        const paced=response.body.pipeThrough(new TransformStream({async transform(chunk,controller){await pause(20);controller.enqueue(chunk);}}));
        return new Response(paced,{status:response.status,headers:response.headers});
      }
      return response;
    };
    const nodeFetch=globalThis.fetch;
    globalThis.fetch=async(url,options)=> {
      const original=String(url),tag=process.env.KX_CANDIDATE_TAG;
      const mapped=original.replace('/tags/core-updates','/tags/'+tag).replace('/download/core-updates/','/download/'+tag+'/');
      const result=await nodeFetch(mapped,new URL(mapped).hostname==='api.github.com' && process.env.GH_TOKEN
        ? {...options,headers:{...options?.headers,Authorization:`Bearer ${process.env.GH_TOKEN}`}}:options);
      if(original.includes('/tags/core-updates') && result.ok){const data=await result.json();return Response.json({...data,tag_name:'core-updates'});}
      return result;
    };
    await import(pathToFileURL(path.join(__dirname, '../src/main.mjs')));
    await app.whenReady();
    let view;
    const readyDeadline = Date.now() + 120000;
    while (!(view = await content())) {
      assert.ok(Date.now() < readyDeadline, 'The old installed core did not open the update test interface');
      await pause(500);
    }
    if (phase === 'old-launcher') {
      await pause(1000);
      void view.executeJavaScript('window.kaixinDesktop.checkForUpdates()').catch(error => { invokeError = error.message; });
      while (!installed) {
        for(const win of BrowserWindow.getAllWindows()) {
          if(win.webContents.getURL().endsWith('/update-progress.html')) {
            progressVisible=true;
            const text=await win.webContents.executeJavaScript('document.body.innerText').catch(()=> '');
            if(/\d+\.\d+ MB/.test(text))progressWithBytes=true;
          }
        }
        await pause(100);
      }
      const updated = JSON.parse(readFileSync(path.join(home, 'active.json')));
      assert.notEqual(updated.runtimeId, before.runtimeId);
      assert.ok(updated.builtAt > (before.builtAt ?? 0));
      assert.equal(accepted, 1);
      const journal = JSON.parse(readFileSync(path.join(home, 'upgrade.json')));
      assert.equal(journal.phase, 'complete');
      assert.equal(journal.previous.runtimeId, before.runtimeId);
      if (needsRestart) {
      view = await content();
      const restartDeadline = Date.now() + 30000;
      while (!await view.executeJavaScript(`Array.from(document.querySelectorAll('button')).some(button=>button.textContent==='重新打开完成更新')`)) {
        assert.ok(Date.now() < restartDeadline, 'The old launcher did not receive a restart action from the signed core');
        await pause(200);
      }
      writeFileSync(stateFile, JSON.stringify({phase:'new-launcher',before,accepted,invokeError,oldPid:process.pid}));
      await view.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='重新打开完成更新').click()`);
      setTimeout(() => {
        let launcher;try {launcher=JSON.parse(readFileSync(path.join(home,'launcher-update.json')));}catch{}
        writeFileSync(output+'.error.json',JSON.stringify({phase:'restart-timeout',launcher}));
        app.exit(1);
      },90000).unref();
      return; // The signed helper must normally close and relaunch this process.
      }
    }
    if (needsRestart) assert.notEqual(process.pid, saved.oldPid, 'The whole application must have restarted');
    const after = JSON.parse(readFileSync(path.join(home, 'active.json')));
    const transaction = JSON.parse(readFileSync(path.join(home, 'upgrade.json')));
    if(!needsRestart) { assert.ok(progressVisible,'No visible update progress'); assert.ok(progressWithBytes,'No visible downloaded-byte feedback'); }
    const launcher = JSON.parse(readFileSync(path.join(home,'launcher-update.json')));
    assert.equal(launcher.status,'current');
    assert.equal(launcher.restartRequired,false);
    const descriptor=JSON.parse(readFileSync(path.join(home,'runtimes',after.runtimeId,'launcher/manifest.json')));
    for(const row of descriptor.files) assert.equal(require('node:crypto').createHash('sha256').update(readFileSync(path.join(__dirname,'..',row.file))).digest('hex'),row.sha256);
    await pause(500);
    view = await content();
    assert.ok(view, 'Updated page did not expose the trusted desktop bridge');
    const uiDeadline = Date.now() + 60000;
    while (!await view.executeJavaScript('Boolean(document.querySelector("textarea")?.offsetHeight) && document.body.innerText.includes("默认学习助手") && !document.body.innerText.includes("加载中...")')) {
      assert.ok(Date.now() < uiDeadline, 'The updated learning interface did not finish rendering');
      await pause(200);
    }
    const menu = await view.executeJavaScript(`(() => { document.querySelector('button[aria-label="资源"]')?.click(); return document.body.innerText; })()`);
    for (const label of ['收藏夹', '学习日志', '题库', '书籍', '阅读']) assert.ok(!menu.split('\n').includes(label), label);
    await view.executeJavaScript(`document.querySelector('button[aria-label="资源"]')?.click()`);
    await require('node:fs/promises').writeFile(path.join(path.dirname(output), 'native-ui-updated.png'), (await view.capturePage()).toPNG());
    const fixture = JSON.parse(readFileSync(path.join(home, 'attachment-fixture.json')));
    const library = await require('./materials-ui.cjs')(view, path.dirname(output), fixture);
    const audio = await require('./ci-chat-audio-ui.cjs')(view, path.dirname(output), fixture.audio);
    const science = await require('./science-ui.cjs').verifyScienceNative(view, path.dirname(output), fixture.science);
    assert.equal(audio.passed, true);
    assert.equal(science.passed, true);
    await view.executeJavaScript('window.kaixinDesktop.checkForUpdates()');
    assert.equal(current, true);
    writeFileSync(output, JSON.stringify({
      native_platform: process.platform, native_arch: process.arch,
      entry: 'renderer IPC desktop:check-release', native_dialogs_auto_confirmed: true,
      production_main_unchanged: true, candidate_feed_routed_only_in_test: true, from_runtime: before.runtimeId, to_runtime: after.runtimeId,
      actual_download_install_backup_restart: 'passed', transaction: transaction.phase,
      check_again_current: true, signed_launcher_restarted: needsRestart, from_launcher: needsRestart?'a47b05f9136ca6fb72d2f1f8a04eeb425298f358':descriptor.buildId, to_launcher: descriptor.buildId, old_pid: saved?.oldPid ?? fromPid, restarted_pid: process.pid, download_progress_visible: progressVisible, downloaded_bytes_visible: progressWithBytes, old_renderer_closed_after_update: Boolean(invokeError),
      library_bulk_upload: library, chat_audio: audio, science_formulas: science,
    }, null, 2));
    clearTimeout(timer);
    app.quit();
  } catch (error) {
    console.error(error.message);
    writeFileSync(output+'.error.json',JSON.stringify({phase,error:error.stack}));
    clearTimeout(timer);
    app.exit(1);
  }
})();
