import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { bundleConfig, canonicalManifest, installBundle } from '../src/bundles.mjs';
import { systemTar, runtimeLayout, targetId } from '../src/platform.mjs';
import { downloadReleaseUpdate, findReleaseUpdate, isInterruptedDownload } from '../src/release-updates.mjs';
import { createUpdateFetch } from '../src/update-network.mjs';

const { publicKey, privateKey } = generateKeyPairSync('ed25519');
const current = { runtimeId: 'student-base', builtAt: 100 };
function signed(values = {}) {
  const result = { formatVersion: 1, protocolVersion: 1, arch: process.arch, platform: process.platform,
    runtimeId: 'student-update', coreVersion: '1.7.1', builtAt: 200, archive: 'patch.tar.gz',
    sha256: '0'.repeat(64), ...values };
  result.signature = sign(null, Buffer.from(canonicalManifest(result)), privateKey).toString('base64');
  return result;
}

test('GitHub feed only offers newer, verified updates for this machine', async () => {
  const check = response => findReleaseUpdate(targetId(), current, publicKey, async url => {
    if (url.hostname === "api.github.com") return Response.json({ tag_name: "core-updates", draft: false, assets: [] });
    assert.match(url.pathname, /\/core-updates\/runtime-.+\.json$/);
    return response;
  });
  assert.equal((await check(Response.json(signed()))).runtimeId, 'student-update');
  assert.equal(await check(Response.json(signed({ builtAt: 99 }))), null);
  await assert.rejects(check(new Response('', { status: 404 })), /HTTP 404/);
  await assert.rejects(check(Response.json(signed({ arch: 'bad' }))), /not compatible/);
  const tampered = signed();
  tampered.builtAt += 1;
  await assert.rejects(check(Response.json(tampered)), /signature/);
  await assert.rejects(check(Response.redirect('https://example.org/invalid')), /Invalid GitHub/);
});

test('the manifest uses the GitHub API first and archive HTTP 504 falls back to the API', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-release-fallback-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const manifestName = `runtime-${targetId()}.json`;
  const archiveBytes = Buffer.from('fixture archive');
  const manifest = signed({ sha256: createHash('sha256').update(archiveBytes).digest('hex') });
  const served = [];
  async function github(url, options) {
    if (url.hostname === 'github.com') return new Response(null, { status: 504 });
    assert.equal(options.credentials, 'omit');
    if (url.pathname.endsWith('/tags/core-updates')) {
      return Response.json({ tag_name: 'core-updates', draft: false, assets: [
        { name: manifestName, state: 'uploaded', id: 11, url: 'https://example.org/untrusted' },
        { name: manifest.archive, state: 'uploaded', id: 12 },
      ] });
    }
    if (url.hostname === 'api.github.com') {
      assert.equal(options.headers.Accept, 'application/octet-stream');
      if (url.pathname.endsWith('/assets/11')) {
        served.push(11);
        return Response.json(manifest);
      }
      assert.match(url.pathname, /\/assets\/12$/);
      served.push(12);
      return Response.redirect('https://release-assets.githubusercontent.com/fixture');
    }
    assert.equal(url.hostname, 'release-assets.githubusercontent.com');
    assert.equal(options.headers, undefined);
    return new Response(archiveBytes);
  }
  const next = await findReleaseUpdate(targetId(), current, publicKey, github);
  assert.equal(next.runtimeId, manifest.runtimeId);
  await downloadReleaseUpdate(next, root, () => {}, github);
  assert.deepEqual(await readFile(path.join(root, manifest.archive)), archiveBytes);
  assert.deepEqual(served, [11, 12]);
});

test('a stalled manifest route leaves time to verify the installed version on the other route', async t => {
  const installed = signed(current);
  const requests = [];
  const apiDeadline = new AbortController();
  const directDeadline = new AbortController();
  t.mock.method(AbortSignal, 'timeout', () => requests.length ? directDeadline.signal : apiDeadline.signal);
  const result = await findReleaseUpdate(targetId(), installed, publicKey, async (url, { signal }) => {
    requests.push(url.hostname);
    if (url.hostname === 'api.github.com') {
      return new Promise((_, reject) => {
        signal.addEventListener('abort', () => reject(signal.reason), { once: true });
        queueMicrotask(() => apiDeadline.abort(new DOMException('Timed out', 'TimeoutError')));
      });
    }
    assert.equal(signal.aborted, false);
    return Response.json(installed);
  });
  assert.equal(result, null);
  assert.deepEqual(requests, ['api.github.com', 'github.com']);
});

