import { createHash } from 'node:crypto';
import { open, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { verifyManifest } from './bundles.mjs';

const REPOSITORY = '1281504089-cell/kaixin-k12-tutor';
const TAG = 'core-updates';
const RELEASE = `https://github.com/${REPOSITORY}/releases/download/${TAG}/`;
const API = `https://api.github.com/repos/${REPOSITORY}/releases/`;
const MANIFEST_LIMIT = 16 * 1024;
const MANIFEST_ROUTE_TIMEOUT = 7000;
const RELEASE_METADATA_LIMIT = 2 * 1024 ** 2;
const ARCHIVE_LIMIT = 2 * 1024 ** 3;
const HOSTS = new Set(['github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com']);

export function isGitHubUpdateURL(url) {
  return url.protocol === 'https:' && HOSTS.has(url.hostname) && !url.port && !url.username && !url.password
    && (url.hostname !== 'api.github.com' || url.href.startsWith(API));
}

async function fetchGitHub(url, fetchAsset, signal, accept) {
  for (let hop = 0; hop < 5; hop++) {
    if (!isGitHubUpdateURL(url)) {
      throw new Error('Invalid GitHub update download location');
    }
    const response = await fetchAsset(url, {
      redirect: 'manual', cache: 'no-store', credentials: 'omit', signal,
      ...(accept && url.hostname === 'api.github.com' ? { headers: { Accept: accept } } : {}),
    });
    if (![301, 302, 303, 307, 308].includes(response.status)) return response;
    const location = response.headers.get('location');
    await response.body?.cancel();
    if (!location) throw new Error('Missing GitHub update redirect');
    url = new URL(location, url);
  }
  throw new Error('Too many GitHub update redirects');
}

async function boundedJSON(response, limit, description) {
  if (!response.body) throw new Error(`Missing GitHub ${description}`);
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > limit) throw new Error(`GitHub ${description} is too large`);
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

async function getApiAsset(name, fetchAsset, signal) {
  const listing = await fetchGitHub(new URL(`tags/${TAG}`, API), fetchAsset, signal, 'application/vnd.github+json');
  if (!listing.ok) return listing;
  const release = await boundedJSON(listing, RELEASE_METADATA_LIMIT, 'release metadata');
  if (release?.tag_name !== TAG || release.draft !== false || !Array.isArray(release.assets)) {
    throw new Error('Invalid GitHub update release metadata');
  }
  const asset = release.assets.find(row => row?.name === name && row.state === 'uploaded');
  if (!asset) return new Response(null, { status: 404 });
  if (!Number.isSafeInteger(asset.id) || asset.id < 1) throw new Error('Invalid GitHub update asset ID');
  return fetchGitHub(new URL(`assets/${asset.id}`, API), fetchAsset, signal, 'application/octet-stream');
}

async function readManifestRoute(fetchManifest, signal) {
  const timeout = AbortSignal.timeout(MANIFEST_ROUTE_TIMEOUT);
  const routeSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const response = await fetchManifest(routeSignal);
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(`GitHub HTTP ${response.status}`);
  }
  return boundedJSON(response, MANIFEST_LIMIT, 'update manifest');
}

async function verifiedReleaseManifest(name, publicKey, fetchAsset, signal) {
  let data;
  try {
    // Version checks read a small signed manifest. Give each route a fresh budget.
    data = await readManifestRoute(routeSignal => getApiAsset(name, fetchAsset, routeSignal), signal);
  } catch {
    signal?.throwIfAborted();
    data = await readManifestRoute(routeSignal => fetchGitHub(new URL(name, RELEASE), fetchAsset, routeSignal), signal);
  }
  return verifyManifest(data, publicKey);
}

