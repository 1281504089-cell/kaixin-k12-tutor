// New passive backup/worker diagnostics only; no Electron, HTTP or installer matrix.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {pathToFileURL}=require('node:url'),childProcess=require('node:child_process');
const source=fs.readFileSync(__dirname+'/ci-update-flow.cjs','utf8'),baseline=fs.readFileSync(__dirname+'/ci-update-flow.backup-baseline.cjs','utf8');
const root=path.join(__dirname,'update-flow-backup-fixtures');fs.mkdirSync(root,{recursive:true});
const before={runtimeId:'materials-before',builtAt:1},after={runtimeId:'candidate-after',builtAt:2},old={pid:111,created:1,role:'supervisor',alive:true};
const backupName='before-'+after.runtimeId+'-1000';let translateNative,sequence=0,localProbes=0,processProbeVerified=false;const checks=[];
const stat=(files=1,bytes=100)=>({name:backupName,files,logical_bytes:bytes,directories:2,symlinks:0,newest_mtime_ns:1,scan_complete:true,examples:[{path:'data/example.json',bytes}]});
function fixture(){
  const dir=fs.mkdtempSync(path.join(root,++sequence+'-')),output=path.join(dir,'result.json'),clock={now:0,step:10000};
  const write=(name,value)=>{const file=path.join(dir,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(value))};
  write('active.json',before);write('upgrade.json',{phase:'prior'});write('launcher-update.json',{status:'current'});for(const row of [before,after])write('runtimes/'+row.runtimeId+'/launcher/manifest.json',{files:[]});
  const requests=[],exits=[],forwarded=[];let provider=()=>({backups:[],backup_names:[],processes_complete:true,old_processes:[{...old,alive:false}],children:[]});
  const shell={getURL:()=>pathToFileURL(path.join(dir,'../src/index.html')).href,send:(...args)=>forwarded.push(args)};
  const electron={app:{exit:code=>exits.push(code)},dialog:{},BrowserWindow:{getAllWindows:()=>[{webContents:shell}]},session:{}};
  const execFile=(python,args,options,callback)=>{
    const p=JSON.parse(args.at(-1));requests.push({python,p,options});
    const result=p.baseline===null?{backups:[],backup_names:['prior-backup'],processes_complete:true,children:[old],old_processes:[]}:provider(p);
    setTimeout(()=>result instanceof Error?callback(result):callback(null,JSON.stringify(result)),0);
  };
  const prefix=source.slice(0,source.indexOf('(async () => {'));
  const api=vm.runInNewContext(prefix+`;initialUpgrade=optionalRead('upgrade.json');shellTranslate=translateNative;({runCheck,flowState,fail,waitForBackup,sampleBackup,backupProbe,candidate:value=>{selectedCandidate=value},found:()=>dialog.showMessageBox({message:'发现开心动力超级学霸新版'}),installed:()=>dialog.showMessageBox({message:'更新已安装'}),markDownload:()=>{downloadStarted=true},warning:()=>dialog.showMessageBox({type:'warning',message:'备份实际失败',detail:'source I/O error'})})`,{
    require:name=>name==='electron'?electron:name==='node:child_process'?{execFile}:require(name),__dirname:dir,process:{env:{OPEN_DEEPTUTOR_TEST_HOME:dir,KX_UPDATE_FLOW_RESULT:output},pid:10000+sequence,platform:'darwin',arch:'x64'},console:{error(){}},URL,Promise,translateNative,
    Date:class extends Date{static now(){return clock.now}},setTimeout:(fn,ms)=>ms===1300000?'global-timer':setTimeout(()=>{clock.now+=ms===100?clock.step:ms;fn()},0),clearTimeout:id=>{if(id!=='global-timer')clearTimeout(id)}
  });
  let calls=0;const view=invoke=>({send:(...args)=>forwarded.push(args),executeJavaScript:async script=>{assert.equal(script,'window.kaixinDesktop.checkForUpdates()');calls++;return invoke()}});
  const apply=async v=>{v.send('desktop:release-status',{available:true,runtimeId:after.runtimeId});await api.found();api.markDownload();shell.send('desktop:status',{phase:'starting',language:'zh',message:translateNative('zh','updating')})};
  const complete=()=>{write('active.json',after);write('upgrade.json',{phase:'complete',previous:before,candidate:after});return api.installed()};
  const context=()=>({names:[],old:[old],processes_complete:true});
  const disposal=()=>({started_at:0,pre_journal_deadline:60000,deadline:60000});
  return {api,dir,output,clock,write,requests,exits,forwarded,view,apply,complete,context,disposal,provider:fn=>{provider=fn},calls:()=>calls};
}
async function check(name,fn){await fn();checks.push(name);console.log('PASS',name)}
(async()=>{
  const local=path.join(__dirname,'materials-launcher-src/i18n.mjs');
  ({translate:translateNative}=await import(pathToFileURL(fs.existsSync(local)?local:path.resolve(__dirname,'../../release-native-pages-20261117/recipe/materials-launcher-src/i18n.mjs'))));
  await check('the baseline snapshot cannot falsely count an old worker as already stopped',async()=>{
    const f=fixture(),c={names:null,old:[]};await f.api.sampleBackup(c,true);f.provider(()=>({backups:[],backup_names:[],processes_complete:true,old_processes:[old]}));f.api.candidate(after.runtimeId);const d=f.disposal();await f.api.waitForBackup(c,d);assert.equal(f.requests.length,2);assert.equal(d.worker_state,'old-worker-alive');assert.equal(d.deadline,60000);
  });
  await check('a growing candidate backup can bridge sixty seconds without rechecking or replaying install',async()=>{
    const f=fixture();f.provider(()=>{if(f.clock.now>=90000)void f.complete();return {backups:[stat(Math.floor(f.clock.now/10000)+1,f.clock.now+100)],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}]}});
    let v;v=f.view(async()=>{await f.apply(v);throw Error('Render frame was disposed before the request completed')});await f.api.runCheck(v);const result=f.api.flowState();assert.equal(f.calls(),1);assert.equal(result.read_only_retry_reasons.length,0);assert(result.renderer_disposal_waits[0].completed_at>60000);assert(fs.existsSync(f.output+'.backup.json'));
  });
  await check('worker liveness and CPU activity without a new backup do not extend the stop wait',async()=>{
    const f=fixture();f.provider(()=>({backups:[],backup_names:[],processes_complete:true,old_processes:[{...old,cpu_seconds:f.clock.now}]}));let v;v=f.view(async()=>{await f.apply(v);throw Error('Render frame was disposed before the request completed')});await assert.rejects(f.api.runCheck(v),/bounded pre-journal/);const d=f.api.flowState().renderer_disposal_waits[0];assert.equal(d.pre_journal_state,'old-worker-alive');assert.equal(d.deadline,d.started_at+60000);assert.equal(f.calls(),1);
  });
  await check('constant files with changing timestamps, CPU or an open PDF do not renew progress',async()=>{
    const f=fixture();f.provider(()=>({backups:[{...stat(),newest_mtime_ns:f.clock.now}],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}],main:{cpu_seconds:f.clock.now,open_raw_pdfs:['workspace/reading/hash/raw/source.pdf']}}));let v;v=f.view(async()=>{await f.apply(v);throw Error('Render frame was disposed before the request completed')});await assert.rejects(f.api.runCheck(v),/bounded pre-journal/);const d=f.api.flowState().renderer_disposal_waits[0];assert.equal(d.deadline,d.backup.last_progress_at+120000);assert(f.clock.now<600000);assert.equal(f.calls(),1);
  });
  await check('continuous real file growth still has an absolute ten-minute backup ceiling',async()=>{
    const f=fixture();f.clock.step=60000;f.provider(()=>({backups:[stat(f.clock.now/60000+1,f.clock.now+1)],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}]}));let v;v=f.view(async()=>{await f.apply(v);throw Error('Render frame was disposed before the request completed')});await assert.rejects(f.api.runCheck(v),/bounded pre-journal/);const d=f.api.flowState().renderer_disposal_waits[0];assert.equal(d.deadline,d.backup.started_at+600000);assert.equal(f.calls(),1);
  });
  await check('a backup concurrent with an original live worker is reported as a contradiction',async()=>{
    const f=fixture();f.api.candidate(after.runtimeId);f.provider(()=>({backups:[stat()],backup_names:[backupName],processes_complete:true,old_processes:[old]}));await assert.rejects(f.api.waitForBackup(f.context(),f.disposal()),/original worker identity is still alive/);
  });
  await check('PID reuse does not turn a different process into a live old worker',async()=>{
    const f=fixture();f.api.candidate(after.runtimeId);f.provider(()=>({backups:[stat()],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false,pid_reused:true}]}));const d=f.disposal();await f.api.waitForBackup(f.context(),d);assert.equal(d.worker_state,'old-workers-stopped');assert.equal(d.deadline,120000);
  });
  await check('missing candidate, baseline or ambiguous backup identities do not grant extra time',async()=>{
    for(const kind of ['candidate','baseline','ambiguous']){const f=fixture(),c=f.context();if(kind!=='candidate')f.api.candidate(after.runtimeId);if(kind==='baseline')c.names=null;f.provider(()=>({backups:kind==='ambiguous'?[stat(),{...stat(),name:backupName+'1'}]:[stat()],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}]}));const d=f.disposal();await f.api.waitForBackup(c,d);assert.equal(d.deadline,60000)}
  });
  await check('an incomplete metadata scan cannot renew time but preserves prior bounded progress credit',async()=>{
    const f=fixture(),c=f.context(),d=f.disposal();f.api.candidate(after.runtimeId);f.provider(()=>({backups:[stat()],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}]}));await f.api.waitForBackup(c,d);f.clock.now=70000;f.provider(()=>({backups:[{...stat(100,10000),scan_complete:false}],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}]}));d.deadline=60000;await f.api.waitForBackup(c,d);assert.equal(d.deadline,120000);assert.equal(c.last_progress_at,0);
  });
  await check('backup removal before a transaction fails instead of granting more time',async()=>{
    const f=fixture(),c=f.context(),d=f.disposal();f.api.candidate(after.runtimeId);f.provider(()=>({backups:[stat()],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}]}));await f.api.waitForBackup(c,d);f.clock.now=10000;f.provider(()=>({backups:[],backup_names:[],processes_complete:true,old_processes:[{...old,alive:false}]}));await assert.rejects(f.api.waitForBackup(c,d),/backup disappeared/);
  });
  await check('real native warnings during sampling fail promptly and retain the passive evidence',async()=>{
    const f=fixture();f.provider(()=>{if(f.clock.now>=20000)void f.api.warning().catch(()=>{});return {backups:[stat(f.clock.now/10000+1,f.clock.now+1)],backup_names:[backupName],processes_complete:true,old_processes:[{...old,alive:false}]}});let v,error;v=f.view(async()=>{await f.apply(v);throw Error('Render frame was disposed before the request completed')});try{await f.api.runCheck(v)}catch(value){error=value}assert.match(String(error),/备份实际失败/);f.api.fail(error);const receipt=JSON.parse(fs.readFileSync(f.output+'.error.json'));assert(receipt.backup_diagnostics.length>=2);assert.match(receipt.native_error,/source I\/O error/);assert.equal(f.calls(),1);assert(f.clock.now<60000);
  });
  await check('the exact embedded helper inventories real local files and excludes old or other backups',()=>{
    const f=fixture();for(const name of [backupName,'before-other-1000','before-'+after.runtimeId+'-999'])f.write('backups/'+name+'/data/file.json',{value:name});
    const run=old_processes=>{localProbes++;return JSON.parse(childProcess.execFileSync(process.env.PYTHON||'python3',['-X','utf8','-c',f.api.backupProbe,JSON.stringify({home:f.dir,pid:process.pid,candidate:after.runtimeId,baseline:['before-'+after.runtimeId+'-999'],old_processes})],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},timeout:5000}))};
    const result=run([]);assert.equal(result.backups.length,1);assert.equal(result.backups[0].name,backupName);assert.equal(result.backups[0].files,1);assert.equal(result.backups[0].scan_complete,true);assert(result.backups[0].logical_bytes>0);assert(source.indexOf(" root=home/'backups'")<source.indexOf(' import psutil'));
    if(result.processes_complete){const original=result.main;const reused=run([{...original,created:original.created-1}]);assert.equal(reused.old_processes[0].pid_reused,true);assert.equal(reused.old_processes[0].alive,false);assert.equal(run([original]).old_processes[0].alive,true);processProbeVerified=true;}
    fs.writeFileSync(__dirname+'/UPDATE-FLOW-BACKUP-LOCAL-PROBE.json',JSON.stringify(result,null,2)+'\n');
  });
  await check('all original installation, signature, transaction, data and UI assertions remain unchanged',()=>{
    const block=(s,a,b)=>s.slice(s.indexOf(a),s.indexOf(b));assert.equal(block(source,'function connectionTimeout(','function flowState('),block(baseline,'function connectionTimeout(','function flowState('));assert.equal(block(source,'      const updated = JSON.parse','      if (needsRestart) {'),block(baseline,'      const updated = JSON.parse','      if (needsRestart) {'));assert.equal(block(source,'    const after = JSON.parse','    await runCheck(view,true);'),block(baseline,'    const after = JSON.parse','    await runCheck(view,true);'));
  });
  fs.writeFileSync(__dirname+'/UPDATE-FLOW-BACKUP-SELFCHECK.json',JSON.stringify({passed:true,checks:checks.length,names:checks,network_calls:0,native_installs:0,local_read_only_python_probes:localProbes,process_probe_verified:processProbeVerified,prior_suites_repeated:false,scope:'Only new backup/worker control simulations and local passive metadata/process probes; no native update success claimed.'},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1});