test('connection, interrupted-body and checksum failures retry the public API without retaining a partial archive', async t => {
  const bytes = Buffer.from('the complete signed archive');
  const manifest = signed({ sha256: createHash('sha256').update(bytes).digest('hex') });
  for (const failure of ['connection', 'body', 'length', 'checksum']) {
    const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-download-retry-'));
    t.after(() => rm(root, { recursive: true, force: true }));
    let apiDownloads = 0;
    const github = async url => {
      if (url.hostname === 'github.com') {
        if (failure === 'connection') throw new TypeError('fetch failed');
        if (failure === 'body') return new Response(new ReadableStream({ start(controller) { controller.error(new TypeError('terminated')); } }));
        if (failure === 'length') return new Response(bytes, { headers: { 'content-length': String(bytes.length + 1) } });
        return new Response('corrupt archive');
      }
      if (url.pathname.endsWith('/tags/core-updates')) {
        return Response.json({ tag_name: 'core-updates', draft: false, assets: [{ name: manifest.archive, state: 'uploaded', id: 12 }] });
      }
      apiDownloads++;
      return new Response(bytes);
    };
    const file = await downloadReleaseUpdate(manifest, root, () => {}, github);
    assert.equal(apiDownloads, 1, failure);
    assert.deepEqual(await readFile(path.join(root, manifest.archive)), bytes, failure);
    assert.equal(JSON.parse(await readFile(file)).signature, manifest.signature);
  }
});

test('cancellation removes only its own partial download and never starts another route', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-download-cancel-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const controller = new AbortController();
  let calls = 0;
  await assert.rejects(downloadReleaseUpdate(signed(), root, () => controller.abort(), async () => {
    calls++;
    return new Response('not installed');
  }, controller.signal), /abort/i);
  assert.equal(calls, 1);
  await assert.rejects(readFile(path.join(root, 'patch.tar.gz')), { code: 'ENOENT' });
  await assert.rejects(readFile(path.join(root, 'runtime.json')), { code: 'ENOENT' });
  await writeFile(path.join(root, 'patch.tar.gz'), 'existing user file');
  await assert.rejects(downloadReleaseUpdate(signed(), root, () => {}, async () => new Response('test')), { code: 'EEXIST' });
  assert.equal(await readFile(path.join(root, 'patch.tar.gz'), 'utf8'), 'existing user file');
});

test('a suspended request or body recovers once with a fresh session and verifies the complete archive', async t => {
  const bytes = Buffer.from('a complete archive after resume');
  const manifest = signed({ sha256: createHash('sha256').update(bytes).digest('hex') });
  for (const phase of ['request', 'body']) {
    const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-suspend-'));
    t.after(() => rm(root, { recursive: true, force: true }));
    const names = [];
    const fetch = createUpdateFetch({ fromPartition(name) {
      names.push(name);
      const generation = names.length;
      return { webRequest: { onBeforeRequest() {} }, fetch: async () => {
        if (generation > 1) return new Response(bytes);
        const error = new TypeError('fetch failed', { cause: new Error('net::ERR_NETWORK_IO_SUSPENDED') });
        if (phase === 'request') throw error;
        return new Response(new ReadableStream({ start(controller) {
          controller.enqueue(bytes.subarray(0, 5));
          queueMicrotask(() => controller.error(error));
        } }));
      } };
    } });
    await downloadReleaseUpdate(manifest, root, () => {}, fetch);
    assert.deepEqual(names, ['kaixin-updates', 'kaixin-updates-resumed-1'], phase);
    assert.deepEqual(await readFile(path.join(root, manifest.archive)), bytes);
    assert.equal(JSON.parse(await readFile(path.join(root, 'runtime.json'))).signature, manifest.signature);
  }
});

