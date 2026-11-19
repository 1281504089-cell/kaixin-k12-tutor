import assert from 'node:assert/strict';
import test from 'node:test';
import { createUpdateFetch } from '../src/update-network.mjs';
import { updateMirrorBase } from '../src/release-updates.mjs';

test('the signed launcher uses the dedicated Shanghai COS release directory', async () => {
  const directory = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/';
  const url = directory + 'runtime-macos-x64.json';
  assert.equal(updateMirrorBase().href, directory);
  let guard;
  const fetch = createUpdateFetch({ fromPartition() {
    return {
      webRequest: { onBeforeRequest(handler) { guard = handler; } },
      fetch: async (requested, options) => {
        assert.equal(requested, url);
        assert.equal(options.redirect, 'error');
        return new Response('ok');
      },
    };
  } });
  await fetch(url);
  for (const [requested, cancel] of [[url, false], [url.replace('/desktop/', '/pilot-k12-11/'), true]]) {
    guard({ url: requested }, result => assert.equal(result.cancel, cancel));
  }
});

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

test('the desktop session pins the mirror directory and refuses mirror redirects', async () => {
  const mirror = 'https://updates.example.test/desktop/';
  let guard;
  const options = [];
  const fetch = createUpdateFetch({ fromPartition() {
    return { webRequest: { onBeforeRequest(callback) { guard = callback; } },
      fetch: async (_url, init) => { options.push(init); return new Response('ok'); } };
  } }, mirror);
  await fetch(new URL('runtime-macos-x64.json', mirror), { credentials: 'omit', redirect: 'error' });
  await fetch('https://github.com/fixture', { credentials: 'omit', redirect: 'manual' });
  assert.deepEqual(options.map(item => [item.redirect, item.credentials]), [['error', 'omit'], ['follow', 'omit']]);
  for (const [url, cancel] of [
    [mirror + 'runtime-macos-x64.json', false],
    [mirror + 'kaixin-core-fixture.tar.gz', false],
    [mirror + 'archive/nested.tar.gz', true],
    [mirror + 'runtime-macos-x64.json?v=1', true],
    ['https://updates.example.test/private/other.json', true],
    ['https://account@updates.example.test/desktop/test.json', true],
    ['https://updates.example.test.untrusted.test/desktop/test.json', true],
    ['http://updates.example.test/desktop/test.json', true],
  ]) {
    let result;
    guard({ url }, value => { result = value; });
    assert.equal(result.cancel, cancel, url);
  }
  for (const invalid of ['http://updates.example.test/desktop/', 'https://updates.example.test/', mirror + '?key=value']) {
    assert.throws(() => createUpdateFetch({}, invalid), /Invalid desktop update mirror directory/);
  }
});
