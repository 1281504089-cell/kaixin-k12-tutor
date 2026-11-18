// Test-only pre-update fixture check: no model, installer or student profile.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/ci-update-flow.cjs','utf8');
const code=source.slice(source.indexOf('async function captureMathBaseline'),source.indexOf('function connectionTimeout'));
const fixture={mistake:'qa-unique-id',mistake_title:'数学检查 qa-unique-id'};
async function run({status=200,title=fixture.mistake_title,timeout=false,missing=false}={}){
  let receipt,calls=0;
  const capture=vm.runInNewContext(code+';captureMathBaseline',{
    assert,JSON,path:require('node:path'),home:'synthetic',output:'synthetic-result',accepted:0,
    readFileSync:()=>JSON.stringify(fixture),writeFileSync:(_,body)=>{receipt=JSON.parse(body)}
  });
  const view={executeJavaScript:script=>vm.runInNewContext(script,{
    URL,AbortController,location:{href:'http://127.0.0.1:8123/space'},
    setTimeout:(fn,ms)=>{assert.equal(ms,5000);if(timeout)fn();return 1},clearTimeout:()=>{},
    fetch:async(url,opts)=>{
      calls++;assert.equal(new URL(url).searchParams.get('practice'),fixture.mistake);assert.equal(opts.credentials,'same-origin');assert.equal(opts.cache,'no-store');
      if(opts.signal.aborted)throw new Error('AbortError');
      return {ok:status===200,status,json:async()=>({title,question:missing?'':'q',student_work:'w',images:[]})};
    }
  })};
  let error;try{await capture(view)}catch(e){error=e}
  assert.equal(calls,1);assert.equal(receipt.accepted,0);return {receipt,error};
}
(async()=>{
  assert.equal((await run()).error,undefined);
  for(const options of [{status:404},{status:401},{title:'another record'},{timeout:true},{missing:true}])assert.ok((await run(options)).error);
  const start=source.indexOf("if (phase === 'old-launcher')"),baseline=source.indexOf('await captureMathBaseline(view)',start),update=source.indexOf('await runCheck(view)',start);
  assert.ok(start<baseline&&baseline<update);
  const diagnostics=fs.readFileSync(__dirname+'/ci-materials-ui.cjs','utf8');
  assert.ok(diagnostics.includes('/api/student/mistakes?practice='));assert.ok(!diagnostics.includes("new URL('/api/student/mistakes?dt_workspace='"));
  console.log('8 math baseline controls passed; same-account read-only probe precedes any accepted update');
})().catch(error=>{console.error(error);process.exitCode=1});
