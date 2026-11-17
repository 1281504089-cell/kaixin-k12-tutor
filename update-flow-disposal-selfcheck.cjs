// Only the renderer-disposal ordering gap and its failure paths; no native/HTTP/UI run.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {pathToFileURL}=require('node:url');
const source=fs.readFileSync(__dirname+'/ci-update-flow.cjs','utf8'),baseline=fs.readFileSync(__dirname+'/ci-update-flow.disposal-baseline.cjs','utf8');
const root=path.join(__dirname,'update-flow-disposal-fixtures');fs.mkdirSync(root,{recursive:true});
const before={runtimeId:'materials-before',builtAt:1},after={runtimeId:'candidate-after',builtAt:2};
const disposed=()=>new Error('Render frame was disposed before the request completed');
let translateNative,sequence=0;const checks=[];
function fixture({old=false,step=100,wrongShell=false}={}) {
  const dir=fs.mkdtempSync(path.join(root,++sequence+'-')),output=path.join(dir,'result.json'),clock={now:0,step,onPause:null};
  const write=(name,value)=>{const file=path.join(dir,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(value))};
  write('active.json',before);write('upgrade.json',{phase:'prior'});write('launcher-update.json',{status:'current'});
  for(const row of [before,after])write('runtimes/'+row.runtimeId+'/launcher/manifest.json',{files:[]});
  const forwarded=[],exits=[],timers=[];
  const contents={getURL:()=>wrongShell?'file:///unrelated/index.html':pathToFileURL(path.join(dir,'../src/index.html')).href,send:(channel,...args)=>forwarded.push({channel,args})};
  const electron={app:{exit:code=>exits.push(code)},dialog:{},BrowserWindow:{getAllWindows:()=>[{webContents:contents}]},session:{}};
  const text=old?baseline:source,prefix=text.slice(0,text.indexOf('(async () => {'));
  const api=vm.runInNewContext(prefix+`;initialUpgrade=optionalRead('upgrade.json');${old?'':'shellTranslate=translateNative;'}({runCheck,flowState,fail,watch:()=>{if(typeof watchShell==='function')watchShell()},found:()=>dialog.showMessageBox({message:'发现开心动力超级学霸新版'}),installed:()=>dialog.showMessageBox({message:'更新已安装'}),markDownload:()=>{downloadStarted=true},warning:()=>dialog.showMessageBox({type:'warning',message:'真实原生更新警告',detail:'signature failed'}),error:()=>dialog.showMessageBox({type:'error',message:'真实原生更新错误',detail:'installation failed'})})`,{
    require:name=>name==='electron'?electron:require(name),__dirname:dir,process:{env:{OPEN_DEEPTUTOR_TEST_HOME:dir,KX_UPDATE_FLOW_RESULT:output},pid:10000+sequence,platform:'darwin',arch:'x64'},console:{error(){}},URL,Promise,translateNative,
    Date:class extends Date{static now(){return clock.now}},
    setTimeout:(fn,ms)=>{if(ms===1300000){timers.push(fn);return 'flow-timer'}return setTimeout(()=>{clock.now+=ms===100?clock.step:ms;clock.onPause?.();fn()},0)},clearTimeout:id=>{if(id!=='flow-timer')clearTimeout(id)}
  });
  const emit=(key,phase='starting',extra={})=>{const state={phase,language:'zh',message:translateNative('zh',key),...extra};contents.send('desktop:status',state);return state};
  let calls=0;
  const view=invoke=>({executeJavaScript:async script=>{assert.equal(script,'window.kaixinDesktop.checkForUpdates()');return invoke(++calls)}});
  const apply=async()=>{await api.found();api.markDownload();return emit('updating')};
  const testing=()=>write('upgrade.json',{phase:'testing',previous:before,candidate:after});
  const complete=async()=>{write('active.json',after);write('upgrade.json',{phase:'complete',previous:before,candidate:after});await api.installed()};
  return {api,dir,output,write,clock,contents,forwarded,exits,emit,view,apply,testing,complete,calls:()=>calls,receipt:()=>JSON.parse(fs.readFileSync(output+'.error.json'))};
}
async function check(name,fn){await fn();checks.push(name);console.log('PASS',name)}
(async()=>{
  ({translate:translateNative}=await import(pathToFileURL(path.join(__dirname,'materials-launcher-src/i18n.mjs'))));
  await check('f188 reproduces disposal failure before the real testing journal exists',async()=>{
    const f=fixture({old:true});await assert.rejects(f.api.runCheck(f.view(async()=>{await f.apply();throw disposed()})),/Render frame was disposed/);assert.equal(f.calls(),1);
  });
  await check('real shell updating is forwarded unchanged and bridges the delayed journal gap',async()=>{
    const f=fixture();let original;await f.api.runCheck(f.view(async()=>{original=await f.apply();setTimeout(()=>{f.testing();f.emit('startingCore');setTimeout(()=>{void f.complete()},4)},4);throw disposed()}));
    const proof=f.api.flowState().renderer_disposal_waits[0];assert.equal(proof.evidence.message,translateNative('zh','updating'));assert.equal(proof.evidence.accepted,1);assert(proof.completed_at>=proof.started_at);assert.strictEqual(f.forwarded[0].args[0],original);assert.equal(f.calls(),1);assert.equal(f.api.flowState().read_only_retry_reasons.length,0);
  });
  await check('arbitrary starting status and accepted/disposed do not establish application proof',async()=>{
    const f=fixture();await assert.rejects(f.api.runCheck(f.view(async()=>{await f.api.found();f.api.markDownload();f.emit('checking');throw disposed()})),/Render frame was disposed/);assert.equal(f.api.flowState().renderer_disposal_waits.length,0);
  });
  await check('an unrelated file window cannot provide trusted shell phase evidence',async()=>{
    const f=fixture({wrongShell:true});await assert.rejects(f.api.runCheck(f.view(async()=>{await f.apply();throw disposed()})),/Render frame was disposed/);
  });
  await check('missing download or acceptance evidence cannot grant pre-journal grace',async()=>{
    for(const accepted of [false,true]){const f=fixture();await assert.rejects(f.api.runCheck(f.view(async()=>{if(accepted)await f.api.found();else f.api.markDownload();f.emit('updating');throw disposed()})),/Render frame was disposed/)}
  });
  await check('a native warning after the original disposed rejection fails immediately with receipt',async()=>{
    const f=fixture();let error;try{await f.api.runCheck(f.view(async()=>{await f.apply();setTimeout(()=>{void f.api.warning().catch(()=>{})},4);throw disposed()}))}catch(value){error=value}assert.match(String(error),/真实原生更新警告/);f.api.fail(error);const receipt=f.receipt();assert.match(receipt.native_error,/signature failed/);assert.equal(receipt.accepted,1);assert.equal(receipt.check_attempts,1);assert(receipt.renderer_disposal_waits[0].evidence);assert(f.clock.now<60000);
  });
  await check('a native error dialog or actual shell error after disposal is never swallowed',async()=>{
    for(const dialog of [true,false]){const f=fixture();await assert.rejects(f.api.runCheck(f.view(async()=>{await f.apply();setTimeout(()=>{if(dialog)void f.api.error().catch(()=>{});else f.emit('startingCore','error',{detail:'worker startup failed'})},4);throw disposed()})),dialog?/真实原生更新错误/:/Native shell error.*worker startup failed/);assert.equal(f.calls(),1);assert(f.clock.now<60000)}
  });
  await check('pre-journal grace stays at sixty seconds despite repeated updating notifications',async()=>{
    const f=fixture({step:100000});f.clock.onPause=()=>f.emit('updating');let error;try{await f.api.runCheck(f.view(async()=>{await f.apply();throw disposed()}))}catch(value){error=value}assert.match(String(error),/bounded pre-journal wait/);const record=f.api.flowState().renderer_disposal_waits[0];assert.equal(record.deadline-record.started_at,60000);assert.equal(f.calls(),1);
  });
  await check('a later frontend phase receives its full 240-second product window after earlier preparation',async()=>{
    const f=fixture();await f.api.runCheck(f.view(async()=>{await f.apply();f.testing();f.emit('preparingUi');setTimeout(()=>{f.clock.now=200000;f.emit('openingSpace');setTimeout(()=>{f.clock.now=430000;void f.complete()},4)},4);throw disposed()}));const record=f.api.flowState().renderer_disposal_waits[0];assert.equal(record.phase_budget_ms,250000);assert.equal(record.deadline,450000);assert(record.completed_at>=430000);assert.equal(f.calls(),1);
  });
  await check('old-core ready events during download cannot shorten the new-core ready window',async()=>{
    const f=fixture();await f.api.runCheck(f.view(async()=>{await f.api.found();f.api.markDownload();f.emit('ready','ready');f.clock.now=45000;f.emit('updating');f.testing();f.emit('openingSpace');setTimeout(()=>{f.clock.now=60000;f.emit('ready','ready');setTimeout(()=>{f.clock.now=100000;void f.complete()},4)},4);throw disposed()}));const record=f.api.flowState().renderer_disposal_waits[0];assert.equal(record.wait_phase,'ready');assert.equal(record.deadline,120000);
  });
  await check('repeated frontend progress cannot renew its first observed phase deadline',async()=>{
    const f=fixture({step:100000});f.clock.onPause=()=>f.emit('openingSpace');await assert.rejects(f.api.runCheck(f.view(async()=>{await f.apply();f.testing();f.emit('openingSpace');throw disposed()})),/bounded openingSpace wait/);assert.equal(f.api.flowState().renderer_disposal_waits[0].deadline,250000);assert.equal(f.calls(),1);
  });
  await check('the optional resource budget requires the actual checking phase and candidate module',async()=>{
    const f=fixture({step:200000});f.write('runtimes/'+after.runtimeId+'/core/deeptutor/services/student_learning/bootstrap.py','fixture module presence');await assert.rejects(f.api.runCheck(f.view(async()=>{await f.apply();f.testing();f.emit('checking');throw disposed()})),/bounded checking wait/);const record=f.api.flowState().renderer_disposal_waits[0];assert.equal(record.phase_budget_ms,670000);assert.equal(record.bootstrap_module_present,true);assert.equal(f.calls(),1);
  });
  await check('rollback or an unrelated transaction after the gap fails without waiting or replay',async()=>{
    const f=fixture();await assert.rejects(f.api.runCheck(f.view(async()=>{await f.apply();setTimeout(()=>f.write('upgrade.json',{phase:'recovered',previous:before,candidate:after}),4);throw disposed()})),/unexpected upgrade transaction/);assert(f.clock.now<60000);assert.equal(f.calls(),1);
  });
  await check('installed confirmation still requires complete transaction and matching active pointer',async()=>{
    const f=fixture();await assert.rejects(f.api.runCheck(f.view(async()=>{await f.apply();f.testing();await f.api.installed();throw disposed()})),/Installed confirmation does not match/);assert.equal(f.calls(),1);
  });
  await check('existing verified transaction evidence remains valid when no shell event is available',async()=>{
    const f=fixture();await f.api.runCheck(f.view(async()=>{await f.api.found();f.testing();setTimeout(()=>{void f.complete()},4);throw disposed()}));assert.equal(f.api.flowState().renderer_disposal_waits[0].evidence.source,'verified-upgrade-journal');assert.equal(f.calls(),1);
  });
  await check('prior-attempt applying state and the final current check cannot grant disposal grace',async()=>{
    const f=fixture();f.api.watch();await f.apply();await assert.rejects(f.api.runCheck(f.view(async()=>{throw disposed()})),/Render frame was disposed/);
    const current=fixture();await assert.rejects(current.api.runCheck(current.view(async()=>{await current.apply();throw disposed()}),true),/Render frame was disposed/);assert.equal(current.api.flowState().renderer_disposal_waits.length,0);
  });
  await check('original connection classification, byte verification, physical/UI assertions are unchanged',()=>{
    const block=(text,start,end)=>text.slice(text.indexOf(start),text.indexOf(end));assert.equal(block(source,'function connectionTimeout(','function flowState('),block(baseline,'function connectionTimeout(','function flowState('));assert.equal(block(source,'      const updated = JSON.parse','      if (needsRestart) {'),block(baseline,'      const updated = JSON.parse','      if (needsRestart) {'));assert.equal(block(source,'    const after = JSON.parse','    await runCheck(view,true);'),block(baseline,'    const after = JSON.parse','    await runCheck(view,true);'));
  });
  fs.writeFileSync(__dirname+'/UPDATE-FLOW-DISPOSAL-SELFCHECK.json',JSON.stringify({passed:true,checks:checks.length,names:checks,scope:'Only new ordering/deadline/native-error control simulations; no old 28, UI, native install or HTTP matrix.',network_calls:0,native_installs:0,model_calls:0},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1});
