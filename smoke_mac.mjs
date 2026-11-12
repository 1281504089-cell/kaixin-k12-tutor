import { spawn, execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { loadTarget } from './student-source/apps/desktop/scripts/lib/target.mjs';
const target = await loadTarget();
const {probe}=await import('./student-source/apps/desktop/src/processes.mjs');
let backend,frontend;
const root = process.cwd();
const bundle = path.join(root, `apps/desktop/out/开心动力超级学霸-darwin-${target.arch}/开心动力超级学霸.app`);
const home = await mkdtemp(path.join(os.tmpdir(), 'KX 安装体验 '));
const log = path.join(home, 'logs/runtime.log');
const app = spawn(path.join(bundle, 'Contents/MacOS/开心动力超级学霸'), [], {env:{...process.env,OPEN_DEEPTUTOR_TEST_HOME:home,PATH:'/usr/bin:/bin:/usr/sbin:/sbin'},stdio:'ignore',detached:true});
try {
  const deadline=Date.now()+900000;
  while(Date.now()<deadline) {
    assert.equal(app.exitCode,null,'Installed app exited before becoming ready');
    let text='';try{text=await readFile(log,'utf8')}catch{}
    assert.doesNotMatch(text,/Desktop startup failed:/);
    backend=/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/.exec(text)?.[1];
    frontend=/Local:\s+(http:\/\/127\.0\.0\.1:\d+)/.exec(text)?.[1];
    if(backend&&frontend) { try {
      const health=await fetch(backend+'/health/ready',{signal:AbortSignal.timeout(5000)});
      const page=await fetch(frontend,{signal:AbortSignal.timeout(5000)});
      const settings=await fetch(frontend+'/api/settings/ui',{signal:AbortSignal.timeout(5000)});
      if(health.ok&&page.ok&&settings.ok)break;
    } catch{} }
    await new Promise(resolve=>setTimeout(resolve,2000));
  }
  assert.ok(backend&&frontend,'App did not expose local services');
  const books=await (await fetch(frontend+'/api/student/textbooks')).json();
  assert.equal(books.books.length,136);
  const profile=await (await fetch(frontend+'/api/settings/ui')).json();
  assert.equal(profile.language,'zh','A fresh install must use a Chinese interface');
  assert.equal(profile.response_language,'zh');
  execFileSync('python', [path.resolve(root, '../verify-installed-voice.py'), '--profile', home,
    '--source', root, '--output', path.join(target.local, 'installed-voice-smoke.json')], { stdio: 'inherit' });
  await writeFile(path.join(target.local,'installed-app-smoke.json'),JSON.stringify({target:target.id,launch:'passed',ui:'passed',api:'passed',language:profile.language,textbooks:136,freshProfile:true,developerPATH:'absent',system:os.release()},null,2));
} finally {
  try { process.kill(-app.pid,'SIGTERM'); } catch {}
  await new Promise(resolve=>{if(app.exitCode!==null)resolve();else{const t=setTimeout(()=>{try { process.kill(-app.pid,'SIGKILL'); } catch {} resolve()},30000);app.once('exit',()=>{clearTimeout(t);resolve()})}});
  const deadline=Date.now()+20000;
  while(Date.now()<deadline && ((backend&&await probe(backend+'/health/ready'))||(frontend&&await probe(frontend)))) await new Promise(resolve=>setTimeout(resolve,500));
  if(backend) assert.equal(await probe(backend+'/health/ready'),false,'Backend survived app termination');
  if(frontend) assert.equal(await probe(frontend),false,'Frontend survived app termination');
  await rm(home,{recursive:true,force:true});
}
