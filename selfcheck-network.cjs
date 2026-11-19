const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {installNetworkProbe,verifyInstallNetwork}=require('./cos-native-net.cjs');
const repo='1281504089-cell/kaixin-k12-tutor';
const mirror='https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/';
const stable=`https://github.com/${repo}/releases/download/core-updates/`;
const sha=value=>createHash('sha256').update(value).digest('hex');
const selected={archive:'fixture.tar.gz',sha256:sha('fixture')}, name='runtime-macos-x64.json';
const manifest=JSON.stringify(selected), cosManifest={name,sha256:sha(manifest)};

(async()=>{
 for(const scenario of ['migration','cos','fallback']) {
  const stageTag=scenario==='cos'?undefined:'student-20261117-k12-12';
  const spec={scenario,selected,cosManifest,bytes:7,stageTag};
  let onRedirect,onResponse,id=0,marked=0;
  const partition={webRequest:{onBeforeRedirect(fn){onRedirect=fn;},onResponseStarted(fn){onResponse=fn;}},async fetch(url){
    const request=++id;
    if(url.startsWith(stable.replace('core-updates',stageTag))) {
      onRedirect({url,id:request});
      url='https://release-assets.githubusercontent.com/a-download';
    }
    onResponse({url,id:request,method:'GET',statusCode:200,fromCache:false});
    return new Response(url.endsWith('.json')?manifest:'fixture');
  }};
  const session={fromPartition(){return partition;}};
  const events=installNetworkProbe(session,spec,()=>{marked++;});
  const verify=()=>verifyInstallNetwork(spec,events);
  const fetch=session.fromPartition('kaixin-updates').fetch;
  if(scenario!=='migration') assert.equal(await (await fetch(mirror+name)).text(),manifest);
  assert.throws(verify,/Missing complete/);
  if(scenario==='fallback') assert.equal((await fetch(mirror+selected.archive)).status,503);
  assert.equal(await (await fetch((scenario==='cos'?mirror:stable)+selected.archive)).text(),'fixture');
  const archive=verify();
  assert.equal(archive.host,scenario==='cos'?new URL(mirror).hostname:'release-assets.githubusercontent.com');
  assert.equal(marked,scenario==='fallback'?2:1);
  archive.cache=true;assert.throws(verify,/Missing complete/);archive.cache=false;
  archive.sha256='0'.repeat(64);assert.throws(verify,/Missing complete/);archive.sha256=selected.sha256;
  if(scenario==='fallback') assert.throws(()=>verifyInstallNetwork(spec,events.filter(x=>x.kind!=='forced-cos-archive-failure')),/explicit COS archive-only failure/);
 }
 console.log('PASS: all three route receipts; rejects check-only, cached, wrong bytes, and unproven fallback');
})().catch(error=>{console.error(error);process.exitCode=1;});
