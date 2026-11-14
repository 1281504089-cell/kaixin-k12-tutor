import { createHash, verify } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, mkdir, rename, rm, access, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { pipeline } from 'node:stream/promises';
import { runtimeLayout, systemTar } from './platform.mjs';

const exec = promisify(execFile);
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

export async function sha256(filename) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}

export async function installBundle(manifestFile, root, publicKey, progress = () => {}) {
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
  const archive = path.join(path.dirname(manifestFile), manifest.archive);
  if (await sha256(archive) !== manifest.sha256) throw new Error('The core bundle checksum does not match; download it again');
  await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const staging = `${destination}.installing`;
  await rm(staging, { recursive: true, force: true });
  await mkdir(staging, { mode: 0o700 });
  try {
    progress('firstLaunch');
    // Only locally signed, hash-verified artifacts reach extraction.
    // Windows' system tar can mangle non-ASCII command-line paths. Node opens
    // the archive and sets the working directory using Unicode-aware OS APIs.
    const extraction = exec(systemTar(), ['-xzf', '-'], { cwd: staging, timeout: 600000, windowsHide: true });
    const [input, result] = await Promise.allSettled([
      pipeline(createReadStream(archive), extraction.child.stdin), extraction,
    ]);
    if (result.status === 'rejected') throw result.reason;
    if (input.status === 'rejected') throw input.reason;
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
