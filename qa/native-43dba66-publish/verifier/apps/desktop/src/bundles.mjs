import { createHash, verify } from 'node:crypto';
import { constants, createReadStream } from 'node:fs';
import { readFile, mkdir, mkdtemp, rename, rm, access, writeFile, copyFile, chmod, lstat, readdir, realpath } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { pipeline } from 'node:stream/promises';
import { runtimeLayout, systemTar, WINDOWS } from './platform.mjs';

export function canonicalManifest(manifest) {
  return JSON.stringify(Object.fromEntries(Object.entries(manifest).filter(([key]) => key !== 'signature').sort(([a], [b]) => a.localeCompare(b))));
}

function runtimeIdValid(value) {
  return typeof value === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,100}$/.test(value);
}

export function verifyManifest(manifest, publicKey, architecture = process.arch, platform = process.platform) {
  if (!manifest || manifest.formatVersion !== 1 || manifest.protocolVersion !== 1
    || manifest.platform !== platform || manifest.arch !== architecture
    || !runtimeIdValid(manifest.runtimeId)
    || (manifest.baseRuntimeId !== undefined && (!runtimeIdValid(manifest.baseRuntimeId) || manifest.baseRuntimeId === manifest.runtimeId))
    || !/^[a-zA-Z0-9][a-zA-Z0-9.+_-]*\.tar\.gz$/.test(manifest.archive)
    || !/^[a-f0-9]{64}$/.test(manifest.sha256)
    || (manifest.builtAt !== undefined && (!Number.isSafeInteger(manifest.builtAt) || manifest.builtAt <= 0))) throw new Error('This core bundle is not compatible with this app or this computer');
  if (!verify(null, Buffer.from(canonicalManifest(manifest)), publicKey, Buffer.from(manifest.signature ?? '', 'base64'))) {
    throw new Error('The core bundle signature is invalid');
  }
  return manifest;
}

export function shouldUseBundledUpdate(saved, bundled, transaction) {
  return Boolean(saved && bundled.runtimeId !== saved.runtimeId
    && bundled.builtAt > (saved.builtAt ?? 0)
    && !(transaction?.phase === 'recovered' && transaction.candidate?.runtimeId === bundled.runtimeId));
}

/** A full installer can reuse its signed native base and open an included newer core immediately. */
export async function bundledRelease(seed, publicKey, architecture = process.arch, platform = process.platform) {
  const base = verifyManifest(JSON.parse(await readFile(seed, 'utf8')), publicKey, architecture, platform);
  const file = path.resolve(path.dirname(seed), '../update/runtime.json');
  let data;
  try { data = JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return { file: seed, manifest: base }; throw error; }
  const manifest = verifyManifest(data, publicKey, architecture, platform);
  if (base.baseRuntimeId || manifest.baseRuntimeId !== base.runtimeId || manifest.builtAt <= (base.builtAt ?? 0)) {
    throw new Error('The included core update does not match this installer base');
  }
  return { file, manifest, baseFile: seed };
}

export async function sha256(filename) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}

export async function extractVerifiedArchive(archive, destination, command = systemTar(), args = ['-xzf', '-']) {
  const child = spawn(command, args, {
    cwd: destination, timeout: 600000, windowsHide: true, stdio: ['pipe', 'ignore', 'pipe'],
  });
  let diagnostics = '';
  const diagnosticLimit = 4096;
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', chunk => {
    if (diagnostics.length < diagnosticLimit) diagnostics += chunk.slice(0, diagnosticLimit - diagnostics.length);
  });
  const completed = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`Runtime extraction failed (${code ?? signal}). ${diagnostics.trim()}`.trim()));
    });
  });
  const [input, result] = await Promise.allSettled([pipeline(createReadStream(archive), child.stdin), completed]);
  if (result.status === 'rejected') throw result.reason;
  if (input.status === 'rejected') throw input.reason;
}

