import { createWriteStream } from 'node:fs';
import { writeFile } from 'node:fs/promises';
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

async function fetchGitHub(url, fetchAsset, signal, accept) {
  for (let hop = 0; hop < 5; hop++) {
    if (url.protocol !== 'https:' || !HOSTS.has(url.hostname) || url.port || url.username || url.password
      || (url.hostname === 'api.github.com' && !url.href.startsWith(API))) {
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

async function getAsset(name, fetchAsset, signal) {
  const direct = await fetchGitHub(new URL(name, RELEASE), fetchAsset, signal);
  if (direct.status !== 404 && direct.status !== 429 && direct.status < 500) return direct;
  await direct.body?.cancel();
  return getApiAsset(name, fetchAsset, signal);
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

export async function findReleaseUpdate(target, current, publicKey, fetchAsset = fetch, signal) {
  const name = `runtime-${target}.json`;
  let data;
  try {
    // Version checks read a small signed manifest. Give each route a fresh budget.
    data = await readManifestRoute(routeSignal => getApiAsset(name, fetchAsset, routeSignal), signal);
  } catch {
    signal?.throwIfAborted();
    data = await readManifestRoute(routeSignal => fetchGitHub(new URL(name, RELEASE), fetchAsset, routeSignal), signal);
  }
  const manifest = verifyManifest(data, publicKey);
  if (!manifest.builtAt || manifest.builtAt <= (current.builtAt ?? 0) || manifest.runtimeId === current.runtimeId) return null;
  return manifest;
}

export async function downloadReleaseUpdate(manifest, directory, onProgress, fetchAsset = fetch, signal) {
  const deadline = AbortSignal.timeout(30 * 60 * 1000);
  signal = signal ? AbortSignal.any([signal, deadline]) : deadline;
  const response = await getAsset(manifest.archive, fetchAsset, signal);
  if (!response.ok || !response.body) {
    await response.body?.cancel();
    throw new Error(`GitHub HTTP ${response.status}`);
  }
  const expected = Number(response.headers.get('content-length'));
  if (expected > ARCHIVE_LIMIT) throw new Error('GitHub update archive is too large');
  let received = 0;
  const limit = new Transform({
    transform(chunk, _encoding, callback) {
      received += chunk.length;
      if (received > ARCHIVE_LIMIT) return callback(new Error('GitHub update archive is too large'));
      if (expected > 0) onProgress(Math.min(received / expected, 1));
      callback(null, chunk);
    },
  });
  await pipeline(Readable.fromWeb(response.body), limit,
    createWriteStream(path.join(directory, manifest.archive), { mode: 0o600, flags: 'wx' }), { signal });
  if (expected > 0 && expected !== received) throw new Error('GitHub update download was incomplete');
  const file = path.join(directory, 'runtime.json');
  await writeFile(file, JSON.stringify(manifest), { mode: 0o600, flag: 'wx' });
  return file;
}
