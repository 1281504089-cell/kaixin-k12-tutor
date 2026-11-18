import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

// Exercise the production shutdown function without starting Electron or a learner profile.
test('shutdown recognizes signal-ended workers and still waits for live workers', async t => {
  const source = await readFile(new URL('../src/main.mjs', import.meta.url), 'utf8');
  const body = source.slice(source.indexOf('async function stopWorker()'), source.indexOf('async function launchRuntime('));
  assert.ok(body.startsWith('async function stopWorker()'));
  const timers = new Set(), children = [];
  t.after(() => { for (const timer of timers) clearTimeout(timer); for (const child of children) if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
  const stopping = child => new Function('worker', 'WINDOWS', 'killTree', 'setTimeout', 'clearTimeout', body + ';return stopWorker();')(
    child, process.platform === 'win32', pid => process.kill(pid),
    (fn, ms) => { const timer = setTimeout(fn, ms); timers.add(timer); return timer; }, clearTimeout);
  const bounded = promise => Promise.race([promise, new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('Shutdown still awaits an already ended worker')), 2000); timers.add(timer); })]);
  const ended = spawn(process.execPath, ['-e', 'process.exit(0)'], { stdio: 'ignore' }); children.push(ended);
  await once(ended, 'exit'); await bounded(stopping(ended));
  const signalled = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { stdio: 'ignore' }); children.push(signalled);
  await once(signalled, 'spawn'); const exit = once(signalled, 'exit'); signalled.kill('SIGTERM'); await exit;
  assert.equal(signalled.exitCode, null); assert.equal(signalled.signalCode, 'SIGTERM');
  await bounded(stopping(signalled));
  const live = spawn(process.execPath, ['-e', 'process.on("message", message => { if (message.type === "stop") process.send("stopping"); if (message.type === "release") process.exit(0); });setInterval(()=>{},1000);'], { stdio: ['ignore', 'ignore', 'ignore', 'ipc'] }); children.push(live);
  await once(live, 'spawn'); const endedLive = once(live, 'exit');
  const acknowledged = once(live, 'message');
  let settled = false;
  const waiting = stopping(live).then(() => { settled = true; });
  assert.equal((await bounded(acknowledged))[0], 'stopping');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false);
  assert.equal(live.exitCode, null); assert.equal(live.signalCode, null);
  live.send({ type: 'release' });
  await bounded(waiting); await endedLive;
  assert.equal(live.exitCode, 0);
});