export async function findReleaseUpdate(target, current, publicKey, fetchAsset = fetch, signal) {
  let manifest = await verifiedReleaseManifest(`runtime-${target}.json`, publicKey, fetchAsset, signal);
  const base = current.baseRuntimeId || current.runtimeId;
  if (manifest.baseRuntimeId !== base && Array.isArray(manifest.compatibleBaseManifests)) {
    const alternative = manifest.compatibleBaseManifests.find(row => row?.baseRuntimeId === base);
    if (alternative) {
      if (typeof alternative.file !== 'string' || !alternative.file.startsWith(`runtime-${target}-`)
        || !/^[a-zA-Z0-9._-]+\.json$/.test(alternative.file)) throw new Error('Invalid compatible update manifest name');
      const compatible = await verifiedReleaseManifest(alternative.file, publicKey, fetchAsset, signal);
      if (compatible.baseRuntimeId !== base || !/^[a-f0-9]{64}$/.test(manifest.corePayloadSha256 ?? '')
        || ['commit', 'builtAt', 'coreVersion', 'corePayloadSha256'].some(key => compatible[key] !== manifest[key])) {
        throw new Error('The compatible update must match the same signed release batch');
      }
      manifest = compatible;
    }
  }
  if (!manifest.builtAt || manifest.builtAt <= (current.builtAt ?? 0) || manifest.runtimeId === current.runtimeId) return null;
  return manifest;
}

export async function downloadReleaseUpdate(manifest, directory, onProgress, fetchAsset = fetch, signal) {
  const deadline = AbortSignal.timeout(30 * 60 * 1000);
  signal = signal ? AbortSignal.any([signal, deadline]) : deadline;
  const archive = path.join(directory, manifest.archive);
  const routes = [
    routeSignal => fetchGitHub(new URL(manifest.archive, RELEASE), fetchAsset, routeSignal),
    routeSignal => getApiAsset(manifest.archive, fetchAsset, routeSignal),
  ];
  for (const [index, route] of routes.entries()) {
    signal.throwIfAborted();
    const stalled = new AbortController();
    const routeSignal = AbortSignal.any([signal, stalled.signal]);
    let timer = setTimeout(() => stalled.abort(new Error('GitHub update connection timed out')), 30000);
    let response, output;
    try {
      response = await route(routeSignal);
      clearTimeout(timer);
      if (!response.ok || !response.body) throw new Error(`GitHub HTTP ${response.status}`);
      const expected = Number(response.headers.get('content-length'));
      if (expected > ARCHIVE_LIMIT) throw new Error('GitHub update archive is too large');
      output = await open(archive, 'wx', 0o600);
      let received = 0;
      const digest = createHash('sha256');
      const reset = () => {
        clearTimeout(timer);
        timer = setTimeout(() => stalled.abort(new Error('GitHub update download stalled')), 60000);
      };
      reset();
      onProgress(0);
      const limit = new Transform({
        transform(chunk, _encoding, callback) {
          reset();
          received += chunk.length;
          if (received > ARCHIVE_LIMIT) return callback(new Error('GitHub update archive is too large'));
          digest.update(chunk);
          if (expected > 0) onProgress(Math.min(received / expected, 1));
          callback(null, chunk);
        },
      });
      await pipeline(Readable.fromWeb(response.body), limit, output.createWriteStream(), { signal: routeSignal });
      if (expected > 0 && expected !== received) throw new Error('GitHub update download was incomplete');
      if (digest.digest('hex') !== manifest.sha256) throw new Error('The core bundle checksum does not match; download it again');
      break;
    } catch (error) {
      if (output) {
        await output.close();
        await rm(archive, { force: true });
      }
      signal.throwIfAborted();
      if (index === routes.length - 1 || ['ENOSPC', 'EACCES', 'EPERM', 'EEXIST'].includes(error.code)) throw error;
    } finally {
      clearTimeout(timer);
      await response?.body?.cancel().catch(() => {});
    }
  }
  const file = path.join(directory, 'runtime.json');
  await writeFile(file, JSON.stringify(manifest), { mode: 0o600, flag: 'wx' });
  return file;
}
