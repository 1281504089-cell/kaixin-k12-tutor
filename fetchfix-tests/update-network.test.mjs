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