test('interrupted downloads on both public routes rebuild the network session once and verify every byte', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-terminated-recovery-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const bytes = Buffer.from('complete archive after both routes were interrupted');
  const manifest = signed({ sha256: createHash('sha256').update(bytes).digest('hex') });
  let generation = 0, archives = 0;
  const names = [];
  const fetch = createUpdateFetch({ fromPartition(name) {
    names.push(name);
    const currentGeneration = ++generation;
    return { webRequest: { onBeforeRequest() {} }, fetch: async url => {
      if (new URL(url).pathname.endsWith('/tags/core-updates')) return Response.json({ tag_name: 'core-updates', draft: false,
        assets: [{ name: manifest.archive, state: 'uploaded', id: 12 }] });
      archives++;
      if (currentGeneration === 1) return new Response(new ReadableStream({ start(controller) {
        controller.enqueue(bytes.subarray(0, 4));
        queueMicrotask(() => controller.error(new TypeError('terminated')));
      } }));
      return new Response(bytes, { headers: { 'content-length': String(bytes.length) } });
    } };
  } });
  const file = await downloadReleaseUpdate(manifest, root, () => {}, fetch);
  assert.equal(archives, 3);
  assert.deepEqual(names, ['kaixin-updates', 'kaixin-updates-resumed-1']);
  assert.deepEqual(await readFile(path.join(root, manifest.archive)), bytes);
  assert.equal(JSON.parse(await readFile(file)).signature, manifest.signature);
});

test('persistent interrupted downloads stop after one session recovery; cancellation never retries', async t => {
  for (const cancel of [false, true]) {
    const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-terminated-limit-'));
    t.after(() => rm(root, { recursive: true, force: true }));
    const controller = new AbortController();
    let archives = 0, recoveries = 0;
    const fetch = async url => {
      if (url.pathname.endsWith('/tags/core-updates')) return Response.json({ tag_name: 'core-updates', draft: false,
        assets: [{ name: 'patch.tar.gz', state: 'uploaded', id: 12 }] });
      archives++;
      return new Response(new ReadableStream({ start(stream) { stream.error(new TypeError('terminated')); } }));
    };
    fetch.recoverAfterSuspend = async signal => {
      recoveries++;
      if (cancel) controller.abort(new Error('user cancelled'));
      signal.throwIfAborted();
    };
    await assert.rejects(downloadReleaseUpdate(signed(), root, () => {}, fetch, controller.signal), cancel ? /user cancelled/ : /terminated/);
    assert.equal(recoveries, 1);
    assert.equal(archives, cancel ? 2 : 3);
    for (const file of ['patch.tar.gz', 'runtime.json']) await assert.rejects(readFile(path.join(root, file)), { code: 'ENOENT' });
  }
});

test('only transport interruption errors qualify for a fresh download session', () => {
  for (const error of [new TypeError('terminated'), new Error('net::ERR_CONNECTION_RESET'),
    new TypeError('fetch failed', { cause: Object.assign(new Error('other side closed'), { code: 'UND_ERR_SOCKET' }) })]) {
    assert.equal(isInterruptedDownload(error), true);
  }
  for (const error of [new Error('Terminated'), new Error('checksum does not match'),
    Object.assign(new Error('disk full'), { code: 'ENOSPC' }), new DOMException('Cancelled', 'AbortError')]) {
    assert.equal(isInterruptedDownload(error), false);
  }
});

test('persistent suspension is bounded and cancellation during recovery starts no new request', async t => {
  for (const cancel of [false, true]) {
    const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-suspend-limit-'));
    t.after(() => rm(root, { recursive: true, force: true }));
    const controller = new AbortController();
    let archives = 0, recoveries = 0;
    const fetch = async url => {
      if (url.pathname.endsWith('/tags/core-updates')) return Response.json({ tag_name: 'core-updates', draft: false,
        assets: [{ name: 'patch.tar.gz', state: 'uploaded', id: 12 }] });
      archives++;
      throw new Error('net::ERR_NETWORK_IO_SUSPENDED');
    };
    fetch.recoverAfterSuspend = async signal => {
      recoveries++;
      if (cancel) controller.abort(new Error('user cancelled'));
      signal.throwIfAborted();
    };
    await assert.rejects(downloadReleaseUpdate(signed(), root, () => {}, fetch, controller.signal), cancel ? /user cancelled/ : /ERR_NETWORK_IO_SUSPENDED/);
    assert.equal(recoveries, 1);
    assert.equal(archives, cancel ? 1 : 3);
    await assert.rejects(readFile(path.join(root, 'patch.tar.gz')), { code: 'ENOENT' });
    await assert.rejects(readFile(path.join(root, 'runtime.json')), { code: 'ENOENT' });
  }
});

