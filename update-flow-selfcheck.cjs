// Isolated control-flow simulations only: no Electron, HTTP, installer or real profile.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/ci-update-flow.cjs','utf8'),baseline=fs.readFileSync(__dirname+'/ci-update-flow.baseline.cjs','utf8');
const prefix=source.slice(0,source.indexOf('(async () => {'));
const saveLine=source.split('\n').find(line=>line.includes("writeFileSync(stateFile, JSON.stringify({phase:'new-launcher'"));
const fixtureRoot=path.join(__dirname,'update-flow-control-fixtures');fs.mkdirSync(fixtureRoot,{recursive:true});
let fixtureSequence=0;const checks=[];
const before={runtimeId:'before-runtime',builtAt:1},after={runtimeId:'after-runtime',builtAt:2};
const idle={available:false,runtimeId:'',phase:'idle',received:0,total:0};
const timeout=()=>new Error('net::ERR_CONNECTION_TIMED_OUT');
function fixture(saved){
  const dir=fs.mkdtempSync(path.join(fixtureRoot,String(++fixtureSequence)+'-'));
  const write=(name,value)=>{const file=path.join(dir,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(value))};
  write('active.json',saved?after:before);write('upgrade.json',{phase:'prior'});write('launcher-update.json',{status:'current'});
  for(const row of [before,after])write('runtimes/'+row.runtimeId+'/launcher/manifest.json',{files:[]});
  const output=path.join(dir,'update.json');if(saved)fs.writeFileSync(output+'.state.json',JSON.stringify(saved));
  const timers=[],exits=[],windows=[];
  const electron={app:{exit:code=>exits.push(code)},dialog:{},BrowserWindow:{getAllWindows:()=>windows},session:{}};
  const sandbox={require:name=>name==='electron'?electron:require(name),process:{env:{OPEN_DEEPTUTOR_TEST_HOME:dir,KX_UPDATE_FLOW_RESULT:output},pid:1000+fixtureSequence,platform:'darwin',arch:'x64'},__dirname:dir,console:{error(){}},URL,Promise,
    setTimeout:(fn,ms)=>{if(ms===1300000){timers.push(fn);return 'global-flow-timer'}return setTimeout(fn,0)},clearTimeout:id=>{if(id!=='global-flow-timer')clearTimeout(id)}};
  const api=vm.runInNewContext(prefix+`;initialUpgrade=optionalRead('upgrade.json');({runCheck,connectionTimeout,checkedFetch,flowState,fail,found:()=>dialog.showMessageBox({message:'发现开心动力超级学霸新版'}),installed:()=>dialog.showMessageBox({message:'更新已安装'}),current:()=>dialog.showMessageBox({message:'已是最新版本'}),warning:()=>dialog.showMessageBox({type:'warning',message:'暂时无法检查更新',detail:'稍后重试'}),fatal:()=>dialog.showErrorBox('QA','fatal detail'),setStage:value=>{stage=value},saveRestart:()=>{${saveLine}},invokeError:()=>invokeError})`,sandbox);
  return {api,dir,output,write,timers,exits,windows,readError:()=>JSON.parse(fs.readFileSync(output+'.error.json')),savedState:()=>JSON.parse(fs.readFileSync(output+'.state.json'))};
}
function view(f,invoke,status=idle){let calls=0,statusCalls=0;return {executeJavaScript:async script=>{
  if(script==='window.kaixinDesktop.checkForUpdates()')return invoke(++calls);
  assert.equal(script,'window.kaixinDesktop.getUpdateStatus()');statusCalls++;return typeof status==='function'?status():status;
},counts:()=>({calls,statusCalls})}}
async function check(name,fn){await fn();checks.push(name);console.log('PASS',name)}
async function rejected(name,prepare,status=idle,error=timeout()){
  await check(name,async()=>{const f=fixture();const v=view(f,async()=>{await prepare?.(f);throw error},status);await assert.rejects(f.api.runCheck(v));assert.equal(v.counts().calls,1)});
}
(async()=>{
  await check('only explicit connection timeouts qualify; signature and non-connection errors do not',()=>{
    const f=fixture();for(const e of [timeout(),Object.assign(new Error('connect failure'),{code:'UND_ERR_CONNECT_TIMEOUT'}),Object.assign(new Error('socket'),{code:'ETIMEDOUT',syscall:'connect'}),new Error("Error invoking remote method 'desktop:check-release': Error: 核心更新未完成: GitHub update connection timed out")])assert(f.api.connectionTimeout(e));
    for(const e of [new Error('fetch failed'),new Error('The operation was aborted due to timeout'),new Error('GitHub HTTP 504'),new Error('GitHub update download stalled'),Object.assign(new Error('read ETIMEDOUT'),{code:'ETIMEDOUT',syscall:'read'}),new Error('signature verification failed',{cause:timeout()})])assert.equal(f.api.connectionTimeout(e),null);
  });
  await check('a fully evidenced accepted-zero read-only check retries the same entry once',async()=>{
    const f=fixture(),v=view(f,async call=>{if(call===1)throw timeout();await f.api.found();await f.api.installed()});
    await f.api.runCheck(v);assert.equal(v.counts().calls,2);assert.equal(v.counts().statusCalls,1);assert.equal(f.api.flowState().check_attempts,2);assert.equal(f.api.flowState().read_only_retry_reasons.length,1);assert.equal(f.api.flowState().read_only_retry_reasons[0].accepted,0);
  });
  await check('a second connection timeout fails immediately without a third check',async()=>{
    const f=fixture(),v=view(f,async()=>{throw timeout()});await assert.rejects(f.api.runCheck(v),/ERR_CONNECTION_TIMED_OUT/);assert.equal(v.counts().calls,2);assert.equal(f.api.flowState().read_only_retry_reasons.length,1);
  });
  await check('the observed archive connection timeout after acceptance fails without replay and writes receipt',async()=>{
    const f=fixture(),error=new Error('核心更新未完成: GitHub update connection timed out');
    const v=view(f,async()=>{await f.api.found();throw error});await assert.rejects(f.api.runCheck(v),/核心更新未完成/);assert.equal(v.counts().calls,1);assert.equal(v.counts().statusCalls,0);f.api.fail(error);
    const receipt=f.readError();assert.equal(receipt.accepted,1);assert.equal(receipt.stage,'check-install');assert.equal(receipt.active.runtimeId,before.runtimeId);assert.equal(receipt.check_attempts,1);assert.equal(receipt.read_only_retry_reasons.length,0);assert.deepEqual(f.exits,[1]);
  });
  await rejected('an actual archive request forbids replay even without a confirmation',async f=>{await assert.rejects(f.api.checkedFetch(async()=>{throw timeout()},'https://github.com/test/releases/download/tag/core.tar.gz'))});
  await rejected('a visible downloading window forbids replay',f=>{f.windows.push({webContents:{getURL:()=>'/update-progress.html',executeJavaScript:async()=>'1.2 MB'}})});
  await rejected('an active pointer change forbids replay',f=>f.write('active.json',after));
  await rejected('a changed install journal forbids replay',f=>f.write('upgrade.json',{phase:'testing',previous:before,candidate:after}));
  await rejected('a discovered release forbids a read-only retry',undefined,{...idle,available:true,runtimeId:after.runtimeId});
  await rejected('an installing status forbids replay',undefined,{...idle,phase:'installing'});
  await rejected('reported downloaded bytes forbid replay',undefined,{...idle,received:1});
  await rejected('an already reported installation forbids replay even without acceptance',f=>f.api.installed());
  await rejected('missing update status fails closed',undefined,null);
  await rejected('signature failures never replay even with a prior connection cause',undefined,idle,new Error('checksum verification failed',{cause:timeout()}));
  await check('a safety-state change during the read-only status query forbids replay',async()=>{
    const f=fixture(),v=view(f,async()=>{throw timeout()},async()=>{await f.api.found();return idle});await assert.rejects(f.api.runCheck(v));assert.equal(v.counts().calls,1);
  });
  await check('the final current-version check fails fast even if current was already reported',async()=>{
    const f=fixture(),v=view(f,async()=>{await f.api.current();throw timeout()});await assert.rejects(f.api.runCheck(v,true));assert.equal(v.counts().calls,1);assert.equal(v.counts().statusCalls,0);assert.equal(f.api.flowState().current_check_attempts,1);
  });
  await check('an invocation resolving without its required dialog fails instead of waiting twenty minutes',async()=>{
    const f=fixture(),v=view(f,async()=>undefined);await assert.rejects(f.api.runCheck(v),/without an installed update/);assert.equal(v.counts().calls,1);
  });
  await check('a verified successful install may normally dispose its original renderer',async()=>{
    const f=fixture(),v=view(f,async()=>{await f.api.found();f.write('active.json',after);f.write('upgrade.json',{phase:'complete',previous:before,candidate:after});await f.api.installed();throw new Error('Render frame was disposed before the request completed')});await f.api.runCheck(v);assert.equal(v.counts().calls,1);
  });
  await check('renderer disposal during a real testing transaction waits for installed confirmation',async()=>{
    const f=fixture(),v=view(f,async()=>{await f.api.found();f.write('upgrade.json',{phase:'testing',previous:before,candidate:after});setTimeout(async()=>{f.write('active.json',after);f.write('upgrade.json',{phase:'complete',previous:before,candidate:after});await f.api.installed()},5);throw new Error('Render frame was disposed before the request completed')});await f.api.runCheck(v);assert.equal(v.counts().calls,1);
  });
  await rejected('renderer disposal without real install evidence fails',f=>f.api.found(),idle,new Error('Render frame was disposed before the request completed'));
  await check('non-disposal errors cannot be hidden behind an installed flag',async()=>{
    const f=fixture(),v=view(f,async()=>{await f.api.installed();throw new Error('checksum failed')});await assert.rejects(f.api.runCheck(v),/checksum failed/);
  });
  await check('a rejection without an error object cannot become a successful installed check',async()=>{
    const f=fixture(),v=view(f,async()=>{await f.api.installed();throw null});await assert.rejects(f.api.runCheck(v),/without an error detail/);assert.equal(v.counts().calls,1);
  });
  await check('attempt count and retry reason survive the exact signed-launcher state writer and reopen',async()=>{
    const f=fixture(),v=view(f,async call=>{if(call===1)throw timeout();await f.api.found();await f.api.installed()});await f.api.runCheck(v);f.api.saveRestart();
    const saved=f.savedState();assert.equal(saved.phase,'new-launcher');assert.equal(saved.check_attempts,2);assert.equal(saved.read_only_retry_reasons.length,1);
    const reopened=fixture(saved),current=view(reopened,async()=>reopened.api.current());await reopened.api.runCheck(current,true);assert.equal(reopened.api.flowState().check_attempts,3);assert.equal(reopened.api.flowState().read_only_retry_reasons.length,1);
  });
  await check('the actual global timeout handler writes stage, accepted, attempts and active pointer',async()=>{
    const f=fixture();await f.api.found();f.write('active.json',after);f.api.setStage('await-signed-restart');f.timers[0]();const receipt=f.readError();assert.equal(receipt.stage,'await-signed-restart');assert.equal(receipt.accepted,1);assert.equal(receipt.active.runtimeId,after.runtimeId);assert.equal(typeof receipt.check_attempts,'number');assert.match(receipt.error,/timed out/);assert.deepEqual(f.exits,[1]);
  });
  await check('native fatal error boxes also write an error receipt',()=>{const f=fixture();f.api.fatal();assert.equal(f.readError().stage,'native-error-box');assert.deepEqual(f.exits,[1])});
  await check('actual connection causes remain attributable through the native warning wrapper',async()=>{
    const f=fixture(),v=view(f,async call=>{if(call===1){await assert.rejects(f.api.checkedFetch(async()=>{throw timeout()},'https://api.github.com/repos/test/releases/tags/core'));await f.api.warning()}else{await f.api.found();await f.api.installed()}});await f.api.runCheck(v);assert.equal(v.counts().calls,2);assert.equal(f.api.flowState().read_only_retry_reasons[0].reason,'net::ERR_CONNECTION_TIMED_OUT');
  });
  await check('a later completed fetch clears a stale connection cause before verification errors',async()=>{
    const f=fixture();await assert.rejects(f.api.checkedFetch(async()=>{throw timeout()},'https://api.github.com/repos/test/releases/tags/core'));await f.api.checkedFetch(async()=>({status:200}),'https://github.com/test/runtime.json');let error;try{await f.api.warning()}catch(e){error=e}assert.equal(f.api.connectionTimeout(error),null);
  });
  await check('all install, signed launcher, UI, pixel, source and data assertion blocks remain unchanged',()=>{
    const block=text=>text.slice(text.indexOf('    const after = JSON.parse'),text.indexOf("    await view.executeJavaScript('window.kaixinDesktop.checkForUpdates()');")>0?text.indexOf("    await view.executeJavaScript('window.kaixinDesktop.checkForUpdates()');"):text.indexOf('    await runCheck(view,true);')).replace("    stage='ui-checks';\n",'');assert.equal(block(source),block(baseline));
    const install=text=>text.slice(text.indexOf('      const updated = JSON.parse'),text.indexOf('      if (needsRestart) {'));assert.equal(install(source),install(baseline));
  });
  fs.writeFileSync(__dirname+'/UPDATE-FLOW-SELFCHECK.json',JSON.stringify({passed:true,checks:checks.length,names:checks,scope:'Simulated QA control flow only; no native, HTTP or installer verification claimed.',network_calls:0,model_calls:0},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1});
