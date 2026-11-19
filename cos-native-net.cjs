// QA only. Runs beside the existing native update IPC harness, never in an installer.
const assert = require('node:assert/strict');
const { createHash, verify } = require('node:crypto');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const repo = '1281504089-cell/kaixin-k12-tutor';
const direct = `https://github.com/${repo}/releases/download/`;
const api = `https://api.github.com/repos/${repo}/releases/`;
const mirror = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/';
const gitHosts = new Set(['github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com']);
const validName = /^[\w.+-]+\.(?:json|tar\.gz)$/;
const sha = value => createHash('sha256').update(value).digest('hex');

function assertLauncher(root, descriptor, expectedBuild, key, canonicalManifest) {
  assert.equal(descriptor.buildId, expectedBuild);
  assert(verify(null, Buffer.from(canonicalManifest(descriptor)), key, Buffer.from(descriptor.signature, 'base64')), 'Launcher signature mismatch');
  assert(descriptor.files.length > 0 && descriptor.files.some(row => row.file === 'src/update-network.mjs'));
  for (const row of descriptor.files) {
    assert.match(row.file, /^src\/[\w.-]+\.(?:mjs|js|cjs|html|css)$/);
    const data = readFileSync(path.join(root, row.file));
    assert.equal(data.length, row.bytes, row.file);
    assert.equal(sha(data), row.sha256, row.file);
  }
}

function installNetworkProbe(electronSession, spec, markDownload) {
  const { scenario, stageTag, selected, cosManifest, bytes, githubArchiveId } = spec;
  assert(['migration','cos','fallback'].includes(scenario));
  assert(!stageTag || /^student-\d{8}-k12-12$/.test(stageTag));
  assert(scenario !== 'cos' || !stageTag, 'COS primary must use the untouched live routes');
  assert.match(selected.archive, /^[\w.+-]+\.tar\.gz$/);
  assert.match(selected.sha256, /^[a-f0-9]{64}$/);
  assert(Number.isSafeInteger(bytes) && bytes > 0);
  if (scenario !== 'migration') {
    assert.match(cosManifest.name, /^runtime-[\w.+-]+\.json$/);
    assert.match(cosManifest.sha256, /^[a-f0-9]{64}$/);
  }
  if (githubArchiveId !== undefined) assert(Number.isSafeInteger(githubArchiveId) && githubArchiveId > 0);
  const events = [];
  const observed = new WeakSet();
  const fromPartition = electronSession.fromPartition.bind(electronSession);
  electronSession.fromPartition = (name, ...args) => {
    const partition = fromPartition(name, ...args);
    if (!/^kaixin-updates(?:-resumed-\d+)?$/.test(name) || observed.has(partition)) return partition;
    observed.add(partition);
    const fetch = partition.fetch.bind(partition);
    let active;
    // Use Chromium's own request ID across redirects; net.fetch may expose an empty Response.url.
    partition.webRequest.onBeforeRedirect(details => {
      if (active && (details.url === active.url || active.id === details.id && Number.isInteger(details.id))) active.id = details.id;
    });
    partition.webRequest.onResponseStarted(details => {
      if (active && (details.url === active.url || active.id === details.id && Number.isInteger(details.id)) && details.method === 'GET') {
        active.response = { host:new URL(details.url).hostname, status:details.statusCode, cache:details.fromCache };
      }
    });
    partition.fetch = async (url, options) => {
      const original = String(url);
      const tail = original.startsWith(mirror) ? original.slice(mirror.length) : '';
      const cosAsset = validName.test(tail) ? tail : '';
      const file = original.startsWith(`${direct}core-updates/`) ? original.slice(`${direct}core-updates/`.length) : '';
      const listing = original === api + 'tags/core-updates';
      if (listing || (validName.test(file) && file.endsWith('.json'))) events.push({kind:'github-manifest-request'});
      const archive = cosAsset.endsWith('.tar.gz') || (validName.test(file) && file.endsWith('.tar.gz'))
        || (githubArchiveId !== undefined && original === api + 'assets/' + githubArchiveId);
      const asset = cosAsset || file || selected.archive;
      if (archive) {
        markDownload();
        events.push({ kind:'archive-request', asset, route:cosAsset ? 'cos' : 'github' });
      }
      if (scenario === 'fallback' && cosAsset === selected.archive) {
        events.push({ kind:'forced-cos-archive-failure', asset });
        return new Response(null, { status:503 });
      }
      const mapped = stageTag && listing ? api + 'tags/' + stageTag
        : stageTag && validName.test(file) ? direct + stageTag + '/' + file : original;
      const manifest = cosAsset && cosAsset === cosManifest?.name;
      const track = archive || manifest;
      const observation = track ? { url:mapped } : undefined;
      assert(!active, 'Unexpected concurrent update requests in this partition');
      active = observation;
      let response;
      try { response = await fetch(mapped, options); }
      finally { active = undefined; }
      if (stageTag && listing && response.ok) {
        const metadata = await response.json();
        assert.equal(metadata.tag_name, stageTag);
        assert.equal(metadata.draft, false);
        return Response.json({ ...metadata, tag_name:'core-updates' });
      }
      if (!track || !response.body || response.status !== 200) return response;
      const observedResponse = observation.response;
      if (!observedResponse || observedResponse.cache !== false || observedResponse.status !== response.status) return response;
      const hash = createHash('sha256');
      let n = 0;
      const body = response.body.pipeThrough(new TransformStream({
        transform(chunk, controller) { n += chunk.byteLength; hash.update(chunk); controller.enqueue(chunk); },
        flush() { events.push({ kind:archive ? 'archive-body' : 'manifest-body', asset, route:cosAsset ? 'cos' : 'github',
          ...observedResponse, bytes:n, sha256:hash.digest('hex') }); },
      }));
      return new Response(body, { status:response.status, statusText:response.statusText, headers:response.headers });
    };
    return partition;
  };
  return events;
}

