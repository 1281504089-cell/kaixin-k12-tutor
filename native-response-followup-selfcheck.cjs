const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {createHash}=require('node:crypto');
const t=require('./ci-k12-library-ui.cjs')._test;
const source=fs.readFileSync(__dirname+'/ci-k12-library-ui.cjs','utf8');
const raw=Buffer.from('%PDF-1.7\ncomplete original response\n%%EOF');
const sha=createHash('sha256').update(raw).digest('hex');
const spec={url:'http://127.0.0.1/api/student/question-bank/native/math%3Atest?sha256='+sha,native:{bytes:raw.length,sha256:sha}};
const headers={'Content-Type':'application/pdf','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"};
const params={requestId:'fetch-original',networkId:'network-original',request:{url:spec.url},responseStatusCode:200,responseHeaders:Object.entries(headers).map(([name,value])=>({name,value}))};
const checks=[];
async function check(name,fn){await fn();checks.push(name);console.log('PASS',name)}
function fakeDebug({body=raw,readError,continueError}={}){
  const calls=[];
  return {calls,sendCommand:async(method,args)=>{
    calls.push({method,args});assert.equal(args.requestId,params.requestId);
    if(method==='Fetch.getResponseBody'){if(readError)throw Error(readError);return {body:body.toString('base64'),base64Encoded:true}}
    assert.equal(method,'Fetch.continueResponse');if(continueError)throw Error(continueError);return {};
  }};
}
function nativeHTTP(reply,{since=0,url=spec.url,missing=false}={}){
  const network=[{type:'request',id:params.networkId,url:spec.url},{type:'response',id:params.networkId,url:spec.url,status:200},{type:'failed',id:params.networkId,url:spec.url,error:'net::ERR_ABORTED'}];
  let tick=0;
  const fn=vm.runInNewContext('('+source.slice(source.indexOf('  async function nativeHTTP('),source.indexOf('  async function nativePreview(')).trim()+')',{
    nativeResponses:missing?[]:[{...reply,sequence:4,complete:true}],network,requestURLs:new Map([[params.networkId,url]]),assert,assertNativeResponse:t.assertNativeResponse,
    Date:{now:()=>tick++*60001},pause:async()=>{},entry:'fixture',width:390,height:844,phase:'native'
  });
  return {run:()=>fn(spec,since),network};
}
(async()=>{
  await check('ready false objects and missing readiness never pass',()=>{for(const probe of [{ready:false},{},null,undefined,false,1,'ready'])assert.equal(t.waitReady(probe),false);assert(t.waitReady(true));assert(t.waitReady({ready:true}))});
  await check('the actual wait polls until ready true',async()=>{
    const values=[{ready:false},{ready:false,painted:true},{ready:true}];let polls=0;
    const wait=vm.runInNewContext('('+source.slice(source.indexOf('  async function wait('),source.indexOf('  async function monitor(')).trim()+')',{Date,assert,pause:async()=>{},waitReady:t.waitReady,js:async()=>values[polls++]});
    await wait(()=>{},[],'not ready');assert.equal(polls,3);
  });
  let captured;
  await check('original Fetch response body is read and verified before continuation',async()=>{
    const debug=fakeDebug();captured=await t.captureNativeResponse(debug,params,spec);
    assert(captured.raw.equals(raw));assert.equal(captured.id,params.networkId);assert.deepEqual(debug.calls.map(call=>call.method),['Fetch.getResponseBody','Fetch.continueResponse']);
  });
  await check('200 then ERR_ABORTED passes only with complete original body proof, no loadingFinished',async()=>{
    const test=nativeHTTP(captured);const result=await test.run();assert(result.native_http_pdf_sha_verified&&result.private_headers_verified);assert.equal(result.response_capture,'Fetch.getResponseBody');assert.equal(result.original_request_id,params.networkId);assert(!test.network.some(event=>event.type==='finished'));assert(test.network.some(event=>event.type==='native-response-verified'&&event.bytes===raw.length&&event.sha256===sha));
  });
  await check('200 then ERR_ABORTED without captured original bytes fails',async()=>assert.rejects(nativeHTTP(captured,{missing:true}).run,/original response body was not captured/));
  await check('an old captured response cannot satisfy a later phase',async()=>assert.rejects(nativeHTTP(captured,{since:4}).run,/original response body was not captured/));
  await check('captured response must bind to the same Network URL',async()=>assert.rejects(nativeHTTP(captured,{url:spec.url+'&other=1'}).run,/original Network request/));
  await check('transport rejects truncated original bytes',async()=>assert.rejects(t.captureNativeResponse(fakeDebug({body:raw.subarray(0,-1)}),params,spec)));
  await check('transport rejects same-size modified bytes',async()=>{const bad=Buffer.from(raw);bad[8]^=1;await assert.rejects(t.captureNativeResponse(fakeDebug({body:bad}),params,spec),/frozen student pages/)});
  await check('transport rejects unsafe original private headers',async()=>assert.rejects(t.captureNativeResponse(fakeDebug(),{...params,responseHeaders:params.responseHeaders.filter(header=>header.name!=='Cache-Control')},spec)));
  await check('transport rejects partial HTTP status',async()=>assert.rejects(t.captureNativeResponse(fakeDebug(),{...params,responseStatusCode:206},spec)));
  await check('transport requires a frozen descriptor before accepting bytes',async()=>assert.rejects(t.captureNativeResponse(fakeDebug(),params),/frozen expected descriptor/));
  await check('transport requires the original Network request ID',async()=>assert.rejects(t.captureNativeResponse(fakeDebug(),{...params,networkId:undefined},spec),/original Network request ID/));
  await check('body read failures remain failures and release the paused response',async()=>{const debug=fakeDebug({readError:'body unavailable'});await assert.rejects(t.captureNativeResponse(debug,params,spec),/body unavailable/);assert.equal(debug.calls.at(-1).method,'Fetch.continueResponse');await assert.rejects(nativeHTTP({url:spec.url,id:params.networkId,error:'body unavailable'}).run,/body unavailable/)});
  await check('response continuation failure cannot become a passing capture',async()=>assert.rejects(t.captureNativeResponse(fakeDebug({continueError:'continuation failed'}),params,spec),/continuation failed/));
  const report={passed:true,checks:checks.length,names:checks,network_calls:0,browser_calls:0,model_calls:0};
  fs.writeFileSync(__dirname+'/NATIVE-RESPONSE-FOLLOWUP-SELFCHECK.json',JSON.stringify(report,null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1});
