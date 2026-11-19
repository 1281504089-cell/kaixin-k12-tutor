import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import { isInterruptedDownload } from '../src/release-updates.mjs';

const source = await readFile(new URL('../src/main.mjs', import.meta.url), 'utf8');
const stateBlock = source.slice(source.indexOf('function releaseSnapshot()'), source.indexOf('const t ='));
const checkBlock = source.slice(source.indexOf('function checkRelease('), source.indexOf('function buildMenu('));
function updater(next, { base = true, transaction = null } = {}) {
  const sent = [], dialogs = [], notices = [];
  const context = {
    busy:false, quitting:false, active:{ manifest:{runtimeId:'installed'} }, state:{phase:'ready'},
    availableRelease:undefined, releaseCheck:undefined, releaseRequest:undefined,
    releaseProgress:{phase:'idle',received:0,total:0,canCancel:false}, progressWindow:undefined,
    sourceDirectory:'/isolated-preview/src', pathToFileURL: value=>({href:`file://${value}`}),
    logPath:'/isolated-preview/runtime.log', mkdir:async()=>{}, appendFile:async()=>{},
    BrowserWindow:class {
      constructor() { this.webContents={send(){},setWindowOpenHandler(){},on(){}}; }
      isDestroyed(){return false;} show(){} focus(){} hide(){} destroy(){} on(){}
      loadFile(){return Promise.resolve();}
    },
    findReleaseUpdate:async()=>next, updateFetch:()=>{}, publicKey:'public', targetId:()=> 'macos-x64',
    readJSON:async()=>transaction, access:async()=> { if (!base) throw new Error('missing'); },
    path, userRoot:'/isolated-preview', transactionFile:'upgrade.json', AbortController,
    updateNotice:async key=>notices.push(key),
    isInterruptedDownload,
    view:{ webContents:{ isDestroyed:()=>false, send:(_channel,payload)=>sent.push(payload) } },
    window:{ isDestroyed:()=>false, setProgressBar:()=>{} },
    dialog:{ showMessageBox:async(_window,options)=> { dialogs.push(options); return {response:0}; } },
    t:key=>key,
  };
  runInNewContext(stateBlock+checkBlock,context);
  return {context,sent,dialogs,notices};
}

test('background detection notifies the avatar without opening an install dialog', async () => {
  const h = updater({runtimeId:'verified-next',signature:'not-sent-to-renderer'});
  await h.context.checkRelease(false);
  const advertised = h.sent.find(status=>status.available);
  assert.equal(advertised.runtimeId,'verified-next');
  assert.deepEqual(Object.keys(advertised).sort(),['available','canCancel','phase','received','runtimeId','total']);
  assert.equal(h.dialogs.length,0);
  assert.equal(h.context.busy,false);
  await h.context.checkRelease(true);
  assert.equal(h.dialogs.length,1);
  assert.equal(h.dialogs[0].message,'releaseAvailable');
  assert.equal(h.context.releaseSnapshot().available,true);
});

test('current, missing-base and recovered updates never advertise an unusable update', async () => {
  for (const h of [updater(null),updater({runtimeId:'next',baseRuntimeId:'base'},{base:false}),
    updater({runtimeId:'next'},{transaction:{phase:'recovered',candidate:{runtimeId:'next'}}})]) {
    await h.context.checkRelease(false);
    assert.equal(h.context.releaseSnapshot().available,false);
    assert.equal(h.dialogs.length,0);
  }
});

test('confirmed updates prevent idle suspension only until download and installation finish', async () => {
  for (const fail of [false, true]) {
    const h = updater({ runtimeId: 'next' });
    const events = [];
    Object.assign(h.context, {
      powerSaveBlocker: { start(type) { events.push(type); return 0; }, stop(id) { events.push(['stop', id]); } },
      mkdtemp: async () => '/isolated-preview/download', rm: async () => { events.push('cleanup'); },
      downloadReleaseUpdate: async () => {
        events.push('download');
        if (fail) throw new Error('net::ERR_NETWORK_IO_SUSPENDED');
        return '/isolated-preview/download/runtime.json';
      },
      applyCoreUpdate: async () => { events.push('install'); },
      isNetworkSuspended: error => error.message.includes('ERR_NETWORK_IO_SUSPENDED'),
    });
    h.context.dialog.showMessageBox = async () => ({ response: 1 });
    h.context.updateNotice = async (...values) => { events.push(values); };
    await h.context.checkRelease(true);
    assert.equal(events[0], 'prevent-app-suspension');
    const released = events.findIndex(value => Array.isArray(value) && value[0] === 'stop');
    const notified = events.findIndex(value => Array.isArray(value) && value[0] === (fail ? 'updateFailed' : 'releaseInstalled'));
    assert.ok(released > 0 && released < notified);
    assert.equal(events[notified][1], fail ? 'releaseSuspended' : 'next');
    assert.equal(events.at(-1), 'cleanup');
    assert.equal(h.context.busy, false);
  }
});

