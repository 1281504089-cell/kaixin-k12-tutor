import assert from 'node:assert/strict';
import { verify } from 'node:crypto';
import { constants } from 'node:fs';
import { access, copyFile, cp, mkdir, mkdtemp, readFile, realpath, rename, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { canonicalManifest, sha256, verifyManifest } from './bundles.mjs';

const exec = promisify(execFile);
const stateName = 'launcher-update.json';
const required = ['src/main.mjs', 'src/entry.mjs', 'src/update-bridge.cjs', 'src/shell-update.mjs'];

async function readJSON(file) {
  try { return JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

async function save(file, value) {
  await writeFile(file + '.tmp', JSON.stringify(value, null, 2), { mode: 0o600 });
  await rename(file + '.tmp', file);
}

async function matches(root, files) {
  for (const row of files) {
    try { if (await sha256(path.join(root, row.file)) !== row.sha256) return false; }
    catch (error) { if (error.code === 'ENOENT') return false; throw error; }
  }
  return true;
}

async function load(context, platform, architecture) {
  const runtimeRoot = await realpath(context.runtimeRoot);
  const profileRoot = await realpath(context.profileRoot);
  const appExecutable = await realpath(context.appExecutable);
  assert.equal(path.dirname(path.dirname(runtimeRoot)), profileRoot, 'Untrusted runtime location');
  assert.equal(path.basename(path.dirname(runtimeRoot)), 'runtimes');
  assert(['darwin', 'win32'].includes(platform), 'Unsupported desktop platform');
  const appRoot = platform === 'darwin' ? path.resolve(path.dirname(appExecutable), '../..') : path.dirname(appExecutable);
  const app = path.join(appRoot, platform === 'darwin' ? 'Contents/Resources/app' : 'resources/app');
  assert.equal((await readJSON(path.join(app, 'package.json')))?.name, 'kaixin-super-scholar', 'Wrong application');
  const key = await readFile(path.join(app, 'assets/runtime-public.pem'));
  const runtime = verifyManifest(await readJSON(path.join(runtimeRoot, 'installed.json')), key, architecture, platform);
  assert.equal(path.basename(runtimeRoot), runtime.runtimeId);
  const payload = path.join(runtimeRoot, 'launcher');
  const manifest = await readJSON(path.join(payload, 'manifest.json'));
  assert(manifest && verify(null, Buffer.from(canonicalManifest(manifest)), key, Buffer.from(manifest.signature ?? '', 'base64')), 'Invalid launcher signature');
  assert.equal(manifest.formatVersion, 1);
  assert.equal(manifest.coreCommit, runtime.commit, 'Launcher and core batches differ');
  assert.match(manifest.buildId, /^[a-zA-Z0-9._-]{1,100}$/);
  assert(Array.isArray(manifest.files) && manifest.files.length <= 64);
  assert(required.every(name => manifest.files.some(row => row.file === name)), 'Incomplete launcher');
  const names = new Set();
  let size = 0;
  for (const row of manifest.files) {
    assert(/^src\/[a-zA-Z0-9._-]+\.(?:mjs|cjs|js|css|html)$/.test(row.file), 'Invalid launcher path');
    assert(!names.has(row.file), 'Duplicate launcher path'); names.add(row.file);
    assert(/^[a-f0-9]{64}$/.test(row.sha256) && Number.isSafeInteger(row.bytes) && row.bytes > 0 && row.bytes < 4 * 1024 ** 2);
    const file = path.join(payload, row.file);
    assert.equal(await realpath(file), file, 'Launcher symlink is not permitted');
    assert.equal((await stat(file)).size, row.bytes);
    assert.equal(await sha256(file), row.sha256, 'Launcher checksum mismatch');
    size += row.bytes;
  }
  assert(size < 4 * 1024 ** 2, 'This carrier only updates launcher scripts');
  return { runtimeRoot, profileRoot, appExecutable, appRoot, app, payload, manifest, runtime, key,
    stateFile: path.join(profileRoot, stateName) };
}

export async function stageBundledShell(context, { platform = process.platform, architecture = process.arch } = {}) {
  const loaded = await load(context, platform, architecture);
  const { app, manifest, runtime, key, stateFile, appRoot } = loaded;
  const prior = await readJSON(stateFile);
  if (prior?.runtime) {
    const previous = verifyManifest(prior.runtime, key, architecture, platform);
    if (previous.builtAt > runtime.builtAt) return { status: 'kept-newer', restartRequired: false };
  }
  const current = await matches(app, manifest.files);
  if (!current) {
    await access(app, constants.W_OK);
    await access(path.dirname(appRoot), constants.W_OK);
  }
  const result = { ...prior, ...context, runtime, buildId: manifest.buildId,
    status: current ? 'current' : 'ready', restartRequired: !current, error: current ? '' : prior?.error ?? '' };
  await save(stateFile, result);
  return { status: result.status, restartRequired: result.restartRequired, buildId: manifest.buildId };
}

export async function applyBundledShell(context, { platform = process.platform, architecture = process.arch, run = exec } = {}) {
  const { app, appRoot, appExecutable, payload, manifest, runtime, stateFile, key } = await load(context, platform, architecture);
  const prior = await readJSON(stateFile);
  if (prior?.runtime && verifyManifest(prior.runtime, key, architecture, platform).builtAt > runtime.builtAt) {
    return { status: 'kept-newer' };
  }
  assert(Number.isSafeInteger(context.appPid) && context.appPid > 0);
  let running = false;
  try { process.kill(context.appPid, 0); running = true; } catch (error) { if (error.code !== 'ESRCH') throw error; }
  // A just-exited Mac process can remain visible to signal 0 until its parent reaps it.
  if (running && platform === 'darwin') {
    try {
      const { stdout } = await exec('/bin/ps', ['-p', String(context.appPid), '-o', 'stat='], { timeout: 5000 });
      if (stdout.trim().startsWith('Z')) running = false;
    } catch {
      try { process.kill(context.appPid, 0); } catch (error) { if (error.code === 'ESRCH') running = false; else throw error; }
    }
  }
  assert(!running, 'Exit the application before replacing its launcher');
  if (await matches(app, manifest.files)) return { status: 'current' };
  const stage = await mkdtemp(path.join(path.dirname(appRoot), '.kaixin-launcher-'));
  const replacement = path.join(stage, 'new-src'), backup = path.join(stage, 'previous-src');
  const signature = path.join(appRoot, 'Contents/_CodeSignature');
  let moved = false, installed = false;
  try {
    await mkdir(replacement);
    for (const row of manifest.files) await copyFile(path.join(payload, row.file), path.join(replacement, path.basename(row.file)));
    if (platform === 'darwin') {
      await copyFile(appExecutable, path.join(stage, 'previous-executable'), constants.COPYFILE_FICLONE);
      await cp(signature, path.join(stage, 'previous-signature'), { recursive: true });
    }
    await rename(path.join(app, 'src'), backup); moved = true;
    await rename(replacement, path.join(app, 'src')); installed = true;
    if (platform === 'darwin') {
      await run('/usr/bin/codesign', ['--force', '--sign', '-', '--preserve-metadata=entitlements,requirements,flags,runtime', appRoot], { timeout: 120000 });
      await run('/usr/bin/codesign', ['--verify', '--deep', '--strict', appRoot], { timeout: 120000 });
    }
    assert(await matches(app, manifest.files), 'Installed launcher checksum mismatch');
    const result = { ...context, runtime, buildId: manifest.buildId, status: 'applied', restartRequired: false, backup: stage };
    await save(stateFile, result);
    return { status: 'applied', buildId: manifest.buildId, backup: stage };
  } catch (error) {
    if (installed) await rename(path.join(app, 'src'), path.join(stage, 'failed-src'));
    if (moved) await rename(backup, path.join(app, 'src'));
    if (platform === 'darwin' && moved) {
      await copyFile(path.join(stage, 'previous-executable'), appExecutable);
      await rm(signature, { recursive: true, force: true });
      await cp(path.join(stage, 'previous-signature'), signature, { recursive: true });
    }
    await save(stateFile, { ...context, runtime, buildId: manifest.buildId, status: 'failed', restartRequired: true, error: error.message, backup: stage });
    throw error;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    let input = '';
    for await (const chunk of process.stdin) { input += chunk; assert(input.length < 16384, 'Launcher request too large'); }
    const context = JSON.parse(input);
    const result = process.argv[2] === '--validate' ? (await load(context, process.platform, process.arch), { verified: true })
      : process.argv[2] === '--stage' ? await stageBundledShell(context)
      : process.argv[2] === '--apply' ? await applyBundledShell(context) : assert.fail('Unknown launcher action');
    console.log(JSON.stringify(result));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
