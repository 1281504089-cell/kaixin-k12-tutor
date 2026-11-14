import assert from 'node:assert/strict';
import test from 'node:test';
import { createUpdateFetch } from '../src/update-network.mjs';

test('the system-network session validates every redirect, omits credentials and initializes after readiness', async () => {
  let guard, sessions = 0;
  const calls = [];
  const fetch = createUpdateFetch({ fromPartition(name) {
    sessions++;
    assert.equal(name, 'kaixin-updates');
    return { webRequest: { onBeforeRequest(callback) { guard = callback; } },
      fetch: async (url, options) => { calls.push({ url, options }); return new Response('ok'); } };
  } });
  assert.equal(sessions, 0);
  await fetch(new URL('https://api.github.com/repos/1281504089-cell/kaixin-k12-tutor/releases/tags/core-updates'), { credentials: 'omit', redirect: 'manual' });
  await fetch(new URL('https://release-assets.githubusercontent.com/fixture'), { credentials: 'omit' });
  assert.equal(sessions, 1);
  assert.equal(calls[0].options.redirect, 'follow');
  assert.equal(calls[0].options.credentials, 'omit');
  for (const [url, cancel] of [
    ['https://release-assets.githubusercontent.com/fixture', false],
    ['https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/core-updates/fixture', false],
    ['https://example.org/redirect', true], ['http://github.com/unsafe', true],
    ['https://api.github.com/user', true], ['https://user@github.com/path', true],
  ]) {
    let result;
    guard({ url }, value => { result = value; });
    assert.equal(result.cancel, cancel, url);
  }
});

test('suspension recovery creates a fresh isolated network session with the same redirect guard', async () => {
  const names = [], guards = [];
  const fetch = createUpdateFetch({ fromPartition(name) {
    names.push(name);
    return { webRequest: { onBeforeRequest(callback) { guards.push(callback); } }, fetch: async () => new Response('ok') };
  } });
  await fetch('https://github.com/fixture');
  await fetch.recoverAfterSuspend();
  await fetch('https://github.com/fixture');
  assert.deepEqual(names, ['kaixin-updates', 'kaixin-updates-resumed-1']);
  let blocked;
  guards[1]({ url: 'https://example.org/redirect' }, value => { blocked = value.cancel; });
  assert.equal(blocked, true);
  const controller = new AbortController();
  controller.abort(new Error('user cancelled'));
  await assert.rejects(fetch.recoverAfterSuspend(controller.signal), /abort/i);
  await fetch('https://github.com/fixture');
  assert.equal(names.length, 2);
});
