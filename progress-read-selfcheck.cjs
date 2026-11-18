// Test-only Electron progress observation; no HTTP, updates or learner records.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/ci-update-flow.cjs','utf8');
const code=source.slice(source.indexOf('async function collectProgress()'),source.indexOf('async function runCheck('));
async function run(mode){
  let destroyed=mode==='already-destroyed',calls=0;
  const contents={isDestroyed:()=>destroyed,getURL:()=>'/update-progress.html',executeJavaScript:()=>{
    calls++;if(mode==='error')return Promise.reject(new Error('read failed'));
    if(mode==='destroyed-during-read'||mode==='stalled-live')return new Promise(()=>{});
    return Promise.resolve('1.2 MB / 2.0 MB');
  }};
  const win={get webContents(){assert.notEqual(mode,'already-destroyed','Closed windows must be skipped before accessing webContents');return contents},isDestroyed:()=>destroyed};
  const context={BrowserWindow:{getAllWindows:()=>[win]},assert,progressVisible:false,downloadStarted:false,progressWithBytes:false,progressReads:[],checkAttempts:2,Promise,
    setTimeout:(fn,ms)=>{assert.equal(ms,5000);return setTimeout(()=>{if(mode==='destroyed-during-read')destroyed=true;fn()},0)},clearTimeout};
  const api=vm.runInNewContext(code+';collectProgress',context);let error;try{await api()}catch(e){error=e}
  return {context,calls,error};
}
(async()=>{
  const live=await run('live');assert.equal(live.error,undefined);assert.equal(live.calls,1);assert(live.context.progressWithBytes);
  const closed=await run('destroyed-during-read');assert.equal(closed.error,undefined);assert.equal(closed.context.progressReads.length,1);assert.equal(closed.context.progressWithBytes,false);
  assert.match(String((await run('stalled-live')).error),/still-live window/);
  assert.match(String((await run('error')).error),/read failed/);
  const skipped=await run('already-destroyed');assert.equal(skipped.calls,0);assert.equal(skipped.context.progressVisible,false);
  console.log('5 bounded progress controls passed; live errors/timeouts still fail, actual update IPC must still finish');
})().catch(error=>{console.error(error);process.exitCode=1});
