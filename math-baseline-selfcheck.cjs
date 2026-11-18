// Test-only pre-update fixture check: no model, installer or student profile.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/ci-update-flow.cjs','utf8');
const code=source.slice(source.indexOf('async function captureMathBaseline'),source.indexOf('function connectionTimeout'));
const fixture={mistake:'qa-unique-id',mistake_title:'数学检查 qa-unique-id'};
async function run({status=200,title=fixture.mistake_title,timeout=false,missing=false,missingWork=false,elapsed=0,mainHang=false,nodeHang=false}={}){
  let receipt,calls=0,nodeCalls=0,executeCalls=0;const clock={now:0};
  class ClockDate extends Date {static now(){return clock.now;}}
  const capture=vm.runInNewContext(code+';captureMathBaseline',{
    assert,JSON,URL,AbortController,Date:ClockDate,path:require('node:path'),home:'synthetic',output:'synthetic-result',accepted:0,
    readFileSync:()=>JSON.stringify(fixture),writeFileSync:(_,body)=>{receipt=JSON.parse(body)},
    setTimeout:(fn,ms)=>{
      if(ms===35000){if(mainHang)queueMicrotask(()=>{clock.now=35000;fn();});}
      else {assert(ms>0&&ms<=5000);if(nodeHang){clock.now+=ms;fn();}}
      return 1;
    },clearTimeout:()=>{},
    fetch:async(url,opts)=>{
      nodeCalls++;assert.equal(opts.method,'GET');assert.equal(new URL(url).searchParams.get('practice'),fixture.mistake);assert.equal(opts.redirect,'error');
      if(nodeHang)return new Promise(()=>{});
      return {ok:true,status:200,json:async()=>({title:fixture.mistake_title,question:'q',student_work:'w'})};
    }
  });
  const view={getURL:()=> 'http://127.0.0.1:8123/space',executeJavaScript:script=>{
    executeCalls++;if(mainHang)return new Promise(()=>{});
    return vm.runInNewContext(script,{
      URL,AbortController,Date:ClockDate,location:{href:'http://127.0.0.1:8123/space'},
      setTimeout:(fn,ms)=>{assert.equal(ms,30000);if(timeout){clock.now=30000;fn();}return 1;},clearTimeout:()=>{},
      fetch:async(url,opts)=>{
        calls++;assert.equal(opts.method,'GET');assert.equal(new URL(url).searchParams.get('practice'),fixture.mistake);assert.equal(opts.credentials,'same-origin');assert.equal(opts.cache,'no-store');
        if(opts.signal.aborted)throw new Error('AbortError');clock.now=elapsed;
        return {ok:status===200,status,json:async()=>({title,question:missing?'':'q',student_work:missingWork?'':'w',images:[]})};
      }
    });
  }};
  let error;try{await capture(view)}catch(e){error=e}
  assert.equal(executeCalls,1);assert.equal(calls,mainHang?0:1);assert.equal(receipt.accepted,0);
  return {receipt,error,calls,nodeCalls};
}
(async()=>{
  const fast=await run();assert.equal(fast.error,undefined);assert.equal(fast.nodeCalls,0);assert.equal(fast.receipt.deadline_ms,30000);assert.equal(fast.receipt.within_original_5s,true);
  // Preserve the original wrong HTTP/title/content/timeout refusals.
  for(const options of [{status:404},{status:401},{title:'another record'},{timeout:true},{missing:true},{missingWork:true}])assert.ok((await run(options)).error);
  const slow=await run({elapsed:6200});assert.equal(slow.error,undefined);assert.equal(slow.receipt.elapsed_ms,6200);assert.equal(slow.receipt.within_original_5s,false);assert.equal(slow.nodeCalls,0);
  const expired=await run({timeout:true});assert.ok(expired.error);assert.equal(expired.receipt.elapsed_ms,30000);assert.equal(expired.receipt.within_original_5s,false);assert.equal(expired.nodeCalls,1);assert.equal(expired.receipt.main_node_diagnostic.status,200);assert.equal(expired.receipt.main_node_diagnostic.title_matches,true);assert.equal(expired.receipt.ok,undefined);
  const hung=await run({mainHang:true});assert.ok(hung.error);assert.equal(hung.receipt.main_deadline_ms,35000);assert.equal(hung.receipt.elapsed_ms,35000);assert.equal(hung.nodeCalls,0);assert.equal(hung.receipt.main_node_diagnostic.skipped,'main baseline deadline exhausted');
  const nodeHung=await run({timeout:true,nodeHang:true});assert.ok(nodeHung.error);assert.equal(nodeHung.nodeCalls,1);assert.equal(nodeHung.receipt.main_node_diagnostic.deadline_ms,5000);assert.equal(nodeHung.receipt.main_node_diagnostic.elapsed_ms,5000);assert.match(nodeHung.receipt.main_node_diagnostic.error,/deadline/);
  const start=source.indexOf("if (phase === 'old-launcher')"),baseline=source.indexOf('await captureMathBaseline(view)',start),update=source.indexOf('await runCheck(view)',start);
  assert.ok(start<baseline&&baseline<update);
  const diagnostics=fs.readFileSync(__dirname+'/ci-materials-ui.cjs','utf8');
  assert.ok(diagnostics.includes('/api/student/mistakes?practice='));assert.ok(!diagnostics.includes("new URL('/api/student/mistakes?dt_workspace='"));
  console.log('13 math baseline controls passed; original8 retained, single30s renderer GET, slow5s tagged, failed-only5s diagnostic cannot pass, total35s bounded');
})().catch(error=>{console.error(error);process.exitCode=1});
