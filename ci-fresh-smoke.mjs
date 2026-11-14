import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { readFile, writeFile, mkdir, access } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [executable, resources, home, evidence] = process.argv.slice(2).map(value => path.resolve(value));
assert.equal(process.platform, process.env.KX_EXPECTED_PLATFORM);
assert.equal(process.arch, process.env.KX_EXPECTED_ARCH);
await mkdir(home, { recursive: true });
const log = path.join(home, 'logs/runtime.log');
const { verifyManifest, sha256 } = await import(pathToFileURL(path.join(resources, 'app/src/bundles.mjs')));
const key = await readFile(path.join(resources, 'app/assets/runtime-public.pem'));
const base = verifyManifest(JSON.parse(await readFile(path.join(resources, 'seed/runtime.json'))), key);
const included = verifyManifest(JSON.parse(await readFile(path.join(resources, 'update/runtime.json'))), key);
assert.equal(await sha256(path.join(resources, 'update', included.archive)), included.sha256);
const operatingPath = process.platform === 'win32'
  ? [process.env.SystemRoot, path.join(process.env.SystemRoot, 'System32'), path.join(process.env.SystemRoot, 'System32/Wbem')].join(';')
  : '/usr/bin:/bin:/usr/sbin:/sbin';
let backend, frontend, child, profile, books, active, passed = false;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function get(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  assert.equal(response.status, 200, url);
  return response;
}
async function responsive(url) {
  try { return (await fetch(url, { signal: AbortSignal.timeout(1500) })).ok; }
  catch { return false; }
}
try {
  const started = Date.now();
  child = spawn(executable, [], { detached: process.platform !== 'win32', stdio: 'ignore',
    env: { ...process.env, OPEN_DEEPTUTOR_TEST_HOME: home, PATH: operatingPath } });
  let spawnError;
  child.once('error', error => { spawnError = error; });
  let ready = false;
  while (Date.now() - started < 15 * 60 * 1000) {
    if (spawnError) throw spawnError;
    assert.equal(child.exitCode, null, 'Installed app exited before becoming ready');
    let text = '';
    try { text = await readFile(log, 'utf8'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    assert.doesNotMatch(text, /Desktop startup failed:|UnicodeEncodeError|ENOSPC/);
    backend = /Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/.exec(text)?.[1];
    frontend = /Local:\s+(http:\/\/127\.0\.0\.1:\d+)/.exec(text)?.[1];
    if (backend && frontend && await responsive(backend + '/health/ready') && await responsive(frontend + '/api/settings/ui')) {
      ready = true;
      break;
    }
    await pause(2000);
  }
  assert.ok(ready, 'Installed app did not become ready before the deadline');
  active = verifyManifest(JSON.parse(await readFile(path.join(home, 'active.json'))), key);
  assert.equal(active.runtimeId, included.runtimeId, 'Fresh install did not select its included current core');
  profile = await (await get(frontend + '/api/settings/ui')).json();
  assert.equal(profile.language, 'zh');
  assert.equal(profile.response_language, 'zh');
  books = (await (await get(frontend + '/api/student/textbooks')).json()).books;
  assert.equal(books.length, 136);
  const html = await (await get(frontend + '/chat')).text();
  assert.match(html, /开心动力超级学霸/);
  const opened = await fetch(frontend + '/api/student/textbooks/' + books[0].id + '/open', {
    method: 'POST', signal: AbortSignal.timeout(30000),
  });
  assert.equal(opened.status, 200);
  const reading = await opened.json();
  assert.match(reading.url, /^\/learning\/reading\//);
  await get(frontend + reading.url);
  const runtime = path.join(home, 'runtimes', active.runtimeId);
  const native = path.join(home, 'runtimes', base.runtimeId);
  const python = path.join(native, process.platform === 'win32' ? 'python/python.exe' : 'python/bin/python3');
  const node = path.join(native, process.platform === 'win32' ? 'node/node.exe' : 'node/bin/node');
  const catalog = path.join(home, 'workspace/data/user/workspace/student-textbooks/catalog.json');
  await access(catalog);
  const code = `
import json
from pathlib import Path
import pymupdf
from deeptutor.services.student_learning.textbooks import library_root
from deeptutor.reading import ReadingStore
root=library_root(); books=json.loads((root/'catalog.json').read_text())['books']
store=ReadingStore(root.parent/'reading')
checked=0
for book in books:
 raw=store.raw_path(book['id']); assert raw and raw.is_file(), book['id']
 with pymupdf.open(raw) as pdf:
  assert len(pdf)==book['page_count'],book['id']
  if checked==0: assert len(pdf[0].get_pixmap(matrix=pymupdf.Matrix(.2,.2)).samples)>0
 checked+=1
print(json.dumps({'pdf_files':checked,'first_page_rendered':True}))
`;
  const proof = execFileSync(python, ['-c', code], { encoding: 'utf8', timeout: 120000,
    env: { ...process.env, PATH: operatingPath, PYTHONPATH: path.join(runtime, 'core'),
      DEEPTUTOR_HOME: path.join(home, 'workspace'), PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1' } });
  const pdf = JSON.parse(proof.trim().split('\n').at(-1));
  assert.equal(pdf.pdf_files, 136);
  const speech = [];
  const audio = await readFile(path.join(runtime, 'core/scripts/fixtures/student-stt-cn.webm'));
  for (let attempt = 0; attempt < 2; attempt++) {
    const form = new FormData();
    form.append('file', new Blob([audio], { type: 'audio/webm' }), 'synthetic-chinese.webm');
    const started = Date.now();
    const response = await fetch(frontend + '/api/voice/stt?local=true', {
      method: 'POST', body: form, signal: AbortSignal.timeout(180000),
    });
    const result = await response.json();
    assert.equal(response.status, 200, JSON.stringify(result));
    assert.match(result.text, /数学题/);
    assert.match(result.text, /分之/);
    speech.push({ milliseconds: Date.now() - started, spoken_audio_decoded: true });
  }
  const attachmentProof = execFileSync(python, [path.join(process.cwd(), 'ci-attachment-native.py'), frontend, path.join(evidence, 'attachments.json'), backend], {
    encoding: 'utf8', timeout: 480000, env: { ...process.env, PYTHONPATH: path.join(runtime, 'core'),
      DEEPTUTOR_HOME: path.join(home, 'workspace'), DEEPTUTOR_LOCAL_AI: path.join(native, 'support/local-ai'),
      DEEPTUTOR_FONT_DIR: path.join(native, 'support/fonts'), PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1',
      OMP_NUM_THREADS: '2', OPENBLAS_NUM_THREADS: '2' } });
  const attachments = JSON.parse(attachmentProof.trim().split('\n').at(-1));
  assert.equal(attachments.scanned_pdf_retrievable, true);
  assert.equal(attachments.raw_originals_verified, true);
  const reportProof = execFileSync(python, [path.join(process.cwd(), 'native-report-smoke.py'),
    '--core-dir', path.join(runtime, 'core'), '--node', node,
    '--out', path.join(evidence, 'reports.json')], {
    encoding: 'utf8', timeout: 180000,
    env: { ...process.env, PATH: operatingPath, PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1' },
  });
  const studyReports = JSON.parse(reportProof.trim().split('\n').at(-1));
  assert.equal(studyReports.passed, true);
  assert.equal(studyReports.cases.length, 9);
  assert.equal(studyReports.real_model_calls, 0);
  // Exercise the installed launcher's automatic compatibility selection without altering live feeds.
  const { findReleaseUpdate, downloadReleaseUpdate } = await import(pathToFileURL(path.join(resources, 'app/src/release-updates.mjs')));
  const trace = [];
  const publicFetch = async (url, options) => { trace.push(url.pathname); return fetch(url, options); };
  const offered = await findReleaseUpdate(process.platform === 'win32' ? 'windows-x64' : `macos-${process.arch}`,
    base, key, publicFetch, AbortSignal.timeout(30000));
  assert.ok(offered);
  assert.equal(offered.baseRuntimeId, base.runtimeId, 'A new full installation must select its small code update');
  assert.ok(offered.builtAt > (base.builtAt ?? 0));
  const currentOffer = await findReleaseUpdate(process.platform === 'win32' ? 'windows-x64' : `macos-${process.arch}`,
    included, key, publicFetch, AbortSignal.timeout(30000));
  assert.ok(!currentOffer || currentOffer.builtAt > included.builtAt, 'Checking a new install must never downgrade its bundled core');
  const inbox = path.join(home, 'automatic-small-update');
  await mkdir(inbox);
  await downloadReleaseUpdate(offered, inbox, () => {}, publicFetch, AbortSignal.timeout(180000));
  assert.equal(await sha256(path.join(inbox, offered.archive)), offered.sha256);
  assert.equal(trace.some(item => item.includes('kaixin-bridge-')), false);
  await writeFile(path.join(evidence, 'app.json'), JSON.stringify({
    native_platform: process.platform, native_arch: process.arch, runtime_id: active.runtimeId,
    core_commit: included.commit, fresh_profile: true, developer_tools_on_path: false,
    language: profile.language, textbooks: books.length, pdf, local_spoken_stt: speech,
    study_reports: studyReports,
    reading_page: 'passed', current_core_included: true,
    automatic_small_update_selection: 'passed', automatic_small_update_download: 'passed',
    compatibility_runtime_downloaded: false, real_keys_used: false,
  }, null, 2));
  passed = true;
} finally {
  if (child?.pid && child.exitCode === null) {
    if (process.platform === 'win32') {
      try {
        execFileSync(path.join(process.env.SystemRoot, 'System32/taskkill.exe'), ['/PID', String(child.pid), '/T', '/F']);
      } catch (error) {
        // taskkill can report a decoder that exited while its process tree was being stopped.
        console.warn('Process-tree cleanup returned status ' + error.status + '; checking actual exit and service shutdown.');
      }
      await Promise.race([new Promise(resolve => child.once('exit', resolve)), pause(20000)]);
      assert.notEqual(child.exitCode, null, 'Installed app is still running after cleanup');
    } else {
      process.kill(-child.pid, 'SIGTERM');
      await Promise.race([new Promise(resolve => child.once('exit', resolve)), pause(20000)]);
      if (child.exitCode === null) process.kill(-child.pid, 'SIGKILL');
    }
  }
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline && ((backend && await responsive(backend + '/health/ready')) || (frontend && await responsive(frontend)))) await pause(500);
  if (backend) assert.equal(await responsive(backend + '/health/ready'), false);
  if (frontend) assert.equal(await responsive(frontend), false);
  try { await writeFile(path.join(evidence, 'runtime.log'), await readFile(log)); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (passed) console.log('PASS: installed native app, 136 PDFs, Chinese, small automatic update, and exit');
}
