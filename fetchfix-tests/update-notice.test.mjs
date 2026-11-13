import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const source = await readFile(new URL('../src/main.mjs', import.meta.url), 'utf8');
const stateBlock = source.slice(source.indexOf('function releaseSnapshot()'), source.indexOf('const t ='));
const checkBlock = source.slice(source.indexOf('function checkRelease('), source.indexOf('function buildMenu('));
function updater(next, { base = true, transaction = null } = {}) {
  const sent = [], dialogs = [], notices = [];
  const context = {
    busy:false, quitting:false, active:{ manifest:{runtimeId:'installed'} }, state:{phase:'ready'},
    availableRelease:undefined, releaseCheck:undefined, releaseRequest:undefined,
    findReleaseUpdate:async()=>next, updateFetch:()=>{}, publicKey:'public', targetId:()=> 'macos-x64',
    readJSON:async()=>transaction, access:async()=> { if (!base) throw new Error('missing'); },
    path, userRoot:'/isolated-preview', transactionFile:'upgrade.json', AbortController,
    updateNotice:async key=>notices.push(key),
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
  assert.equal(h.sent.length,1);
  assert.equal(h.sent[0].available,true);
  assert.equal(h.sent[0].runtimeId,'verified-next');
  assert.deepEqual(Object.keys(h.sent[0]).sort(),['available','runtimeId']);
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
