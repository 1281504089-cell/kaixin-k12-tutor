const { app, session, net } = require('electron');
const http = require('node:http');
const sockets = require('node:net');
const { readFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
app.setPath('userData', process.env.KX_PROXY_HOME);
app.disableHardwareAcceleration();
let connections = 0;
const proxy = http.createServer();
proxy.on('connect', (request, client, head) => {
  const [host, port] = request.url.split(':');
  if (port !== '443' || !['github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'].includes(host)) {
    client.destroy(); return;
  }
  connections++;
  const upstream = sockets.connect(443, host, () => {
    client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
    if (head.length) upstream.write(head);
    client.pipe(upstream).pipe(client);
  });
  upstream.on('error', () => client.destroy());
  client.on('error', () => upstream.destroy());
  client.on('close', () => upstream.destroy());
});
app.whenReady().then(async () => {
  const timer = setTimeout(() => app.exit(1), 240000);
  try {
    await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve));
    await session.defaultSession.setProxy({ mode: 'fixed_servers', proxyRules: `http=127.0.0.1:${proxy.address().port};https=127.0.0.1:${proxy.address().port}` });
    const { findReleaseUpdate, downloadReleaseUpdate } = await import(pathToFileURL(path.join(__dirname, 'release-updates.mjs')));
    const key = readFileSync(path.join(__dirname, '../assets/runtime-public.pem'));
    const base = JSON.parse(readFileSync(process.env.KX_BASE_MANIFEST));
    const target = process.platform === 'win32' ? 'windows-x64' : `macos-${process.arch}`;
    let failedDirect = false;
    const fetch = (url, options) => {
      if (url.hostname === 'github.com') {
        failedDirect = true;
        return Promise.reject(new TypeError('fetch failed'));
      }
      return net.fetch(String(url), options);
    };
    const offered = await findReleaseUpdate(target, base, key, fetch, AbortSignal.timeout(30000));
    assert.equal(offered.baseRuntimeId, base.runtimeId);
    await downloadReleaseUpdate(offered, process.env.KX_PROXY_HOME, () => {}, fetch, AbortSignal.timeout(180000));
    assert.equal(failedDirect, true);
    assert.ok(connections > 0, 'Electron must honor its proxy configuration');
    writeFileSync(process.env.KX_PROXY_RESULT, JSON.stringify({
      native_platform: process.platform, native_arch: process.arch, proxy_connections: connections,
      proxy_used: true, direct_fetch_failed: true, api_fallback_download: 'passed',
      signature_verified: true, archive_checksum_verified: true, runtime_id: offered.runtimeId,
    }, null, 2));
    clearTimeout(timer);
    app.exit(0);
  } catch (error) {
    console.error(error.message);
    clearTimeout(timer);
    app.exit(1);
  }
});