test('an interrupted download has a readable notice and stage log without starting installation', async () => {
  for (const stage of ['downloading', 'installing']) {
    const h = updater({ runtimeId: 'next' });
    const events = [], logs = [];
    const error = new TypeError('terminated', { cause: Object.assign(new Error('socket closed'), { code: 'UND_ERR_SOCKET' }) });
    Object.assign(h.context, {
      powerSaveBlocker: { start() { return 0; }, stop() {} },
      mkdtemp: async () => '/isolated-preview/download', rm: async () => { events.push('cleanup'); },
      appendFile: async (_path, text) => logs.push(text),
      downloadReleaseUpdate: async () => {
        if (stage === 'downloading') throw error;
        return '/isolated-preview/download/runtime.json';
      },
      applyCoreUpdate: async () => { events.push('install'); throw error; },
      isNetworkSuspended: () => false,
      updateNotice: async (...values) => events.push(values),
    });
    h.context.dialog.showMessageBox = async () => ({ response: 1 });
    await h.context.checkRelease(true);
    assert.deepEqual(events.find(Array.isArray), ['updateFailed', stage === 'downloading' ? 'releaseInterrupted' : 'terminated', 'error']);
    assert.equal(events.includes('install'), stage === 'installing');
    assert.match(logs[0], new RegExp(`failed \\[${stage}\\]: terminated \\(UND_ERR_SOCKET\\)`));
    assert.equal(events.at(-1), 'cleanup');
    assert.equal(h.context.active.manifest.runtimeId, 'installed');
    assert.equal(h.context.busy, false);
  }
});

test('the preload sends only status data and removes subscriptions', async () => {
  let bridge, handler, removed;
  const invoked = [];
  runInNewContext(await readFile(new URL('../src/update-bridge.cjs',import.meta.url),'utf8'),{
    require:()=>({contextBridge:{exposeInMainWorld:(_name,value)=>{bridge=value;}},ipcRenderer:{
      invoke:async channel=>{ invoked.push(channel); return {available:false,runtimeId:''}; },
      on:(_channel,fn)=>{handler=fn;}, removeListener:(_channel,fn)=>{removed=fn;},
    }}),
  });
  let received;
  const dispose = bridge.onUpdateStatus(status=>{received=status;});
  const payload={available:true,runtimeId:'next'};
  handler({secret:'electron-event'},payload);
  assert.equal(received,payload);
  dispose();
  assert.equal(removed,handler);
  await bridge.getUpdateStatus();
  await bridge.checkForUpdates();
  assert.deepEqual(invoked,['desktop:get-release-status','desktop:check-release']);
});

test('both update IPC handlers reject foreign frames and windows', () => {
  const handlers={};
  const frame={url:'http://127.0.0.1:18802/chat'};
  const contents={mainFrame:frame};
  const start=source.indexOf('  const trustedUpdateCaller =');
  const end=source.indexOf('  buildMenu();',start);
  runInNewContext(source.slice(start,end),{
    view:{webContents:contents},state:{url:'http://127.0.0.1:18802'},URL,
    ipcMain:{handle:(name,fn)=>{handlers[name]=fn;}},
    releaseSnapshot:()=>({available:false}),checkRelease:async()=>{},
  });
  const valid={sender:contents,senderFrame:frame};
  assert.equal(handlers['desktop:get-release-status'](valid).available,false);
  assert.throws(()=>handlers['desktop:get-release-status']({...valid,sender:{}}),/Untrusted/);
  assert.throws(()=>handlers['desktop:get-release-status']({...valid,senderFrame:{url:frame.url}}),/Untrusted/);
  frame.url='https://example.org/';
  assert.throws(()=>handlers['desktop:get-release-status'](valid),/Untrusted/);
});

