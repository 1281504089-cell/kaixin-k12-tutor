const assert = require('node:assert/strict');
const { mkdtemp, readdir, readFile, rm } = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { loadInitialLibrary } = require('./ci-materials-ui.cjs');
const target = 'http://127.0.0.1:18802/space?dt_workspace=';
const changed = (url = target) => Object.assign(new Error(`ERR_NETWORK_CHANGED (-21) loading '${url}'`), { code: 'ERR_NETWORK_CHANGED', errno: -21, url });
async function run(name, { origin = 'http://127.0.0.1:18802/chat', errors = [], count, status }) {
  const evidence = await mkdtemp(path.join(os.tmpdir(), 'kaixin-navigation-'));
  let calls = 0;
  const view = { getURL: () => origin, loadURL: async url => {
    calls++;
    assert.equal(url, new URL('/space?dt_workspace=', origin).href);
    if (calls === 2) {
      const files = await readdir(evidence);
      assert.equal(files.length, 1);
      const first = JSON.parse(await readFile(path.join(evidence, files[0]), 'utf8'));
      assert.equal(first.status, 'retry_scheduled');
      assert.equal(first.retry_count, 0);
      assert.equal(first.first_error.errno, -21);
    }
    if (errors[calls - 1]) throw errors[calls - 1];
    return 'loaded';
  } };
  try {
    if (status === 'failed' || status === 'retry_failed') await assert.rejects(loadInitialLibrary(view, evidence), error => error === errors.at(-1));
    else assert.equal(await loadInitialLibrary(view, evidence), 'loaded');
    assert.equal(calls, count);
    const files = await readdir(evidence);
    if (!status) assert.equal(files.length, 0);
    else {
      assert.equal(files.length, 1);
      const receipt = JSON.parse(await readFile(path.join(evidence, files[0]), 'utf8'));
      assert.equal(receipt.status, status);
      assert.equal(receipt.retry_count, count - 1);
      assert.equal(receipt.first_error.message, errors[0].message);
      if (status === 'retry_failed') assert.equal(receipt.retry_error.message, errors[1].message);
    }
    console.log('PASS ' + name);
  } finally { await rm(evidence, { recursive: true, force: true }); }
}
(async () => {
  await run('initial success has no retry', { count: 1 });
  await run('exact -21 retries once and records success', { errors: [changed()], count: 2, status: 'retry_succeeded' });
  await run('persistent -21 stops after two calls', { errors: [changed(), changed()], count: 2, status: 'retry_failed' });
  await run('other error is preserved without retry', { errors: [Object.assign(new Error('ERR_CONNECTION_REFUSED'), { code: 'ERR_CONNECTION_REFUSED', errno: -102, url: target })], count: 1, status: 'failed' });
  await run('non-loopback is never retried', { origin: 'https://example.com/chat', errors: [changed('https://example.com/space?dt_workspace=')], count: 1, status: 'failed' });
  await run('different error URL is never retried', { errors: [changed(target + 'different')], count: 1, status: 'failed' });
})().catch(error => { console.error(error); process.exitCode = 1; });
