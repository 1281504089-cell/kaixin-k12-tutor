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
let checkAttempts=saved?.check_attempts??0, currentCheckAttempts=saved?.current_check_attempts??0;
const readOnlyRetries=saved?.read_only_retry_reasons??[];
const phase = saved?.phase ?? 'old-launcher';
let stage=phase, downloadStarted=saved?.download_started??false, initialUpgrade, lastTransportError;
const needsRestart=process.env.KX_EXPECT_SHELL_RESTART==='1';
let progressVisible=saved?.download_progress_visible??false, progressWithBytes=saved?.downloaded_bytes_visible??false;
let fromPid=process.pid;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function optionalRead(name) {
  try { return readFileSync(path.join(home,name),'utf8'); } catch(error) { if(error.code==='ENOENT')return null;throw error; }
}
function connectionTimeout(error) {
  const chain=[];for(let item=error;item&&chain.length<5;item=item.cause)chain.push(item);
  if(chain.some(item=>/signature|checksum|验签|签名|校验|ENOSPC|EACCES|EPERM/i.test(String(item.message||item)+' '+String(item.code||''))))return null;
  for(const item of chain) {
    const message=String(item.message||item).replace(/^Error invoking remote method 'desktop:check-release': (?:Error: )?/,'').replace(/^Error: /,'');
    if(item.code==='UND_ERR_CONNECT_TIMEOUT')return item.code;
    if((item.code==='ETIMEDOUT'&&item.syscall==='connect')||/^connect ETIMEDOUT\b/.test(message))return 'connect ETIMEDOUT';
    if(['net::ERR_CONNECTION_TIMED_OUT','GitHub update connection timed out','核心更新未完成: GitHub update connection timed out'].includes(message))return message;
  }
  return null;
}
async function checkedFetch(fetch,url,options) {
  const tracked=['github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'].includes(new URL(url).hostname);
  if(/\.tar\.gz$/.test(new URL(url).pathname))downloadStarted=true;
  try {const response=await fetch(url,options);if(tracked)lastTransportError=null;return response;}
  catch(error){if(tracked)lastTransportError={attempt:checkAttempts,url:new URL(url).origin+new URL(url).pathname,error};throw error;}
}
function flowState() {
  return {check_attempts:checkAttempts,current_check_attempts:currentCheckAttempts,read_only_retry_reasons:readOnlyRetries,download_started:downloadStarted,download_progress_visible:progressVisible,downloaded_bytes_visible:progressWithBytes};
}
function fail(error, failedStage=stage) {
  console.error(error.message||error);
  let launcher,active,tail,differences=[];
  try {launcher=JSON.parse(optionalRead('launcher-update.json'));} catch {}
  try {active=JSON.parse(optionalRead('active.json'));} catch {}
  try {tail=optionalRead('logs/runtime.log')?.slice(-18000);} catch {}
  try {
    const d=JSON.parse(readFileSync(path.join(home,'runtimes',active.runtimeId,'launcher/manifest.json')));
    for(const row of d.files) {
      let actual;try {actual=require('node:crypto').createHash('sha256').update(readFileSync(path.join(__dirname,'..',row.file))).digest('hex');}catch(e){actual=e.message;}
      if(actual!==row.sha256)differences.push({file:row.file,expected:row.sha256,actual});
    }
  } catch(e) {console.error('Evidence collection:',e.message);}
  try {writeFileSync(output+'.error.json',JSON.stringify({phase,stage:failedStage,error:String(error.stack||error),accepted,installed,current,before_runtime:before.runtimeId,invokeError,...flowState(),launcher,active:active??null,tail,differences,transport_error:lastTransportError?{attempt:lastTransportError.attempt,url:lastTransportError.url,error:String(lastTransportError.error.stack||lastTransportError.error)}:null}));}
  finally {clearTimeout(timer);app.exit(1);}
}
async function collectProgress() {
  for(const win of BrowserWindow.getAllWindows())if(win.webContents.getURL().endsWith('/update-progress.html')) {
    progressVisible=true;downloadStarted=true;
    const text=await win.webContents.executeJavaScript('document.body.innerText').catch(()=> '');
    if(/\d+\.\d+ MB/.test(text))progressWithBytes=true;
  }
}
async function runCheck(view, expectCurrent=false) {
  for(;;) {
    checkAttempts++;if(expectCurrent)currentCheckAttempts++;
    stage=expectCurrent?'check-current':'check-install';lastTransportError=null;
    let error,done=false;
    void Promise.resolve().then(()=>view.executeJavaScript('window.kaixinDesktop.checkForUpdates()')).then(()=>{done=true;},value=>{error=value||new Error('Update check rejected without an error detail');invokeError=String(error.message||error);done=true;});
    for(;;) {
      await collectProgress();
      if(error) {
        const active=JSON.parse(readFileSync(path.join(home,'active.json'))),journal=JSON.parse(optionalRead('upgrade.json'));
        // A real install disposes its old renderer before its IPC can resolve.
        const replacing=!expectCurrent&&accepted===1&&invokeError==='Render frame was disposed before the request completed'&&optionalRead('upgrade.json')!==initialUpgrade&&journal?.previous?.runtimeId===before.runtimeId&&typeof journal?.candidate?.runtimeId==='string'&&journal.candidate.runtimeId.length>0&&journal.candidate.runtimeId!==before.runtimeId&&['testing','complete'].includes(journal.phase);
        if(replacing) {if(installed) return;stage='await-installed-after-renderer-close';await pause(100);continue;}
        let status,reason=connectionTimeout(error);
        if(!expectCurrent&&reason&&accepted===0&&!installed&&!current&&!downloadStarted&&!progressVisible&&readOnlyRetries.length===0&&active.runtimeId===before.runtimeId&&optionalRead('upgrade.json')===initialUpgrade) {
          try {status=await view.executeJavaScript('window.kaixinDesktop.getUpdateStatus()');}catch{}
          if(status?.available===false&&status.runtimeId===''&&[undefined,'idle'].includes(status.phase)&&[undefined,0].includes(status.received)&&[undefined,0].includes(status.total)&&accepted===0&&!installed&&!current&&!downloadStarted&&!progressVisible&&JSON.parse(readFileSync(path.join(home,'active.json'))).runtimeId===before.runtimeId&&optionalRead('upgrade.json')===initialUpgrade) {
            readOnlyRetries.push({attempt:checkAttempts,reason,invoke_error:invokeError,accepted,active_runtime_id:active.runtimeId,download_started:false,update_status:status});break;
          }
        }
        throw error;
      }
      if(done) {assert(expectCurrent?current:installed,expectCurrent?'Current-version check returned without confirmation':'Update check returned without an installed update');return;}
      await pause(100);
    }
  }
}
dialog.showMessageBox = async (...args) => {
  const options = args.at(-1);
  if (options.message === '发现开心动力超级学霸新版') {
    accepted++;
    return { response: 1 };
  }
  if (options.message === '更新已安装') installed = true;
  else if (options.message === '已是最新版本') current = true;
  else if (options.type === 'error' || options.type === 'warning') {
    throw new Error(options.message + ': ' + options.detail, {cause:lastTransportError?.attempt===checkAttempts?lastTransportError.error:undefined});
  }
  return { response: 0 };
};
dialog.showErrorBox = (title, detail) => fail(new Error(title + ': ' + detail),'native-error-box');
const timer = setTimeout(() => fail(new Error('Native update flow timed out')), 1300000);
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
      const response = await checkedFetch(originalFetch,mapped,ciOptions);
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
      const result=await checkedFetch(nodeFetch,mapped,new URL(mapped).hostname==='api.github.com' && process.env.GH_TOKEN
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
      initialUpgrade=optionalRead('upgrade.json');
      await runCheck(view);
      stage='validate-installed';
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
      stage='await-signed-restart';
      writeFileSync(stateFile, JSON.stringify({phase:'new-launcher',before,accepted,invokeError,oldPid:process.pid,...flowState()}));
      await view.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='重新打开完成更新').click()`);
      setTimeout(() => {
        fail(new Error('The signed launcher did not reopen'),'restart-timeout');
      },90000).unref();
      return; // The signed helper must normally close and relaunch this process.
      }
    }
    stage='verify-new-launcher';
    if (needsRestart) assert.notEqual(process.pid, saved.oldPid, 'The whole application must have restarted');
    const after = JSON.parse(readFileSync(path.join(home, 'active.json')));
    const transaction = JSON.parse(readFileSync(path.join(home, 'upgrade.json')));
    if(!needsRestart) { assert.ok(progressVisible,'No visible update progress'); assert.ok(progressWithBytes,'No visible downloaded-byte feedback'); }
    const launcherDeadline = Date.now()+30000;
    let launcher;
    do {
      launcher = JSON.parse(readFileSync(path.join(home,'launcher-update.json')));
      if(launcher.status==='current') break;
      assert.ok(Date.now()<launcherDeadline, 'Launcher did not become current: '+JSON.stringify(launcher));
      await pause(200);
    } while(true);
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
    stage='ui-checks';
    const fixture = JSON.parse(readFileSync(path.join(home, 'attachment-fixture.json')));
    const library = await require('./materials-ui.cjs')(view, path.dirname(output), fixture);
    const audio = await require('./ci-chat-audio-ui.cjs')(view, path.dirname(output), fixture.audio);
    const science = await require('./science-ui.cjs').verifyScienceNative(view, path.dirname(output), fixture.science);
    const preview = await require('./ci-turn-preview.cjs')(view, path.dirname(output), fixture.science.preview);
    const k12 = await require('./ci-k12-library-ui.cjs')(view, path.dirname(output), fixture.k12, { entry: path.basename(output, '.json') });
    assert.equal(k12.passed, true);
    assert.equal(preview.passed, true);
    assert.equal(audio.passed, true);
    assert.equal(science.passed, true);
    await runCheck(view,true);
    assert.equal(current, true);
    writeFileSync(output, JSON.stringify({
      native_platform: process.platform, native_arch: process.arch,
      ...flowState(),
      entry: 'renderer IPC desktop:check-release', native_dialogs_auto_confirmed: true,
      production_main_unchanged: true, candidate_feed_routed_only_in_test: true, from_runtime: before.runtimeId, to_runtime: after.runtimeId,
      actual_download_install_backup_restart: 'passed', transaction: transaction.phase,
      check_again_current: true, signed_launcher_restarted: needsRestart, from_launcher: process.env.KX_START_LAUNCHER_BUILD??(needsRestart?'a47b05f9136ca6fb72d2f1f8a04eeb425298f358':descriptor.buildId), to_launcher: descriptor.buildId, old_pid: saved?.oldPid ?? fromPid, restarted_pid: process.pid, download_progress_visible: progressVisible, downloaded_bytes_visible: progressWithBytes, old_renderer_closed_after_update: invokeError==='Render frame was disposed before the request completed', selected_archive:after.archive, selected_base_runtime:after.baseRuntimeId??null,
      library_bulk_upload: library, chat_audio: audio, science_formulas: science, quick_preview: preview, k12_library: k12,
    }, null, 2));
    clearTimeout(timer);
    app.quit();
  } catch (error) {
    fail(error);
  }
})();