test('the native Mac and Windows menus and Settings invoke the same interactive updater', async () => {
  const menuStart = source.indexOf('function buildMenu(');
  const menuSource = source.slice(menuStart, source.indexOf('if (!app.requestSingleInstanceLock()', menuStart));
  const ipcStart = source.indexOf('  const trustedUpdateCaller =');
  const ipcSource = source.slice(ipcStart, source.indexOf('  buildMenu();', ipcStart));
  for (const entry of ['Mac menu', 'Windows menu', 'Settings']) {
    const h = updater({ runtimeId: 'next' });
    const frame = { url: 'http://127.0.0.1:18802/chat' };
    const contents = h.context.view.webContents;
    contents.mainFrame = frame;
    h.context.state.url = new URL(frame.url).origin;
    let menu;
    const handlers = {};
    Object.assign(h.context, {
      WINDOWS: entry === 'Windows menu', URL,
      Menu: { buildFromTemplate: template => template, setApplicationMenu: template => { menu = template; } },
      ipcMain: { handle: (channel, handler) => { handlers[channel] = handler; } },
    });
    runInNewContext(menuSource + ipcSource, h.context);
    h.context.buildMenu();
    if (entry === 'Settings') {
      const event = { sender: contents, senderFrame: frame };
      await handlers['desktop:check-release'](event);
    } else {
      menu.flatMap(item => item.submenu).find(item => item.label === 'checkRelease').click();
      await h.context.releaseCheck.promise;
    }
    assert.equal(h.dialogs[0]?.message, 'releaseAvailable', entry);
  }
});

test('reopening the local learning page after suspension retries once without clearing its partition', async () => {
  const block = source.slice(source.indexOf('async function openContent('), source.indexOf('function trustedShell('));
  for (const mode of ['resume', 'persistent', 'other-error', 'quit']) {
    let calls = 0, waits = 0;
    const error = new Error(mode === 'other-error' ? 'net::ERR_CONNECTION_REFUSED' : 'net::ERR_NETWORK_IO_SUSPENDED');
    const context = { URL, path, sourceDirectory: '/preview', quitting: false,
      hideContent() {}, layout() {}, status() {}, window: { contentView: { addChildView() {} } },
      isNetworkSuspended: value => value.message.includes('ERR_NETWORK_IO_SUSPENDED'),
      delay: async () => { waits++; if (mode === 'quit') context.quitting = true; },
      WebContentsView: class {
        constructor(options) {
          assert.equal(options.webPreferences.partition, 'persist:deeptutor');
          this.webContents = { setWindowOpenHandler() {}, on() {}, loadURL: async () => {
            calls++;
            if (mode !== 'resume' || calls === 1) throw error;
          } };
        }
      },
    };
    runInNewContext(block, context);
    if (mode === 'resume') await context.openContent('http://127.0.0.1:18762');
    else await assert.rejects(context.openContent('http://127.0.0.1:18762'), value => value === error);
    assert.equal(calls, ['resume', 'persistent'].includes(mode) ? 2 : 1);
    assert.equal(waits, mode === 'other-error' ? 0 : 1);
  }
});

 test('cancelled downloads never install or retry and leave the entry reusable', async()=> {
  const h=updater({runtimeId:'next'});
  const events=[];
  Object.assign(h.context,{
    powerSaveBlocker:{start:()=>0,stop:()=>events.push('released')},
    mkdtemp:async()=>'/isolated-preview/download',rm:async()=>events.push('cleanup'),
    downloadReleaseUpdate:async(_manifest,_directory,onProgress,_fetch,signal)=> {
      onProgress(.5,{received:50,total:100});
      h.context.releaseRequest.abort(new Error('Update cancelled'));
      signal.throwIfAborted();
    },
    applyCoreUpdate:async()=>events.push('installed'),
  });
  h.context.dialog.showMessageBox=async()=>({response:1});
  await h.context.checkRelease(true);
  assert.equal(h.context.releaseSnapshot().phase,'cancelled');
  assert.ok(h.sent.some(status=>status.received===50 && status.total===100));
  assert.deepEqual(events,['released','cleanup']);
  assert.equal(h.context.busy,false);
  assert.equal(h.context.releaseCheck,undefined);
 });
