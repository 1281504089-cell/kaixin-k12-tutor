import assert from 'node:assert/strict';
import { generateKeyPairSync, sign, createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { spawn, execFileSync } from 'node:child_process';
import { setTimeout as pause } from 'node:timers/promises';
import { canonicalManifest } from '../src/bundles.mjs';
import { stageBundledShell, applyBundledShell } from '../src/shell-update.mjs';

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-signed-launcher-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const profileRoot = path.join(root, 'profile');
  const runtimeRoot = path.join(profileRoot, 'runtimes', 'candidate');
  const bundle = path.join(root, 'Scholar.app');
  const app = path.join(bundle, 'Contents/Resources/app');
  const appExecutable = path.join(bundle, 'Contents/MacOS/Scholar');
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  await mkdir(path.join(runtimeRoot, 'launcher/src'), { recursive: true });
  await mkdir(path.join(app, 'assets'), { recursive: true });
  await mkdir(path.join(app, 'src'));
  await mkdir(path.dirname(appExecutable), { recursive: true });
  await mkdir(path.join(bundle, 'Contents/_CodeSignature'));
  await mkdir(path.join(profileRoot, 'workspace'));
  await writeFile(path.join(profileRoot, 'workspace/study.json'), 'KEEP CHAT AND SETTINGS');
  await writeFile(path.join(app, 'package.json'), JSON.stringify({ name: 'kaixin-super-scholar' }));
  await writeFile(path.join(app, 'assets/runtime-public.pem'), publicKey.export({ type: 'spki', format: 'pem' }));
  await writeFile(appExecutable, 'OLD EXECUTABLE');
  await writeFile(path.join(bundle, 'Contents/_CodeSignature/CodeResources'), 'OLD SIGNATURE');
  const signed = value => ({ ...value, signature: sign(null, Buffer.from(canonicalManifest(value)), privateKey).toString('base64') });
  const runtime = signed({ formatVersion: 1, protocolVersion: 1, platform: 'darwin', arch: 'x64',
    runtimeId: 'candidate', archive: 'core.tar.gz', sha256: 'a'.repeat(64), commit: 'b'.repeat(40), builtAt: 2000 });
  await writeFile(path.join(runtimeRoot, 'installed.json'), JSON.stringify(runtime));
  const files = [];
  for (const name of ['main.mjs', 'entry.mjs', 'update-bridge.cjs', 'shell-update.mjs']) {
    const bytes = Buffer.from('// NEW ' + name);
    await writeFile(path.join(runtimeRoot, 'launcher/src', name), bytes);
    await writeFile(path.join(app, 'src', name), '// OLD ' + name);
    files.push({ file: 'src/' + name, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') });
  }
  const manifest = signed({ formatVersion: 1, coreCommit: runtime.commit, buildId: 'verified-shell', files });
  const manifestFile = path.join(runtimeRoot, 'launcher/manifest.json');
  await writeFile(manifestFile, JSON.stringify(manifest));
  return { root, profileRoot, runtimeRoot, app, appExecutable, bundle, runtime, manifest, manifestFile, signed,
    context: { profileRoot, runtimeRoot, appExecutable, appPid: 2147483647 },
    options: { platform: 'darwin', architecture: 'x64', run: async () => {} } };
}

test('stages without touching live code, then installs only after exit and keeps a backup', async t => {
  const f = await fixture(t);
  assert.equal((await stageBundledShell(f.context, f.options)).restartRequired, true);
  assert.equal(await readFile(path.join(f.app, 'src/main.mjs'), 'utf8'), '// OLD main.mjs');
  const result = await applyBundledShell(f.context, f.options);
  assert.equal(result.status, 'applied');
  assert.equal(await readFile(path.join(f.app, 'src/main.mjs'), 'utf8'), '// NEW main.mjs');
  assert.equal(await readFile(path.join(result.backup, 'previous-src/main.mjs'), 'utf8'), '// OLD main.mjs');
  assert.equal(await readFile(path.join(f.profileRoot, 'workspace/study.json'), 'utf8'), 'KEEP CHAT AND SETTINGS');
  assert.equal((await stageBundledShell(f.context, f.options)).restartRequired, false);
});

test('a bad signature, mixed core batch, path traversal or modified source never reaches the application', async t => {
  for (const change of [
    m => ({ ...m, signature: 'invalid' }),
    (m, f) => f.signed({ ...m, coreCommit: 'c'.repeat(40) }),
    (m, f) => f.signed({ ...m, files: [...m.files, { file: '../outside.mjs', bytes: 1, sha256: 'a'.repeat(64) }] }),
    (m, f) => f.signed({ ...m, files: m.files.map((row, i) => i ? row : { ...row, sha256: '0'.repeat(64) }) }),
  ]) {
    const f = await fixture(t);
    await writeFile(f.manifestFile, JSON.stringify(change(f.manifest, f)));
    await assert.rejects(stageBundledShell(f.context, f.options));
    assert.equal(await readFile(path.join(f.app, 'src/main.mjs'), 'utf8'), '// OLD main.mjs');
  }
});

test('refuses a running process and payload symlinks', async t => {
  const f = await fixture(t);
  await assert.rejects(applyBundledShell({ ...f.context, appPid: process.pid }, f.options), /Exit the application/);
  const file = path.join(f.runtimeRoot, 'launcher/src/main.mjs');
  await rm(file);
  await symlink(path.join(f.app, 'src/main.mjs'), file);
  await assert.rejects(stageBundledShell(f.context, f.options), /symlink/);
});

test('an exited macOS process awaiting parent reap cannot block a verified launcher replacement', { skip: process.platform === 'win32', timeout: 10000 }, async t => {
  const f = await fixture(t);
  const holder = spawn(process.env.PYTHON || 'python3', ['-u', '-c', 'import os,sys\npid=os.fork()\nif pid==0: os._exit(0)\nprint(pid,flush=True)\nsys.stdin.readline()\nos.waitpid(pid,0)'], { stdio: ['pipe', 'pipe', 'inherit'] });
  holder.stdin.on('error', () => {});
  t.after(() => {
    const timer = setTimeout(() => holder.kill('SIGKILL'), 1000);
    holder.once('exit', () => clearTimeout(timer));
    holder.stdin.end('\n');
  });
  const pid = await new Promise((resolve, reject) => {
    holder.once('error', reject);
    holder.once('exit', () => reject(new Error('Zombie fixture exited before its PID was read')));
    holder.stdout.once('data', value => resolve(Number(value.toString().trim())));
  });
  assert(Number.isSafeInteger(pid) && pid > 0);
  const deadline = Date.now() + 2000;
  while (!execFileSync('/bin/ps', ['-p', String(pid), '-o', 'stat='], { encoding: 'utf8' }).trim().startsWith('Z')) {
    assert(Date.now() < deadline, 'The fixture did not become a real zombie');
    await pause(20);
  }
  assert.doesNotThrow(() => process.kill(pid, 0));
  assert.equal((await applyBundledShell({ ...f.context, appPid: pid }, f.options)).status, 'applied');
  assert.equal(await readFile(path.join(f.profileRoot, 'workspace/study.json'), 'utf8'), 'KEEP CHAT AND SETTINGS');
});

test('codesign failure restores the source, executable and signature and keeps study data', async t => {
  const f = await fixture(t);
  await stageBundledShell(f.context, f.options);
  await assert.rejects(applyBundledShell(f.context, { ...f.options, run: async () => {
    await writeFile(f.appExecutable, 'SIMULATED SIGNATURE WRITE');
    throw new Error('codesign denied');
  } }), /codesign denied/);
  assert.equal(await readFile(path.join(f.app, 'src/main.mjs'), 'utf8'), '// OLD main.mjs');
  assert.equal(await readFile(f.appExecutable, 'utf8'), 'OLD EXECUTABLE');
  assert.equal(await readFile(path.join(f.bundle, 'Contents/_CodeSignature/CodeResources'), 'utf8'), 'OLD SIGNATURE');
  assert.equal(await readFile(path.join(f.profileRoot, 'workspace/study.json'), 'utf8'), 'KEEP CHAT AND SETTINGS');
  assert.equal(JSON.parse(await readFile(path.join(f.profileRoot, 'launcher-update.json'))).status, 'failed');
});

test('a core rollback cannot downgrade a newer signed launcher', async t => {
  const f = await fixture(t);
  await writeFile(path.join(f.profileRoot, 'launcher-update.json'), JSON.stringify({ runtime: f.signed({ ...f.runtime, builtAt: 3000 }) }));
  assert.equal((await stageBundledShell(f.context, f.options)).status, 'kept-newer');
  assert.equal((await applyBundledShell(f.context, f.options)).status, 'kept-newer');
  assert.equal(await readFile(path.join(f.app, 'src/main.mjs'), 'utf8'), '// OLD main.mjs');
});
