const { app, session } = require('electron');
const http = require('node:http');
const sockets = require('node:net');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const { createHash } = require('node:crypto');
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
    await session.fromPartition('kaixin-updates').setProxy({ mode: 'fixed_servers', proxyRules: `http=127.0.0.1:${proxy.address().port};https=127.0.0.1:${proxy.address().port}` });
    const { findReleaseUpdate, downloadReleaseUpdate } = await import(pathToFileURL(path.join(__dirname, 'release-updates.mjs')));
    const { verifyManifest } = await import(pathToFileURL(path.join(__dirname, 'bundles.mjs')));
    const { createUpdateFetch } = await import(pathToFileURL(path.join(__dirname, 'update-network.mjs')));
    const systemFetch = createUpdateFetch(session);
    let sessionRecoveries=0;
    const recoverSession=async signal=>{
      await systemFetch.recoverAfterSuspend(signal);sessionRecoveries++;
      await session.fromPartition(`kaixin-updates-resumed-${sessionRecoveries}`).setProxy({mode:'fixed_servers',proxyRules:`http=127.0.0.1:${proxy.address().port};https=127.0.0.1:${proxy.address().port}`});
    };
    const key = readFileSync(path.join(__dirname, '../assets/runtime-public.pem'));
    const base = JSON.parse(readFileSync(process.env.KX_BASE_MANIFEST));
    const target = process.platform === 'win32' ? 'windows-x64' : `macos-${process.arch}`;
    let failedDirect = false;
    const fetch = async (url, options) => {
      if (url.hostname === 'github.com') {
        failedDirect = true;
        return Promise.reject(new TypeError('fetch failed'));
      }
      try {
        const ciOptions = url.hostname === 'api.github.com' && process.env.GH_TOKEN
          ? { ...options, headers: { ...options.headers, Authorization: `Bearer ${process.env.GH_TOKEN}` } } : options;
        const response = await systemFetch(url, ciOptions);
        console.log('Proxy request:', url.hostname, response.status);
        return response;
      } catch (error) {
        console.error('Proxy request failed:', url.hostname, error.message, error.cause?.code);
        throw error;
      }
    };
    fetch.recoverAfterSuspend=recoverSession;
    const offered = await findReleaseUpdate(target, base, key, fetch, AbortSignal.timeout(30000));
    assert.equal(offered.baseRuntimeId, base.runtimeId);
    await downloadReleaseUpdate(offered, process.env.KX_PROXY_HOME, () => {}, fetch, AbortSignal.timeout(180000));
    assert.equal(failedDirect, true);
    assert.ok(connections > 0, 'Electron must honor its proxy configuration');
    const fixtureName=`runtime-${target}.json`;
    const response=await systemFetch(new URL(`https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/core-updates/${fixtureName}`),{signal:AbortSignal.timeout(30000),credentials:'omit'});
    assert.equal(response.ok,true);const chunks=[];let bytes=0;
    for await(const chunk of response.body){bytes+=chunk.length;assert.ok(bytes<=16384);chunks.push(chunk);}
    const payload=Buffer.concat(chunks);verifyManifest(JSON.parse(payload),key);
    let recoveries=0,faults=0;
    const interruptedFetch=async(url,options)=>{
      const ciOptions=url.hostname==='api.github.com'&&process.env.GH_TOKEN?{...options,headers:{...options.headers,Authorization:`Bearer ${process.env.GH_TOKEN}`}}:options;
      const result=await systemFetch(url,ciOptions);
      if(!result.ok)console.error('Interrupted fixture HTTP:',url.hostname,result.status,'API remaining:',result.headers.get('x-ratelimit-remaining'));
      if(recoveries===0&&result.ok&&result.body&&(url.pathname.endsWith('/'+fixtureName)||options.headers?.Accept==='application/octet-stream')){
        faults++;
        return new Response(result.body.pipeThrough(new TransformStream({transform(){throw new TypeError('terminated');}})),{status:result.status,headers:result.headers});
      }
      return result;
    };
    interruptedFetch.recoverAfterSuspend=async signal=>{
      await recoverSession(signal);recoveries++;
    };
    const inbox=path.join(process.env.KX_PROXY_HOME,'interrupted-fixture');mkdirSync(inbox);
    const fixtureSha=createHash('sha256').update(payload).digest('hex');
    await downloadReleaseUpdate({archive:fixtureName,sha256:fixtureSha},inbox,()=>{},interruptedFetch,AbortSignal.timeout(90000));
    assert.equal(faults,2);assert.equal(recoveries,1);assert.deepEqual(readFileSync(path.join(inbox,fixtureName)),payload);
    let mixedRecoveries=0,mixedFaults=0,apiDenials=0;
    const mixedFetch=async(url,options)=>{
      if(url.hostname==='api.github.com'){apiDenials++;return new Response(null,{status:403});}
      const result=await systemFetch(url,options);
      if(mixedRecoveries===0&&result.ok&&result.body)return new Response(result.body.pipeThrough(new TransformStream({transform(){mixedFaults++;throw new TypeError('terminated');}})),{status:result.status,headers:result.headers});
      return result;
    };
    mixedFetch.recoverAfterSuspend=async signal=>{
      await recoverSession(signal);mixedRecoveries++;
    };
    const mixedInbox=path.join(process.env.KX_PROXY_HOME,'interrupted-denied-fixture');mkdirSync(mixedInbox);
    await downloadReleaseUpdate({archive:fixtureName,sha256:fixtureSha},mixedInbox,()=>{},mixedFetch,AbortSignal.timeout(90000));
    assert.equal(mixedFaults,1);assert.equal(apiDenials,1);assert.equal(mixedRecoveries,1);assert.deepEqual(readFileSync(path.join(mixedInbox,fixtureName)),payload);
    writeFileSync(process.env.KX_PROXY_RESULT, JSON.stringify({
      native_platform: process.platform, native_arch: process.arch, proxy_connections: connections,
      proxy_used: true, direct_fetch_failed: true, api_fallback_download: 'passed',
      ci_api_authenticated: Boolean(process.env.GH_TOKEN),
      signature_verified: true, archive_checksum_verified: true, runtime_id: offered.runtimeId,
      interrupted_transport_fixture:{faults,recoveries,bytes,sha256:fixtureSha,verified_complete:true,full_installer_or_core:false,ci_api_authenticated:Boolean(process.env.GH_TOKEN),anonymous_initial_direct_payload:true},
      interrupted_direct_denied_api_fixture:{mixedFaults,apiDenials,mixedRecoveries,verified_complete:true,anonymous_direct_download:true,injected_api_denial:true},
    }, null, 2));
    clearTimeout(timer);
    app.exit(0);
  } catch (error) {
    console.error(error.message);
    clearTimeout(timer);
    app.exit(1);
  }
});
