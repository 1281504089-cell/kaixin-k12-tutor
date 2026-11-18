// Offline diagnostics contract: no Electron, network, model, service writes or retries.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const digest=value=>require('node:crypto').createHash('sha256').update(JSON.stringify(value)).digest('hex');
const t=require('./ci-k12-library-ui.cjs')._test;
const origin='http://127.0.0.1:18802',id='unified_fixture',marker='fixture marker';
const empty={status:null,id_matches:false,message_count:null,marker_present:false,sources_present:false};

test('session network diagnostics track only this origin and collection/detail routes',()=>{
  const requests=new Map(),url=origin+'/api/sessions/'+id+'?dt_workspace=';
  assert.equal(t.sessionNetworkEvent('Network.requestWillBeSent',{requestId:'outside',request:{url:'https://example.com/api/sessions/'+id}},origin,requests),null);
  assert.equal(t.sessionNetworkEvent('Network.requestWillBeSent',{requestId:'wrong-port',request:{url:'http://127.0.0.1:1/api/sessions/'+id}},origin,requests),null);
  assert.equal(t.sessionNetworkEvent('Network.requestWillBeSent',{requestId:'other',request:{url:origin+'/api/student/question-bank/pictures/q'}},origin,requests),null);
  assert.equal(t.sessionNetworkEvent('Network.requestWillBeSent',{requestId:'one',request:{url,method:'GET'},timestamp:1},origin,requests).http_method,'GET');
  assert.equal(t.sessionNetworkEvent('Network.responseReceived',{requestId:'one',response:{url,status:503}},origin,requests).status,503);
  assert.equal(t.sessionNetworkEvent('Network.loadingFailed',{requestId:'one',errorText:'net::ERR_ABORTED'},origin,requests).error,'net::ERR_ABORTED');
  assert.equal(t.sessionNetworkEvent('Network.loadingFailed',{requestId:'outside',errorText:'no'},origin,requests),null);
  assert.equal(t.sessionNetworkEvent('Network.responseReceived',{requestId:'list',response:{url:origin+'/api/sessions?limit=200',status:200}},origin,requests).status,200);
});
test('runtime exceptions record bounded first-line errors without stacks',()=>{
  const value=t.runtimeException({exceptionDetails:{exception:{className:'TypeError',description:'TypeError: '+('x'.repeat(400))+'\n    at secret-stack'}}});
  assert.equal(value.name,'TypeError');assert.equal(value.message.length,240);assert(!JSON.stringify(value).includes('secret-stack'));
});
test('navigation observation retains the original promise and its rejection',async()=>{
  const ok={},p=Promise.resolve();assert.equal(t.recordNavigation(p,ok),p);await p;assert.equal(ok.state,'fulfilled');
  const bad={},error=new TypeError('ERR_NETWORK_CHANGED\nstack-private'),rejected=Promise.reject(error);
  assert.equal(t.recordNavigation(rejected,bad),rejected);await assert.rejects(rejected,/ERR_NETWORK_CHANGED/);
  assert.deepEqual(bad,{state:'rejected',error:{name:'TypeError',message:'ERR_NETWORK_CHANGED'}});
});
test('failure probe performs one no-store local GET and returns only five summary fields',async()=>{
  let calls=0;
  const result=await t.probeSessionReadOnly(origin,id,marker,async(url,options)=>{
    calls++;assert.equal(url,origin+'/api/sessions/'+id+'?dt_workspace=');assert.equal(options.method,'GET');assert.equal(options.cache,'no-store');assert.equal(options.redirect,'error');assert(options.signal instanceof AbortSignal);assert.equal(options.body,undefined);
    return {status:200,json:async()=>({id,messages:[{role:'user',content:'PRIVATE USER PROSE'},{role:'assistant',content:marker+' PRIVATE RESPONSE',events:[{metadata:{sources:[{private:'PRIVATE SOURCE'}]}}]}]})};
  });
  assert.equal(calls,1);assert.deepEqual(result,{status:200,id_matches:true,message_count:2,marker_present:true,sources_present:true});assert(!JSON.stringify(result).includes('PRIVATE'));
});
test('nested session shape and identity mismatch remain distinguishable',async()=>{
  const result=await t.probeSessionReadOnly(origin,id,marker,async()=>({status:200,json:async()=>({session:{id:'different',messages:[{role:'assistant',content:'other',metadata:{sources:[]}}]}})}));
  assert.deepEqual(result,{status:200,id_matches:false,message_count:1,marker_present:false,sources_present:false});
});
test('production session_id identity takes precedence over the legacy id field',async()=>{
  const response={session_id:id,id:'legacy-other',messages:[{role:'assistant',content:marker,metadata:{sources:[{}]}}]};
  assert.deepEqual(await t.probeSessionReadOnly(origin,id,marker,async()=>({status:200,json:async()=>response})),{status:200,id_matches:true,message_count:1,marker_present:true,sources_present:true});
  response.session_id='different';response.id=id;
  assert.equal((await t.probeSessionReadOnly(origin,id,marker,async()=>({status:200,json:async()=>response}))).id_matches,false);
});
test('invalid responses and fetch errors never expose response prose or retry',async()=>{
  let calls=0;
  const result=await t.probeSessionReadOnly(origin,id,marker,async()=>{calls++;return {status:502,json:async()=>{throw new SyntaxError('PRIVATE RESPONSE CONTENT');}};});
  assert.equal(calls,1);assert.deepEqual(result,{...empty,status:502});
  assert.deepEqual(await t.probeSessionReadOnly(origin,id,marker,async()=>{throw Error('PRIVATE TRANSPORT');}),empty);
});
test('non-loopback failure probes cannot call fetch',async()=>{
  let calls=0;assert.deepEqual(await t.probeSessionReadOnly('https://example.com',id,marker,async()=>{calls++;}),empty);assert.equal(calls,0);
});
test('timeout is exactly 5000ms, aborts a hung read and never retries',async()=>{
  const original=global.setTimeout;let delay,calls=0,signal;
  global.setTimeout=(fn,ms)=>{delay=ms;return original(fn,0);};
  try {
    const value=await t.probeSessionReadOnly(origin,id,marker,async(_url,options)=>{calls++;signal=options.signal;return new Promise(()=>{});});
    assert.deepEqual(value,empty);assert.equal(delay,5000);assert.equal(calls,1);assert.equal(signal.aborted,true);
  } finally {global.setTimeout=original;}
});
test('original assertions, time limits, four viewports, Fetch patterns and native inputs remain',()=>{
  const source=fs.readFileSync(path.join(__dirname,'ci-k12-library-ui.cjs'),'utf8');
  const assertions=s=>s.split('\n').filter(line=>line.includes('assert(')||line.includes('assert.')).map(line=>line.trim());
  assert.equal(assertions(source).length,62);
  assert.equal(digest(assertions(source)),'bfcbcf2df9610f818bc15f7f850e34f4d29d67de1bcef71ca1c9668d17595453');
  for(const needle of ['timeout = 60000','heldUntil=Date.now()+30000','await pause(1000)','for ([width,height] of [[390,844],[844,390],[1366,900],[1920,1080]])','await navigation;'])assert(source.includes(needle));
  assert.equal(source.split('view.loadURL(').length-1,6);assert.equal(source.split('view.sendInputEvent(').length-1,5);
  const fetchLines=s=>s.split('\n').filter(line=>line.includes("sendCommand('Fetch.enable'")).map(line=>line.trim());
  assert.equal(fetchLines(source).length,5);assert.equal(digest(fetchLines(source)),'ecc79db6312f499f151d542b3d1df98794d1b295fb5e08a83c90a20918e0a4a0');
  assert(source.includes("if(phase==='prepared-picture-history-delayed')record.session_api_after_failure=await probeSessionReadOnly("));
  assert(source.includes('actual_url:location.href,ready_state:document.readyState'));assert(source.includes("sendCommand('Runtime.enable')"));
  assert(!/\.click\s*\(/.test(source));
});