test('signed update reuses original runtime without modifying it; wrong archive is rejected', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-update-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const base = path.join(root, 'runtimes', current.runtimeId);
  const tree = path.join(root, 'overlay');
  const inbox = path.join(root, 'inbox');
  const { node, python } = runtimeLayout();
  for (const [directory, files] of [[base, [node, python, 'core/deeptutor_cli/main.py', 'web/server.js']],
    [tree, ['core/deeptutor_cli/main.py', 'web/server.js']]]) {
    for (const file of files) {
      await mkdir(path.dirname(path.join(directory, file)), { recursive: true });
      await writeFile(path.join(directory, file), directory === base ? 'original' : 'updated');
    }
  }
  await mkdir(inbox);
  await writeFile(path.join(base, 'installed.json'), JSON.stringify(signed(current)));
  const archive = path.join(root, 'overlay.tar.gz');
  execFileSync(systemTar(), ['-czf', archive, '-C', tree, 'core', 'web']);
  const bytes = await readFile(archive);
  const manifest = signed({ sha256: createHash('sha256').update(bytes).digest('hex'), baseRuntimeId: current.runtimeId });
  let progress = 0;
  const file = await downloadReleaseUpdate(manifest, inbox, value => { progress = value; }, async () =>
    new Response(bytes, { headers: { 'Content-Length': String(bytes.length) } }));
  assert.equal(progress, 1);
  await writeFile(path.join(inbox, manifest.archive), 'wrong');
  await assert.rejects(installBundle(file, root, publicKey), /checksum/);
  await writeFile(path.join(inbox, manifest.archive), bytes);
  const result = await installBundle(file, root, publicKey);
  const config = bundleConfig(result.destination, path.join(root, 'workspace'), manifest.runtimeId, manifest.baseRuntimeId);
  assert.equal(config.pythonPath, path.join(base, python));
  assert.equal(await readFile(path.join(config.webPath, 'server.js'), 'utf8'), 'updated');
  assert.equal(await readFile(path.join(base, 'web/server.js'), 'utf8'), 'original');
});

test('a verified release can select a matching legacy base from the same signed batch', async () => {
  const target = targetId();
  const base = { runtimeId: 'old-overlay', baseRuntimeId: 'base-old', builtAt: 100 };
  const alternate = signed({ runtimeId: 'update-old', baseRuntimeId: 'base-old', commit: 'a'.repeat(40), corePayloadSha256: 'c'.repeat(64) });
  const defaults = signed({ commit: 'a'.repeat(40), corePayloadSha256: 'c'.repeat(64),
    compatibleBaseManifests: [{ baseRuntimeId: 'base-old', file: `runtime-${target}-early.json` }] });
  let wrongBatch = false;
  const download = async url => {
    if (url.hostname === 'api.github.com') return Response.json({ tag_name: 'core-updates', draft: false, assets: [] });
    return Response.json(url.pathname.endsWith('-early.json')
      ? (wrongBatch ? signed({ ...alternate, builtAt: 201 }) : alternate) : defaults);
  };
  assert.equal((await findReleaseUpdate(target, base, publicKey, download)).runtimeId, 'update-old');
  wrongBatch = true;
  await assert.rejects(findReleaseUpdate(target, base, publicKey, download), /same signed release batch/);
});

test('a signed compatibility entry cannot redirect the client outside its platform feed', async () => {
  const manifest = signed({ baseRuntimeId: 'new-base', compatibleBaseManifests: [
    { baseRuntimeId: current.runtimeId, file: '../runtime-other.json' },
  ] });
  const download = async url => url.hostname === 'api.github.com'
    ? Response.json({ tag_name: 'core-updates', draft: false, assets: [] }) : Response.json(manifest);
  await assert.rejects(findReleaseUpdate(targetId(), current, publicKey, download), /Invalid compatible/);
});