function verifyInstallNetwork(spec, events) {
  const fromCos = spec.scenario === 'cos';
  const index = events.findIndex(row => row.kind === 'archive-body' && row.route === (fromCos ? 'cos' : 'github')
    && (fromCos ? row.host === new URL(mirror).hostname : gitHosts.has(row.host)) && row.status === 200 && row.cache === false
    && row.asset === spec.selected.archive && row.sha256 === spec.selected.sha256 && row.bytes === spec.bytes);
  // shortcut: require one full HTTP 200 body for this release gate; use the separate native Range test for resumed bodies.
  assert(index >= 0, 'Missing complete, uncached updater archive from the expected host with exact SHA-256');
  const before = events.slice(0, index);
  if (spec.scenario !== 'migration') {
    const firstArchive = before.findIndex(row => row.kind === 'archive-request');
    const manifest = before.slice(0, firstArchive).findLastIndex(row => row.kind === 'manifest-body' && row.route === 'cos' && row.host === new URL(mirror).hostname
      && row.cache === false && row.status === 200 && row.asset === spec.cosManifest.name && row.sha256 === spec.cosManifest.sha256);
    assert(manifest >= 0, 'Missing the exact signed COS manifest body before archive completion');
    assert(firstArchive > manifest && before[firstArchive].route === 'cos' && before[firstArchive].asset === spec.selected.archive);
    assert(!before.slice(manifest + 1, firstArchive).some(row => row.kind === 'github-manifest-request'), 'The selected manifest must come from COS');
    if (fromCos) assert(!before.some(row => row.kind === 'archive-request' && row.route === 'github'));
    else {
      const fault = before.findIndex(row => row.kind === 'forced-cos-archive-failure' && row.asset === spec.selected.archive);
      const fallback = before.findIndex(row => row.kind === 'archive-request' && row.route === 'github');
      assert(fault > firstArchive && fallback > fault, 'GitHub must follow the explicit COS archive-only failure');
    }
  } else {
    assert(!before.some(row => row.route === 'cos'), 'The old updater should use GitHub only');
  }
  return events[index];
}

module.exports = { assertLauncher, installNetworkProbe, verifyInstallNetwork };