export function coreDeltaDescriptor(manifest) {
  const delta = manifest.coreDelta;
  const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  if (!manifest.baseRuntimeId || !delta || delta.formatVersion !== 1
    || !digest(delta.fromCoreSha256) || !digest(delta.sha256) || delta.toCoreSha256 !== manifest.sha256
    || delta.fromCoreSha256 === delta.toCoreSha256
    || !Number.isSafeInteger(delta.bytes) || delta.bytes <= 0 || delta.bytes > 2 * 1024 ** 3
    || typeof delta.archive !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9.+_-]*\.tar\.gz$/.test(delta.archive)
    || delta.archive === manifest.archive) return null;
  return delta;
}

export function compatibleCoreDelta(manifest, current) {
  const delta = coreDeltaDescriptor(manifest);
  return delta && current && manifest.baseRuntimeId === (current.baseRuntimeId ?? current.runtimeId)
    && delta.fromCoreSha256 === current.corePayloadSha256 ? delta : null;
}

const inventoryName = 'delta-inventory.json';
function deltaPathValid(name) {
  return typeof name === 'string' && (name === 'BUILD_COMMIT' || /^(core|web|launcher)\//.test(name))
    && name.split('/').every(part => part && part !== '.' && part !== '..'
      && !/[\\:<>"|?*\u0000-\u001f]|[ .]$/.test(part)
      && !/^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)/i.test(part));
}

async function checkExtractedFiles(root, required, relative = '') {
  for (const entry of await readdir(path.join(root, relative), { withFileTypes: true })) {
    const name = relative ? `${relative}/${entry.name}` : entry.name;
    if (entry.isDirectory()) await checkExtractedFiles(root, required, name);
    else if (!entry.isFile() || !required.has(name)) throw new Error(`Unexpected incremental update entry: ${name}`);
  }
}

async function assembleDelta(staging, donor, delta, signal) {
  const inventoryPath = path.join(staging, inventoryName);
  const inventoryStat = await lstat(inventoryPath);
  if (!inventoryStat.isFile() || inventoryStat.nlink !== 1 || inventoryStat.size > 16 * 1024 ** 2) {
    throw new Error('Invalid incremental update inventory');
  }
  const inventory = JSON.parse(await readFile(inventoryPath, 'utf8'));
  if (inventory.formatVersion !== 1 || inventory.fromCoreSha256 !== delta.fromCoreSha256
    || inventory.toCoreSha256 !== delta.toCoreSha256 || !Array.isArray(inventory.files)) {
    throw new Error('Incremental update targets a different core');
  }
  const required = new Set();
  const aliases = new Set();
  for (const row of inventory.files) {
    const name = row?.file;
    if (!deltaPathValid(name) || !Number.isSafeInteger(row.bytes) || row.bytes < 0
      || typeof row.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(row.sha256)
      || ![0o644, 0o755].includes(row.mode)) throw new Error('Invalid incremental update file record');
    const alias = name.normalize('NFC').toLowerCase();
    if (aliases.has(alias)) throw new Error(`Duplicate incremental update entry: ${name}`);
    aliases.add(alias);
    required.add(name);
  }
  if (!required.has('BUILD_COMMIT')) throw new Error('Incremental update is missing its build identity');
  await rm(inventoryPath);
  await checkExtractedFiles(staging, required);
  const donorRoot = await realpath(donor);
  for (const row of inventory.files) {
    signal?.throwIfAborted();
    const file = path.join(staging, row.file);
    const staged = await lstat(file).catch(error => {
      if (error.code !== 'ENOENT') throw error;
      return null;
    });
    if (!staged) {
      const original = await realpath(path.join(donorRoot, row.file));
      if (!original.startsWith(donorRoot + path.sep)) throw new Error('Previous core file is outside its runtime');
      const originalStat = await lstat(original);
      if (!originalStat.isFile() || originalStat.size !== row.bytes) throw new Error(`Previous core file changed: ${row.file}`);
      await mkdir(path.dirname(file), { recursive: true });
      await copyFile(original, file, constants.COPYFILE_FICLONE | constants.COPYFILE_EXCL);
    } else if (!staged.isFile() || staged.nlink !== 1 || staged.size !== row.bytes) {
      throw new Error(`Invalid incremental update file: ${row.file}`);
    }
    if (await sha256(file) !== row.sha256) throw new Error(`Incremental update checksum mismatch: ${row.file}`);
    await chmod(file, row.mode);
  }
}

export async function installBundle(manifestFile, root, publicKey, progress = () => {}, incremental) {
  const manifest = verifyManifest(JSON.parse(await readFile(manifestFile, 'utf8')), publicKey);
  const destination = path.join(root, 'runtimes', manifest.runtimeId);
  const base = manifest.baseRuntimeId ? path.join(root, 'runtimes', manifest.baseRuntimeId) : null;
  if (base) {
    const installedBase = verifyManifest(JSON.parse(await readFile(path.join(base, 'installed.json'), 'utf8')), publicKey);
    if (installedBase.runtimeId !== manifest.baseRuntimeId || installedBase.baseRuntimeId) throw new Error('The required base runtime is missing');
    await checkLayout(base);
  }
  try {
    const existing = JSON.parse(await readFile(path.join(destination, 'installed.json'), 'utf8'));
    if (existing.sha256 === manifest.sha256 && existing.signature === manifest.signature) {
      await checkLayout(destination, base);
      return { manifest, destination };
    }
    throw new Error('A different core is already installed under this runtime ID; use a new runtime ID');
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  progress('verifying');
  let delta, donor;
  if (incremental) {
    const previous = verifyManifest(incremental.current, publicKey);
    delta = compatibleCoreDelta(manifest, previous);
    if (!delta) throw new Error('This installed core cannot accept the incremental update');
    donor = path.join(root, 'runtimes', previous.runtimeId);
    if (!(await lstat(donor)).isDirectory()) throw new Error('Previous core is not an installed runtime directory');
    const installed = verifyManifest(JSON.parse(await readFile(path.join(donor, 'installed.json'), 'utf8')), publicKey);
    if (installed.signature !== previous.signature) throw new Error('Previous core signature changed');
  }
  const asset = delta ?? manifest;
  const archive = path.join(path.dirname(manifestFile), asset.archive);
  if ((delta && (await lstat(archive)).size !== delta.bytes) || await sha256(archive) !== asset.sha256) {
    throw new Error('The core bundle checksum does not match; download it again');
  }
  await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const previousStaging = `${destination}.installing`;
  await rm(previousStaging, { recursive: true, force: true });
  // Keep Windows tar's working path short and on the same volume as the final runtime.
  const staging = WINDOWS ? await mkdtemp(path.join(root, '.kx-')) : previousStaging;
  if (!WINDOWS) await mkdir(staging, { mode: 0o700 });
  try {
    progress('firstLaunch');
    // Only locally signed, hash-verified artifacts reach extraction.
    // Windows' system tar can mangle non-ASCII command-line paths. Node opens
    // the archive and sets the working directory using Unicode-aware OS APIs.
    await extractVerifiedArchive(archive, staging);
    if (delta) {
      await assembleDelta(staging, donor, delta, incremental.signal);
      if ((await readFile(path.join(staging, 'BUILD_COMMIT'), 'utf8')).trim() !== manifest.commit) {
        throw new Error('Incremental update reconstructed a different build');
      }
      incremental.signal?.throwIfAborted();
    }
    await checkLayout(staging, base);
    await writeFile(path.join(staging, 'installed.json'), JSON.stringify(manifest, null, 2));
    await rename(staging, destination);
    return { manifest, destination };
  } catch (error) {
    await rm(staging, { recursive: true, force: true });
    throw error;
  }
}

async function checkLayout(root, base = root) {
  const { python, node } = runtimeLayout();
  await Promise.all([path.join(base ?? root, python), path.join(base ?? root, node),
    path.join(root, 'core/deeptutor_cli/main.py'), path.join(root, 'web/server.js')].map(file => access(file)));
}

export function bundleConfig(destination, runtimeHome, runtimeId, baseRuntimeId) {
  const { python, node } = runtimeLayout();
  const basePath = baseRuntimeId ? path.join(path.dirname(destination), baseRuntimeId) : destination;
  return {
    schemaVersion: 1, mode: 'bundled', runtimeId,
    sourcePath: path.join(destination, 'core'),
    pythonPath: path.join(basePath, python),
    nodePath: path.join(basePath, node),
    webPath: path.join(destination, 'web'), basePath, runtimeHome,
  };
}
