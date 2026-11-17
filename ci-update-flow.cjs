// Test-only entry in a disposable Electron copy; production modules remain unchanged.
const { app, BrowserWindow, dialog, session } = require('electron');
const { readFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const home = process.env.OPEN_DEEPTUTOR_TEST_HOME;
const output = process.env.KX_UPDATE_FLOW_RESULT;
const stateFile = output + '.state.json';
const saved = require('node:fs').existsSync(stateFile) ? JSON.parse(readFileSync(stateFile)) : null;
const before = saved?.before ?? JSON.parse(readFileSync(path.join(home, 'active.json')));
let installed = false, current = false, accepted = saved?.accepted ?? 0, invokeError = saved?.invokeError ?? '';
let checkAttempts=saved?.check_attempts??0, currentCheckAttempts=saved?.current_check_attempts??0;
const readOnlyRetries=saved?.read_only_retry_reasons??[];
const phase = saved?.phase ?? 'old-launcher';
let stage=phase, downloadStarted=saved?.download_started??false, initialUpgrade, lastTransportError;
let shellTranslate, applyingEvidence, nativeFailure, applyPhases={},lastShellStatus=saved?.last_shell_status??null;
let selectedCandidate='',candidateEvidence;
const backupDiagnostics=saved?.backup_diagnostics??[];
const phaseBudgets={updating:60000,checking:70000,preparingUi:240000,startingCore:190000,openingSpace:250000,ready:60000};
const watchedShells=new WeakSet(), rendererDisposals=saved?.renderer_disposal_waits??[];
const needsRestart=process.env.KX_EXPECT_SHELL_RESTART==='1';
let progressVisible=saved?.download_progress_visible??false, progressWithBytes=saved?.downloaded_bytes_visible??false;
let fromPid=process.pid;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function optionalRead(name) {
  try { return readFileSync(path.join(home,name),'utf8'); } catch(error) { if(error.code==='ENOENT')return null;throw error; }
}
function connectionTimeout(error) {
  const chain=[];for(let item=error;item&&chain.length<5;item=item.cause)chain.push(item);
  if(chain.some(item=>/signature|checksum|验签|签名|校验|ENOSPC|EACCES|EPERM/i.test(String(item.message||item)+' '+String(item.code||''))))return null;
  for(const item of chain) {
    const message=String(item.message||item).replace(/^Error invoking remote method 'desktop:check-release': (?:Error: )?/,'').replace(/^Error: /,'');
    if(item.code==='UND_ERR_CONNECT_TIMEOUT')return item.code;
    if((item.code==='ETIMEDOUT'&&item.syscall==='connect')||/^connect ETIMEDOUT\b/.test(message))return 'connect ETIMEDOUT';
    if(['net::ERR_CONNECTION_TIMED_OUT','GitHub update connection timed out','核心更新未完成: GitHub update connection timed out'].includes(message))return message;
  }
  return null;
}
async function checkedFetch(fetch,url,options) {
  const tracked=['github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'].includes(new URL(url).hostname);
  if(/\.tar\.gz$/.test(new URL(url).pathname))downloadStarted=true;
  try {const response=await fetch(url,options);if(tracked)lastTransportError=null;return response;}
  catch(error){if(tracked)lastTransportError={attempt:checkAttempts,url:new URL(url).origin+new URL(url).pathname,error};throw error;}
}
function flowState() {
  return {check_attempts:checkAttempts,current_check_attempts:currentCheckAttempts,read_only_retry_reasons:readOnlyRetries,download_started:downloadStarted,download_progress_visible:progressVisible,downloaded_bytes_visible:progressWithBytes,renderer_disposal_waits:rendererDisposals,last_shell_status:lastShellStatus,native_error:nativeFailure?String(nativeFailure.stack||nativeFailure):null,backup_diagnostics:backupDiagnostics};
}
function watchShell(view) {
  if(typeof view?.send==='function'&&!watchedShells.has(view)) {
    const send=view.send.bind(view);watchedShells.add(view);
    view.send=(channel,...args)=>{const status=args[0];if(channel==='desktop:release-status'&&status?.available===true&&typeof status.runtimeId==='string'&&/^[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,100}$/.test(status.runtimeId)&&status.runtimeId!==before.runtimeId){if(selectedCandidate!==status.runtimeId)candidateEvidence={at:Date.now(),check_attempt:checkAttempts,source:'native-renderer-release-status',available:true,runtimeId:status.runtimeId};selectedCandidate=status.runtimeId;}return send(channel,...args);};
  }
  const shellURL=pathToFileURL(path.join(__dirname,'../src/index.html')).href;
  for(const win of BrowserWindow.getAllWindows()) {
    const contents=win.webContents;
    if(contents.getURL()!==shellURL||watchedShells.has(contents))continue;
    const send=contents.send.bind(contents);watchedShells.add(contents);
    contents.send=(channel,...args)=>{
      if(channel==='desktop:status') {
        const state=args[0]??{},step=state.phase==='ready'?'ready':Object.keys(phaseBudgets).find(key=>typeof shellTranslate==='function'&&state.message===shellTranslate(state.language,key));
        lastShellStatus={...state,observed_step:step,at:Date.now(),check_attempt:checkAttempts,shell_url:shellURL};
        if(state.phase==='error')nativeFailure=new Error('Native shell error: '+(state.detail||state.message));
        if(state.phase==='starting'&&typeof shellTranslate==='function'&&state.message===shellTranslate(state.language,'updating')&&accepted===1&&downloadStarted)applyingEvidence={...lastShellStatus,accepted,download_started:downloadStarted};
        if(step&&accepted===1&&downloadStarted&&applyingEvidence?.check_attempt===checkAttempts&&!applyPhases[step])applyPhases[step]=lastShellStatus;
      }
      return send(channel,...args);
    };
  }
}
const backupProbe=String.raw`
import os,sys,json,time,stat as mode
from pathlib import Path
p=json.loads(sys.argv[1]);home=Path(p['home']).resolve();out={'backup_names':[],'backups':[],'processes_complete':False,'children':[],'old_processes':[]}
try:
 root=home/'backups'
 if root.is_symlink():raise ValueError('backup root is a symlink')
 entries=list(root.iterdir()) if root.exists() else []
 out['backup_names']=[f.name for f in entries if f.is_dir() and not f.is_symlink()]
 candidate=p.get('candidate','');baseline=p.get('baseline')
 for folder in entries:
  prefix='before-'+candidate+'-'
  if not candidate or baseline is None or folder.name in baseline or not folder.name.startswith(prefix) or not folder.name[len(prefix):].isdigit():continue
  if folder.is_symlink() or not folder.is_dir():raise ValueError('invalid backup directory')
  stat={'name':folder.name,'files':0,'logical_bytes':0,'directories':0,'symlinks':0,'newest_mtime_ns':0,'scan_complete':True,'examples':[]};deadline=time.monotonic()+2
  def failed(e):stat['scan_complete']=False;stat['scan_error']=str(e)
  for directory,dirs,files in os.walk(folder,followlinks=False,onerror=failed):
   if time.monotonic()>deadline:stat['scan_complete']=False;stat['scan_error']='metadata scan exceeded two seconds';break
   stat['directories']+=1
   for name in files:
    file=Path(directory)/name
    try:
     info=file.lstat()
     if mode.S_ISLNK(info.st_mode):stat['symlinks']+=1;continue
     if not mode.S_ISREG(info.st_mode):continue
     stat['files']+=1;stat['logical_bytes']+=info.st_size;stat['newest_mtime_ns']=max(stat['newest_mtime_ns'],info.st_mtime_ns)
     if len(stat['examples'])<3:stat['examples'].append({'path':str(file.relative_to(folder)),'bytes':info.st_size})
    except OSError as e:failed(e)
  out['backups'].append(stat)
except Exception as e:out['backup_error']=str(e)
try:
 import psutil
 def row(proc,role):
  c=proc.cpu_times();status=proc.status();return {'pid':proc.pid,'ppid':proc.ppid(),'pgid':os.getpgid(proc.pid) if hasattr(os,'getpgid') else None,'created':proc.create_time(),'role':role,'status':status,'alive':proc.is_running() and status!=psutil.STATUS_ZOMBIE,'cpu_seconds':c.user+c.system}
 app=psutil.Process(p['pid']);ids={x.pid for x in app.children(recursive=True)}
 for proc in psutil.process_iter(['cwd']):
  try:
   cwd=Path(proc.info['cwd']).resolve() if proc.info['cwd'] else None
   if proc.pid not in ids and not (cwd and (cwd==home or home in cwd.parents)):continue
   args=proc.cmdline();names=[Path(a).name for a in args]
   role='supervisor' if 'supervisor.mjs' in names else 'backend' if 'deeptutor_cli.main' in args and 'serve' in args else 'frontend' if 'server.js' in names or 'dev.mjs' in names else None
   if role:out['children'].append(row(proc,role))
  except (psutil.Error,OSError):pass
 for old in p.get('old_processes',[]):
  try:
   proc=psutil.Process(old['pid']);same=abs(proc.create_time()-old['created'])<0.000001
   out['old_processes'].append(row(proc,old['role']) if same else {**old,'alive':False,'pid_reused':True})
  except psutil.NoSuchProcess:out['old_processes'].append({**old,'alive':False})
  except psutil.Error as e:out['old_processes'].append({**old,'alive':None,'error':str(e)})
 out['main']=row(app,'qa-main');out['main']['open_raw_pdfs']=[]
 try:
  for f in app.open_files():
   q=Path(f.path);parts=q.parts
   if home in q.parents and len(parts)>=4 and parts[-4]=='reading' and parts[-2]=='raw' and len(parts[-3])==64 and all(c in '0123456789abcdef' for c in parts[-3]) and q.suffix.lower()=='.pdf':out['main']['open_raw_pdfs'].append({'path':f.path,'bytes':q.stat().st_size,'fd':f.fd,'position':getattr(f,'position',None)})
 except (psutil.Error,OSError):pass
 out['processes_complete']=True
except Exception as e:out['process_error']=str(e)
print(json.dumps(out,ensure_ascii=False))
`;
async function sampleBackup(context, baseline=false) {
  const python=path.join(home,'runtimes',before.baseRuntimeId||before.runtimeId,process.platform==='win32'?'python/python.exe':'python/bin/python3');
  let result;
  try {
    const raw=await new Promise((resolve,reject)=>require('node:child_process').execFile(python,['-X','utf8','-c',backupProbe,JSON.stringify({home,pid:process.pid,candidate:selectedCandidate,baseline:baseline?null:context.names,old_processes:context.old||[]})],{timeout:5000,maxBuffer:1024*1024,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8',PYTHONDONTWRITEBYTECODE:'1'}},(error,stdout)=>error?reject(error):resolve(stdout)));
    result=JSON.parse(raw);
  } catch(error){result={probe_error:String(error.message||error)};}
  const sample={at:Date.now(),check_attempt:checkAttempts,candidate_runtime:selectedCandidate,candidate_evidence:candidateEvidence,baseline,...result};
  if(baseline){context.names=result.backup_names??null;context.old=result.children??[];context.processes_complete=result.processes_complete===true;}
  context.last=sample;context.next=Date.now()+5000;backupDiagnostics.push(sample);if(backupDiagnostics.length>64)backupDiagnostics.splice(1,1);
  writeFileSync(output+'.backup.json',JSON.stringify(backupDiagnostics,null,2));return sample;
}
async function waitForBackup(context, disposal) {
  if(!context.last||context.last.baseline||context.last.candidate_runtime!==selectedCandidate||Date.now()>=context.next)await sampleBackup(context);
  if(nativeFailure)throw nativeFailure;
  const sample=context.last,old=sample.old_processes||[],known=context.processes_complete&&context.old.length>0&&sample.processes_complete&&old.length===context.old.length&&old.every(row=>row.alive!==null);
  const alive=old.filter(row=>row.alive===true),worker=known?(alive.length?'old-worker-alive':'old-workers-stopped'):'worker-state-unknown';
  const candidates=sample.backups||[],backup=candidates.length===1&&candidates[0].scan_complete?candidates[0]:null;
  disposal.worker_state=worker;disposal.pre_journal_state=sample.probe_error||sample.backup_error?'diagnostic-unavailable':context.names===null?'backup-baseline-unavailable':!selectedCandidate?'candidate-unobserved':candidates.length>1?'ambiguous-candidate-backups':worker;disposal.backup_sample_at=sample.at;
  if(backup&&context.names!==null&&selectedCandidate) {
    if(alive.length)throw new Error('A backup exists while an original worker identity is still alive');
    if(context.backup&&context.backup!==backup.name)throw new Error('The in-progress backup identity changed');
    context.backup=backup.name;context.backup_started_at??=sample.at;
    const advanced=backup.files>(context.files||0)||backup.logical_bytes>(context.bytes||0);
    if(advanced){context.last_progress_at=sample.at;context.files=backup.files;context.bytes=backup.logical_bytes;}
    disposal.backup={...backup,started_at:context.backup_started_at,last_progress_at:context.last_progress_at??null,hard_deadline:context.backup_started_at+600000,stall_deadline:context.last_progress_at===undefined?null:context.last_progress_at+120000,worker_state:worker};
    disposal.pre_journal_state=advanced?'backup-file-progress':context.last_progress_at!==undefined?'backup-awaiting-file-progress':'backup-started-without-file-progress';
  } else if(context.backup&&sample.backup_names&&!sample.backup_names.includes(context.backup)&&!sample.backup_error)throw new Error('The in-progress backup disappeared before the testing transaction');
  if(context.last_progress_at!==undefined){disposal.phase_started_at=context.backup_started_at;disposal.phase_budget_ms=600000;disposal.deadline=Math.min(context.backup_started_at+600000,context.last_progress_at+120000);if(Date.now()>=context.backup_started_at+600000)disposal.pre_journal_state='backup-hard-limit';else if(Date.now()>=context.last_progress_at+120000)disposal.pre_journal_state='backup-stalled';}
}
function fail(error, failedStage=stage) {
  console.error(error.message||error);
  let launcher,active,tail,differences=[];
  try {launcher=JSON.parse(optionalRead('launcher-update.json'));} catch {}
  try {active=JSON.parse(optionalRead('active.json'));} catch {}
  try {tail=optionalRead('logs/runtime.log')?.slice(-18000);} catch {}
  try {
    const d=JSON.parse(readFileSync(path.join(home,'runtimes',active.runtimeId,'launcher/manifest.json')));
    for(const row of d.files) {
      let actual;try {actual=require('node:crypto').createHash('sha256').update(readFileSync(path.join(__dirname,'..',row.file))).digest('hex');}catch(e){actual=e.message;}
      if(actual!==row.sha256)differences.push({file:row.file,expected:row.sha256,actual});
    }
  } catch(e) {console.error('Evidence collection:',e.message);}
  try {writeFileSync(output+'.error.json',JSON.stringify({phase,stage:failedStage,error:String(error.stack||error),accepted,installed,current,before_runtime:before.runtimeId,invokeError,...flowState(),launcher,active:active??null,tail,differences,transport_error:lastTransportError?{attempt:lastTransportError.attempt,url:lastTransportError.url,error:String(lastTransportError.error.stack||lastTransportError.error)}:null}));}
  finally {clearTimeout(timer);app.exit(1);}
}
async function collectProgress() {
  for(const win of BrowserWindow.getAllWindows())if(win.webContents.getURL().endsWith('/update-progress.html')) {
    progressVisible=true;downloadStarted=true;
    const text=await win.webContents.executeJavaScript('document.body.innerText').catch(()=> '');
    if(/\d+\.\d+ MB/.test(text))progressWithBytes=true;
  }
}
async function runCheck(view, expectCurrent=false) {
  const backupContext={names:null,old:[]};
  for(;;) {
    if(nativeFailure)throw nativeFailure;
    checkAttempts++;if(expectCurrent)currentCheckAttempts++;
    stage=expectCurrent?'check-current':'check-install';lastTransportError=null;applyingEvidence=null;applyPhases={};selectedCandidate='';candidateEvidence=null;watchShell(view);
    if(!expectCurrent&&backupContext.names===null)await sampleBackup(backupContext,true);
    if(nativeFailure)throw nativeFailure;
    let error,done=false,disposal;
    const invocation=Promise.resolve().then(()=>view.executeJavaScript('window.kaixinDesktop.checkForUpdates()')).then(()=>{done=true;},value=>{error=value||new Error('Update check rejected without an error detail');invokeError=String(error.message||error);done=true;});
    for(;;) {
      await collectProgress();
      if(nativeFailure&&!done&&accepted===0&&!expectCurrent&&connectionTimeout(nativeFailure))await Promise.race([invocation,pause(1000)]);
      if(nativeFailure){error=nativeFailure;invokeError=String(error.message||error);}
      if(error) {
        const active=JSON.parse(readFileSync(path.join(home,'active.json'))),journal=JSON.parse(optionalRead('upgrade.json'));
        const changed=optionalRead('upgrade.json')!==initialUpgrade;
        const transaction=changed&&journal?.previous?.runtimeId===before.runtimeId&&typeof journal?.candidate?.runtimeId==='string'&&journal.candidate.runtimeId.length>0&&journal.candidate.runtimeId!==before.runtimeId&&['testing','complete'].includes(journal.phase);
        // Legacy shells close the old view after verification, before writing the journal.
        const replacing=!expectCurrent&&accepted===1&&!nativeFailure&&invokeError==='Render frame was disposed before the request completed'&&(transaction||applyingEvidence?.check_attempt===checkAttempts);
        if(replacing) {
          if(!disposal){disposal={started_at:Date.now(),pre_journal_deadline:Date.now()+60000,evidence:applyingEvidence??{source:'verified-upgrade-journal'}};rendererDisposals.push(disposal);}
          Object.assign(disposal,{journal_phase:journal?.phase??null,active_runtime:active.runtimeId,installed,last_shell:lastShellStatus});
          assert(!changed||transaction,'The renderer disposal was followed by an unexpected upgrade transaction');
          if(installed){assert(journal?.phase==='complete'&&transaction&&active.runtimeId===journal.candidate.runtimeId,'Installed confirmation does not match the completed transaction and active runtime');disposal.completed_at=Date.now();return;}
          disposal.wait_phase='pre-journal';disposal.phase_started_at=disposal.started_at;disposal.phase_budget_ms=60000;disposal.deadline=disposal.pre_journal_deadline;
          if(transaction) {
            disposal.transaction_at??=Date.now();
            const step=lastShellStatus?.observed_step,event=applyPhases[step];
            disposal.wait_phase=event&&step!=='updating'?step:'testing';
            let budget=phaseBudgets[disposal.wait_phase]??490000;
            if(disposal.wait_phase==='checking'&&require('node:fs').existsSync(path.join(home,'runtimes',journal.candidate.runtimeId,'core/deeptutor/services/student_learning/bootstrap.py'))){budget+=600000;disposal.bootstrap_module_present=true;}
            disposal.phase_budget_ms=budget;disposal.phase_started_at=disposal.wait_phase==='testing'?disposal.transaction_at:event.at;disposal.deadline=disposal.phase_started_at+budget;
          } else await waitForBackup(backupContext,disposal);
          assert(Date.now()<disposal.deadline,'The verified apply stage exceeded its bounded '+disposal.wait_phase+' wait');
          stage='await-installed-after-renderer-close';await pause(100);continue;
        }
        let status,reason=connectionTimeout(error);
        if(done&&!expectCurrent&&reason&&accepted===0&&!installed&&!current&&!downloadStarted&&!progressVisible&&readOnlyRetries.length===0&&active.runtimeId===before.runtimeId&&optionalRead('upgrade.json')===initialUpgrade) {
          try {status=await view.executeJavaScript('window.kaixinDesktop.getUpdateStatus()');}catch{}
          if(status?.available===false&&status.runtimeId===''&&[undefined,'idle'].includes(status.phase)&&[undefined,0].includes(status.received)&&[undefined,0].includes(status.total)&&accepted===0&&!installed&&!current&&!downloadStarted&&!progressVisible&&JSON.parse(readFileSync(path.join(home,'active.json'))).runtimeId===before.runtimeId&&optionalRead('upgrade.json')===initialUpgrade) {
            readOnlyRetries.push({attempt:checkAttempts,reason,invoke_error:invokeError,accepted,active_runtime_id:active.runtimeId,download_started:false,update_status:status});nativeFailure=null;break;
          }
        }
        throw error;
      }
      if(done) {assert(expectCurrent?current:installed,expectCurrent?'Current-version check returned without confirmation':'Update check returned without an installed update');return;}
      await pause(100);
    }
  }
}
dialog.showMessageBox = async (...args) => {
  const options = args.at(-1);
  if (options.message === '发现开心动力超级学霸新版') {
    accepted++;
    return { response: 1 };
  }
  if (options.message === '更新已安装') installed = true;
  else if (options.message === '已是最新版本') current = true;
  else if (options.type === 'error' || options.type === 'warning') {
    nativeFailure=new Error(options.message + ': ' + options.detail, {cause:lastTransportError?.attempt===checkAttempts?lastTransportError.error:undefined});throw nativeFailure;
  }
  return { response: 0 };
};
dialog.showErrorBox = (title, detail) => fail(new Error(title + ': ' + detail),'native-error-box');
const timer = setTimeout(() => fail(new Error('Native update flow timed out')), 1300000);
async function content() {
  for (const window of BrowserWindow.getAllWindows()) {
    const found = window.contentView.children.find(view => view.webContents?.getURL().startsWith('http://127.0.0.1:'));
    if (found && await found.webContents.executeJavaScript('Boolean(window.kaixinDesktop?.checkForUpdates)').catch(() => false)) return found.webContents;
  }
}
(async () => {
  try {
    await app.whenReady();
    const updates = session.fromPartition('kaixin-updates');
    const originalFetch = updates.fetch.bind(updates);
    updates.fetch = async (url, options) => {
      const tag = process.env.KX_CANDIDATE_TAG;
      const original = String(url);
      const mapped = original.replace('/tags/core-updates', '/tags/' + tag).replace('/download/core-updates/', '/download/' + tag + '/');
      const ciOptions = new URL(mapped).hostname === 'api.github.com' && process.env.GH_TOKEN
        ? { ...options, headers: { ...options?.headers, Authorization: `Bearer ${process.env.GH_TOKEN}` } } : options;
      const response = await checkedFetch(originalFetch,mapped,ciOptions);
      if (original.includes('/tags/core-updates') && response.ok) {
        const metadata = await response.json();
        return Response.json({ ...metadata, tag_name: 'core-updates' });
      }
      if(!needsRestart && original.includes('.tar.gz') && response.ok && response.body) {
        const paced=response.body.pipeThrough(new TransformStream({async transform(chunk,controller){await pause(20);controller.enqueue(chunk);}}));
        return new Response(paced,{status:response.status,headers:response.headers});
      }
      return response;
    };
    const nodeFetch=globalThis.fetch;
    globalThis.fetch=async(url,options)=> {
      const original=String(url),tag=process.env.KX_CANDIDATE_TAG;
      const mapped=original.replace('/tags/core-updates','/tags/'+tag).replace('/download/core-updates/','/download/'+tag+'/');
      const result=await checkedFetch(nodeFetch,mapped,new URL(mapped).hostname==='api.github.com' && process.env.GH_TOKEN
        ? {...options,headers:{...options?.headers,Authorization:`Bearer ${process.env.GH_TOKEN}`}}:options);
      if(original.includes('/tags/core-updates') && result.ok){const data=await result.json();return Response.json({...data,tag_name:'core-updates'});}
      return result;
    };
    await import(pathToFileURL(path.join(__dirname, '../src/main.mjs')));
    ({translate:shellTranslate}=await import(pathToFileURL(path.join(__dirname,'../src/i18n.mjs'))));
    await app.whenReady();
    let view;
    const readyDeadline = Date.now() + 120000;
    while (!(view = await content())) {
      assert.ok(Date.now() < readyDeadline, 'The old installed core did not open the update test interface');
      await pause(500);
    }
    if (phase === 'old-launcher') {
      await pause(1000);
      initialUpgrade=optionalRead('upgrade.json');
      await runCheck(view);
      stage='validate-installed';
      const updated = JSON.parse(readFileSync(path.join(home, 'active.json')));
      assert.notEqual(updated.runtimeId, before.runtimeId);
      assert.ok(updated.builtAt > (before.builtAt ?? 0));
      assert.equal(accepted, 1);
      const journal = JSON.parse(readFileSync(path.join(home, 'upgrade.json')));
      assert.equal(journal.phase, 'complete');
      assert.equal(journal.previous.runtimeId, before.runtimeId);
      if (needsRestart) {
      view = await content();
      const restartDeadline = Date.now() + 30000;
      while (!await view.executeJavaScript(`Array.from(document.querySelectorAll('button')).some(button=>button.textContent==='重新打开完成更新')`)) {
        assert.ok(Date.now() < restartDeadline, 'The old launcher did not receive a restart action from the signed core');
        await pause(200);
      }
      stage='await-signed-restart';
      writeFileSync(stateFile, JSON.stringify({phase:'new-launcher',before,accepted,invokeError,oldPid:process.pid,...flowState()}));
      await view.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='重新打开完成更新').click()`);
      setTimeout(() => {
        fail(new Error('The signed launcher did not reopen'),'restart-timeout');
      },90000).unref();
      return; // The signed helper must normally close and relaunch this process.
      }
    }
    stage='verify-new-launcher';
    if (needsRestart) assert.notEqual(process.pid, saved.oldPid, 'The whole application must have restarted');
    const after = JSON.parse(readFileSync(path.join(home, 'active.json')));
    const transaction = JSON.parse(readFileSync(path.join(home, 'upgrade.json')));
    if(!needsRestart) { assert.ok(progressVisible,'No visible update progress'); assert.ok(progressWithBytes,'No visible downloaded-byte feedback'); }
    const launcherDeadline = Date.now()+30000;
    let launcher;
    do {
      launcher = JSON.parse(readFileSync(path.join(home,'launcher-update.json')));
      if(launcher.status==='current') break;
      assert.ok(Date.now()<launcherDeadline, 'Launcher did not become current: '+JSON.stringify(launcher));
      await pause(200);
    } while(true);
    assert.equal(launcher.status,'current');
    assert.equal(launcher.restartRequired,false);
    const descriptor=JSON.parse(readFileSync(path.join(home,'runtimes',after.runtimeId,'launcher/manifest.json')));
    for(const row of descriptor.files) assert.equal(require('node:crypto').createHash('sha256').update(readFileSync(path.join(__dirname,'..',row.file))).digest('hex'),row.sha256);
    await pause(500);
    view = await content();
    assert.ok(view, 'Updated page did not expose the trusted desktop bridge');
    const uiDeadline = Date.now() + 60000;
    while (!await view.executeJavaScript('Boolean(document.querySelector("textarea")?.offsetHeight) && document.body.innerText.includes("默认学习助手") && !document.body.innerText.includes("加载中...")')) {
      assert.ok(Date.now() < uiDeadline, 'The updated learning interface did not finish rendering');
      await pause(200);
    }
    const menu = await view.executeJavaScript(`(() => { document.querySelector('button[aria-label="资源"]')?.click(); return document.body.innerText; })()`);
    for (const label of ['收藏夹', '学习日志', '题库', '书籍', '阅读']) assert.ok(!menu.split('\n').includes(label), label);
    await view.executeJavaScript(`document.querySelector('button[aria-label="资源"]')?.click()`);
    await require('node:fs/promises').writeFile(path.join(path.dirname(output), 'native-ui-updated.png'), (await view.capturePage()).toPNG());
    stage='ui-checks';
    const fixture = JSON.parse(readFileSync(path.join(home, 'attachment-fixture.json')));
    const library = await require('./materials-ui.cjs')(view, path.dirname(output), fixture);
    const audio = await require('./ci-chat-audio-ui.cjs')(view, path.dirname(output), fixture.audio);
    const science = await require('./science-ui.cjs').verifyScienceNative(view, path.dirname(output), fixture.science);
    const preview = await require('./ci-turn-preview.cjs')(view, path.dirname(output), fixture.science.preview);
    const k12 = await require('./ci-k12-library-ui.cjs')(view, path.dirname(output), fixture.k12, { entry: path.basename(output, '.json') });
    assert.equal(k12.passed, true);
    assert.equal(preview.passed, true);
    assert.equal(audio.passed, true);
    assert.equal(science.passed, true);
    await runCheck(view,true);
    assert.equal(current, true);
    writeFileSync(output, JSON.stringify({
      native_platform: process.platform, native_arch: process.arch,
      ...flowState(),
      entry: 'renderer IPC desktop:check-release', native_dialogs_auto_confirmed: true,
      production_main_unchanged: true, candidate_feed_routed_only_in_test: true, from_runtime: before.runtimeId, to_runtime: after.runtimeId,
      actual_download_install_backup_restart: 'passed', transaction: transaction.phase,
      check_again_current: true, signed_launcher_restarted: needsRestart, from_launcher: process.env.KX_START_LAUNCHER_BUILD??(needsRestart?'a47b05f9136ca6fb72d2f1f8a04eeb425298f358':descriptor.buildId), to_launcher: descriptor.buildId, old_pid: saved?.oldPid ?? fromPid, restarted_pid: process.pid, download_progress_visible: progressVisible, downloaded_bytes_visible: progressWithBytes, old_renderer_closed_after_update: invokeError==='Render frame was disposed before the request completed', selected_archive:after.archive, selected_base_runtime:after.baseRuntimeId??null,
      library_bulk_upload: library, chat_audio: audio, science_formulas: science, quick_preview: preview, k12_library: k12,
    }, null, 2));
    clearTimeout(timer);
    app.quit();
  } catch (error) {
    fail(error);
  }
})();
