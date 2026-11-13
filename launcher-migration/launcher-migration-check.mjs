import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { access, lstat, readFile, readdir, realpath, writeFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const exec = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const APP = '开心动力超级学霸';
const targets = { 'windows-x64': ['win32', 'x64'], 'macos-x64': ['darwin', 'x64'], 'macos-arm64': ['darwin', 'arm64'] };
export const inside = (parent, child) => { const r = path.relative(parent, child); return r === '' || (!r.startsWith(`..${path.sep}`) && r !== '..' && !path.isAbsolute(r)); };
const json = async file => JSON.parse(await readFile(file, 'utf8'));
const hash = async file => { const h = createHash('sha256'); for await (const b of createReadStream(file)) h.update(b); return h.digest('hex'); };

async function noLinks(directory) {
  let current = path.resolve(directory);
  while (true) {
    assert(!(await lstat(current)).isSymbolicLink(), 'Installation/profile path contains a symlink or junction');
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
}

export async function tree(root) {
  const result = {};
  const mac = path.basename(root) === 'Contents';
  async function walk(dir) {
    for (const name of (await readdir(dir)).sort()) {
      const file = path.join(dir, name), rel = path.relative(root, file).split(path.sep).join('/');
      if (/^(?:resources|Resources)\/app\/launcher-migration-payload.json$/.test(rel)
        || /(^|\/)_CodeSignature(\/|$)/.test(rel) || rel.endsWith('/CodeResources')
        || (mac && /^(?:MacOS|Frameworks)(\/|$)/.test(rel))) continue;
      const stat = await lstat(file);
      assert(inside(root, await realpath(file)), 'External payload symlink');
      if (stat.isSymbolicLink()) {
        const { readlink } = await import('node:fs/promises');
        result[rel] = { symlink: await readlink(file) };
      } else if (stat.isDirectory()) await walk(file);
      else { assert(stat.isFile(), 'Unsupported payload file'); result[rel] = { sha256: await hash(file), size: stat.size }; }
    }
  }
  await walk(root);
  return result;
}

export async function validateProfile(appDirectory, profile, target, isolated = false) {
  assert(targets[target], 'Unsupported target');
  const [platform, arch] = targets[target];
  const resources = path.join(appDirectory, target.startsWith('macos-') ? 'Contents/Resources' : 'resources');
  const shell = path.join(resources, 'app');
  const { verifyManifest, shouldUseBundledUpdate } = await import(pathToFileURL(path.join(shell, 'src/bundles.mjs')).href);
  const publicKey = await readFile(path.join(shell, 'assets/runtime-public.pem'), 'utf8');
  profile = await realpath(profile);
  assert(!inside(appDirectory, profile) && !inside(profile, appDirectory), 'App and profile must be separate');
  if (isolated) {
    assert.equal((await json(path.join(profile, '.launcher-migration-synthetic.json'))).synthetic, true, 'Only synthetic profiles are permitted');
    const roots = [process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, APP),
      process.env.APPDATA && path.join(process.env.APPDATA, APP),
      process.env.HOME && path.join(process.env.HOME, 'Library/Application Support', APP)].filter(Boolean);
    assert(roots.every(root => !inside(path.resolve(root), profile)), 'Real learner profile is forbidden in tests');
  }
  const verify = data => verifyManifest(data, publicKey, arch, platform);
  const seed = verify(await json(path.join(resources, 'seed/runtime.json')));
  assert.equal(seed.runtimeId, `1.7.1-77f2ba387-${arch}`, 'A genuine early full seed manifest is required');
  assert.equal(seed.commit, '77f2ba387713d23ef6af9897d393d24d84e421be');
  assert(!seed.baseRuntimeId && seed.builtAt, 'Seed must be a signed full base with its original time');
  assert.deepEqual(await readdir(path.join(resources, 'seed')), ['runtime.json'], 'Seed archives must not be embedded');
  await assert.rejects(access(path.join(resources, 'update')), error => error.code === 'ENOENT');
  const active = verify(await json(path.join(profile, 'active.json')));
  assert(!shouldUseBundledUpdate(active, seed, null), 'Bundled metadata would force a missing base installation');
  assert((active.builtAt ?? 0) >= seed.builtAt, 'Existing active runtime is older than migration seed');
  const root = path.join(profile, 'runtimes');
  const current = path.join(root, active.runtimeId);
  const installed = verify(await json(path.join(current, 'installed.json')));
  assert.equal(installed.signature, active.signature, 'Active and installed manifests differ');
  const base = active.baseRuntimeId ? path.join(root, active.baseRuntimeId) : current;
  if (active.baseRuntimeId) {
    const full = verify(await json(path.join(base, 'installed.json')));
    assert.equal(full.runtimeId, active.baseRuntimeId);
    assert(!full.baseRuntimeId, 'Native base may not be another partial update');
  }
  const layout = platform === 'win32' ? ['python/python.exe', 'node/node.exe'] : ['python/bin/python3', 'node/bin/node'];
  for (const file of [...layout.map(p => path.join(base, p)), path.join(base, 'core/deeptutor_cli/main.py'), path.join(base, 'web/server.js'),
    path.join(current, 'core/deeptutor_cli/main.py'), path.join(current, 'web/server.js')]) {
    await access(file);
    assert(inside(profile, await realpath(file)), 'Runtime path leaves the selected profile');
  }
  const transaction = await json(path.join(profile, 'upgrade.json')).catch(error => { if (error.code === 'ENOENT') return null; throw error; });
  assert(!transaction || !['testing', 'installing'].includes(transaction.phase), 'An upgrade is already in progress');
  return { target, activeRuntimeId: active.runtimeId, baseRuntimeId: active.baseRuntimeId ?? active.runtimeId,
    seedRuntimeId: seed.runtimeId, signature: 'verified', existingRuntimeReused: true, profileWritten: false };
}

export async function preflight(options) {
  const packageRoot = path.resolve(here, '../..'); // This file is embedded at resources/app/.
  const metadata = await json(path.join(here, 'launcher-migration-payload.json'));
  assert.equal(metadata.target, options.target);
  assert.deepEqual(await tree(packageRoot), metadata.files, 'Candidate payload checksum mismatch');
  const appDirectory = metadata.target.startsWith('macos-') ? path.dirname(packageRoot) : packageRoot;
  const result = await validateProfile(appDirectory, options.profile, options.target, options.requireIsolated);
  if (!options.packagePreflight) {
    assert.deepEqual(targets[options.target], [process.platform, process.arch], 'Run the installer on its native target');
    assert(options.installDir, 'A fixed installation directory is required');
    await noLinks(options.installDir);
    await noLinks(options.profile);
    const destination = await realpath(options.installDir);
    const profile = await realpath(options.profile);
    assert.notEqual(destination, path.parse(destination).root, 'Drive root cannot be an app directory');
    if (!options.requireIsolated) assert.equal(path.basename(destination), APP, 'Unexpected fixed app directory name');
    assert(!inside(destination, profile) && !inside(profile, destination), 'Install directory overlaps learner data');
    const oldApp = path.join(destination, options.target.startsWith('macos-') ? 'Contents/Resources/app' : 'resources/app');
    const old = await json(path.join(oldApp, 'package.json'));
    assert.equal(old.name, 'kaixin-super-scholar', 'Unknown existing installation');
    assert.equal(await readFile(path.join(oldApp, 'assets/runtime-public.pem'), 'utf8'), await readFile(path.join(here, 'assets/runtime-public.pem'), 'utf8'), 'Existing installation has a different trust key');
    if (process.platform === 'win32') {
      const powershell = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32/WindowsPowerShell/v1.0/powershell.exe');
      const { stdout } = await exec(powershell, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
        '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [Console]::OutputEncoding; ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -ErrorAction Stop | Select-Object ProcessId,Name,ExecutablePath)'], { windowsHide: true, timeout: 20000 });
      const processes = JSON.parse(stdout.replace(/^\uFEFF/, ''));
      assert(Array.isArray(processes) && processes.some(row => row.ProcessId === process.pid), 'Cannot reliably inspect running app processes');
      const running = processes.filter(row => row.ProcessId !== process.pid && (row.Name === `${APP}.exe` || (row.ExecutablePath
        && (inside(destination, path.resolve(row.ExecutablePath)) || inside(path.join(profile, 'runtimes'), path.resolve(row.ExecutablePath))
          || inside(path.join(profile, 'cache'), path.resolve(row.ExecutablePath))
          || path.basename(row.ExecutablePath) === `${APP}.exe`))));
      assert.equal(running.length, 0, '请先正常退出超级学霸，再运行迁移安装器。不会替你强制结束程序。');
    }
  }
  return { ...result, payload: 'verified', nativeLaunch: 'not_checked', updateUI: 'not_checked' };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const raw = process.argv.slice(2), options = {};
  for (let i = 0; i < raw.length; i++) {
    const key = { '--target': 'target', '--profile': 'profile', '--install-dir': 'installDir', '--report-file': 'reportFile' }[raw[i]];
    if (key) options[key] = raw[++i];
    else if (raw[i] === '--require-isolated') options.requireIsolated = true;
    else if (raw[i] === '--package-preflight') options.packagePreflight = true;
    else throw new Error(`Unknown argument: ${raw[i]}`);
  }
  try {
    const result = { passed: true, ...await preflight(options) };
    if (options.reportFile) {
      assert(!inside(path.resolve(options.profile), path.resolve(options.reportFile)), 'Report must stay outside the learning profile');
      await writeFile(options.reportFile, JSON.stringify(result, null, 2));
    }
    console.log(JSON.stringify(result));
  } catch (error) {
    if (options.reportFile && options.profile && !inside(path.resolve(options.profile), path.resolve(options.reportFile))) {
      await writeFile(options.reportFile, JSON.stringify({ passed: false, error: error.message }, null, 2));
    }
    console.error(`Migration preflight failed: ${error.message}`);
    process.exitCode = 2;
  }
}
