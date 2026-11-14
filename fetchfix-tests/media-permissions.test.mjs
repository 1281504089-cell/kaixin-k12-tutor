import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';

// Exercise the installed handlers without starting Electron or opening real devices.
const source = await readFile(new URL('../src/main.mjs', import.meta.url), 'utf8');
const block = source.slice(source.indexOf("  const mac = process.platform === 'darwin';"), source.indexOf('  coreSession.setDisplayMediaRequestHandler'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

async function handlers(platform, grants = {}, saved = {}, approve = true) {
  const registered = {}, contents = {}, asked = [], writes = [];
  const state = { url: 'http://127.0.0.1:18802' };
  await new AsyncFunction('process', 'path', 'userRoot', 'readJSON', 'writeJSON', 'systemPreferences', 'coreSession', 'state', 'view', 'dialog', 'window', 't', block)(
    { platform }, path, '/private-test', async file => saved[path.basename(file)], async (file, value) => writes.push([path.basename(file), value]),
    { getMediaAccessStatus: device => grants[device] ?? 'denied', askForMediaAccess: async device => { asked.push(device); if (approve) grants[device] = 'granted'; return approve; } },
    { setPermissionCheckHandler: fn => { registered.check = fn; }, setPermissionRequestHandler: fn => { registered.request = fn; } },
    state, { webContents: contents }, { showMessageBox: async () => { asked.push('prompt'); return { response: approve ? 1 : 0 }; } }, {}, key => key,
  );
  const details = { requestingUrl: state.url + '/chat', isMainFrame: true };
  return { ...registered, contents, details, asked, writes };
}

test('an authorized camera remains visible to device enumeration only in the trusted main frame', async () => {
  const h = await handlers('darwin', { camera: 'granted', microphone: 'granted' });
  const check = overrides => h.check(h.contents, 'media', '', { ...h.details, mediaType: 'video', ...overrides });
  assert.equal(check({}), true);
  assert.equal(check({ isMainFrame: false }), false);
  assert.equal(check({ requestingUrl: 'https://example.org/chat' }), false);
  assert.equal(check({ mediaType: 'unknown' }), false);
  assert.equal(h.check({}, 'media', '', { ...h.details, mediaType: 'video' }), false);
  assert.deepEqual(h.asked, []);
});

test('camera consent is checked and requested separately from microphone consent', async () => {
  for (const approve of [true, false]) {
    const h = await handlers('darwin', { microphone: 'granted' }, {}, approve);
    const details = { ...h.details, mediaTypes: ['video'] };
    let allowed;
    await h.request(h.contents, 'media', value => { allowed = value; }, details);
    assert.equal(allowed, approve);
    assert.deepEqual(h.asked, ['camera']);
    assert.equal(h.check(h.contents, 'media', '', { ...h.details, mediaType: 'audio' }), true);
    if (approve) {
      await h.request(h.contents, 'media', value => { allowed = value; }, details);
      assert.deepEqual(h.asked, ['camera']);
    }
  }
});

test('non-Mac camera consent survives restart without granting microphone access', async () => {
  const first = await handlers('win32');
  await first.request(first.contents, 'media', allowed => assert.equal(allowed, true), { ...first.details, mediaTypes: ['video'] });
  assert.deepEqual(first.writes, [['camera-permission.json', true]]);
  const restored = await handlers('win32', {}, Object.fromEntries(first.writes));
  assert.equal(restored.check(restored.contents, 'media', '', { ...restored.details, mediaType: 'video' }), true);
  assert.equal(restored.check(restored.contents, 'media', '', { ...restored.details, mediaType: 'audio' }), false);
});
