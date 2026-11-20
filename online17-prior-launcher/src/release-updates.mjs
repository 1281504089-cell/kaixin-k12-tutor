import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { open, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { compatibleCoreDelta, installBundle, verifyManifest } from './bundles.mjs';

const REPOSITORY = '1281504089-cell/kaixin-k12-tutor';
const TAG = 'core-updates';
const RELEASE = `https://github.com/${REPOSITORY}/releases/download/${TAG}/`;
const API = `https://api.github.com/repos/${REPOSITORY}/releases/`;
const MANIFEST_LIMIT = 16 * 1024;
const MANIFEST_ROUTE_TIMEOUT = 7000;
const RELEASE_METADATA_LIMIT = 2 * 1024 ** 2;
const ARCHIVE_LIMIT = 2 * 1024 ** 3;
const HOSTS = new Set(['github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com']);
// The release owner sets the public HTTPS directory in the signed launcher.
const UPDATE_MIRROR_BASE = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/';

export function updateMirrorBase(value = UPDATE_MIRROR_BASE) {
  if (!value) return null;
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.port || url.username || url.password || url.search || url.hash
    || !/^\/(?:[a-zA-Z0-9_-]+\/)+$/.test(url.pathname)) {
    throw new Error('Invalid desktop update mirror directory');
  }
  return url;
}

export function isUpdateMirrorAsset(url, mirror) {
  return Boolean(mirror && url.origin === mirror.origin && !url.username && !url.password && !url.search
    && !url.hash && url.pathname.startsWith(mirror.pathname)
    && /^[a-zA-Z0-9][a-zA-Z0-9._+-]*\.(?:json|tar\.gz)$/.test(url.pathname.slice(mirror.pathname.length)));
}

function fetchMirrorAsset(name, mirror, fetchAsset, signal, headers) {
  const url = new URL(name, mirror);
  if (!isUpdateMirrorAsset(url, mirror)) throw new Error('Invalid desktop update mirror asset');
  return fetchAsset(url, { redirect: 'error', cache: 'no-store', credentials: 'omit', signal, ...(headers ? { headers } : {}) });
}

export function isGitHubUpdateURL(url) {
  return url.protocol === 'https:' && HOSTS.has(url.hostname) && !url.port && !url.username && !url.password
    && (url.hostname !== 'api.github.com' || url.href.startsWith(API));
}

export function isNetworkSuspended(error) {
  return [error, error?.cause].some(value => value?.code === 'ERR_NETWORK_IO_SUSPENDED'
    || /\bERR_NETWORK_IO_SUSPENDED\b/.test(value?.message ?? ''));
}

export function isInterruptedDownload(error) {
  return [error, error?.cause].some(value => (value?.name === 'TypeError' && /^terminated$/i.test(value.message))
    || ['UND_ERR_SOCKET', 'ECONNRESET'].includes(value?.code)
    || /\bERR_(CONNECTION_RESET|CONTENT_LENGTH_MISMATCH|INCOMPLETE_CHUNKED_ENCODING|HTTP2_PROTOCOL_ERROR)\b/.test(`${value?.code ?? ''} ${value?.message ?? ''}`));
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

async function selectReleaseManifest(target, current, readVerified) {
  let manifest = await readVerified(`runtime-${target}.json`);
  const base = current.baseRuntimeId || current.runtimeId;
  if (manifest.baseRuntimeId !== base && Array.isArray(manifest.compatibleBaseManifests)) {
    const alternative = manifest.compatibleBaseManifests.find(row => row?.baseRuntimeId === base);
    if (alternative) {
      if (typeof alternative.file !== 'string' || !alternative.file.startsWith(`runtime-${target}-`)
        || !/^[a-zA-Z0-9._-]+\.json$/.test(alternative.file)) throw new Error('Invalid compatible update manifest name');
      const compatible = await readVerified(alternative.file);
      if (compatible.baseRuntimeId !== base || !/^[a-f0-9]{64}$/.test(manifest.corePayloadSha256 ?? '')
        || ['commit', 'builtAt', 'coreVersion', 'corePayloadSha256'].some(key => compatible[key] !== manifest[key])) {
        throw new Error('The compatible update must match the same signed release batch');
      }
      manifest = compatible;
    }
  }
  return manifest;
}

function newerRelease(manifest, current) {
  return manifest.builtAt > (current.builtAt ?? 0) && manifest.runtimeId !== current.runtimeId ? manifest : null;
}

export async function findReleaseUpdate(target, current, publicKey, fetchAsset = fetch, signal, mirrorBase) {
  const mirror = updateMirrorBase(mirrorBase);
  if (mirror) {
    try {
      const manifest = await selectReleaseManifest(target, current, async name => verifyManifest(
        await readManifestRoute(routeSignal => fetchMirrorAsset(name, mirror, fetchAsset, routeSignal), signal), publicKey));
      if (manifest.builtAt >= (current.builtAt ?? 0)) return newerRelease(manifest, current);
    } catch {
      signal?.throwIfAborted();
    }
  }
  const manifest = await selectReleaseManifest(target, current, name => verifiedReleaseManifest(name, publicKey, fetchAsset, signal));
  return newerRelease(manifest, current);
}

async function downloadUpdateArchive(asset, directory, onProgress, fetchAsset, signal, mirrorBase, exactBytes) {
  const mirror = updateMirrorBase(mirrorBase);
  const archive = path.join(directory, asset.archive);
  const routes = [
    ...(mirror ? [(routeSignal, headers) => fetchMirrorAsset(asset.archive, mirror, fetchAsset, routeSignal, headers)] : []),
    routeSignal => fetchGitHub(new URL(asset.archive, RELEASE), fetchAsset, routeSignal),
    routeSignal => getApiAsset(asset.archive, fetchAsset, routeSignal),
  ];
  let sessionRetried = false;
  let interruptedRoute = -1;
  let mirrorResumeUsed = false;
  let partial;
  for (let index = 0; index < routes.length; index++) {
    const onMirror = mirror && index === 0;
    const stalled = new AbortController();
    const routeSignal = AbortSignal.any([signal, stalled.signal]);
    let timer = setTimeout(() => stalled.abort(new Error('Update connection timed out')), 30000);
    let response, output;
    let expected = 0;
    let resumeTag;
    let incomplete = false;
    try {
      signal.throwIfAborted();
      const range = partial && { Range: `bytes=${partial.offset}-`, 'If-Match': partial.etag };
      response = await routes[index](routeSignal, range);
      clearTimeout(timer);
      if (!response.ok || !response.body) throw new Error(`${onMirror ? 'Update mirror' : 'GitHub'} HTTP ${response.status}`);
      const length = Number(response.headers.get('content-length'));
      const etag = response.headers.get('etag') ?? '';
      const identity = (response.headers.get('content-encoding') ?? 'identity').toLowerCase() === 'identity';
      expected = partial?.total ?? (length || exactBytes || 0);
      if (exactBytes && expected !== exactBytes) throw new Error('Incremental update download length does not match');
      if (expected > ARCHIVE_LIMIT) throw new Error('Update archive is too large');
      if (partial) {
        const contentRange = `bytes ${partial.offset}-${partial.total - 1}/${partial.total}`;
        if (response.status !== 206 || response.headers.get('content-range') !== contentRange
          || !identity || etag !== partial.etag || length !== partial.total - partial.offset) {
          throw new Error('Update mirror returned an invalid partial archive');
        }
      } else if (onMirror && response.status !== 200) {
        throw new Error('Update mirror did not return a complete archive');
      }
      if (onMirror && identity && Number.isSafeInteger(expected) && expected > 0 && /^"[^"\x00-\x1f\x7f]+"$/.test(etag)) {
        resumeTag = etag;
      }
      output = await open(archive, partial ? 'r+' : 'wx', 0o600);
      let received = partial?.offset ?? 0;
      let progressAt = 0;
      const digest = createHash('sha256');
      if (partial) {
        if ((await output.stat()).size !== received) throw new Error('Partial update archive changed');
        for await (const chunk of createReadStream(archive, { end: received - 1, signal: routeSignal })) digest.update(chunk);
      }
      const reset = () => {
        clearTimeout(timer);
        timer = setTimeout(() => stalled.abort(new Error('Update download stalled')), 60000);
      };
      reset();
      onProgress(expected > 0 ? received / expected : 0, { received, total: expected > 0 ? expected : 0 });
      const limit = new Transform({
        transform(chunk, _encoding, callback) {
          reset();
          received += chunk.length;
          if (received > ARCHIVE_LIMIT || (expected > 0 && received > expected)) {
            return callback(new Error('Update archive exceeds its declared size'));
          }
          digest.update(chunk);
          if (Date.now() - progressAt >= 200 || received === expected) {
            progressAt = Date.now();
            onProgress(expected > 0 ? Math.min(received / expected, 1) : 2, { received, total: expected > 0 ? expected : 0 });
          }
          callback(null, chunk);
        },
      });
      await pipeline(Readable.fromWeb(response.body), limit, output.createWriteStream({ start: received }), { signal: routeSignal });
      if (expected > 0 && expected !== received) {
        incomplete = true;
        throw new Error('Update download was incomplete');
      }
      signal.throwIfAborted();
      if (digest.digest('hex') !== asset.sha256) throw new Error('The core bundle checksum does not match; download it again');
      break;
    } catch (error) {
      await output?.close();
      // Resume only within this attempt, using the byte count committed to disk.
      if (output && resumeTag && !mirrorResumeUsed && !signal.aborted
        && (incomplete || stalled.signal.aborted || isInterruptedDownload(error))) {
        const size = (await stat(archive).catch(() => null))?.size;
        if (size > 0 && size < expected) {
          partial = { offset: size, total: expected, etag: resumeTag };
          mirrorResumeUsed = true;
          index--;
          continue;
        }
      }
      if (output || partial) await rm(archive, { force: true });
      partial = undefined;
      signal.throwIfAborted();
      if (['ENOSPC', 'EACCES', 'EPERM', 'EEXIST'].includes(error.code)) throw error;
      if (isInterruptedDownload(error)) interruptedRoute = index;
      if (!sessionRetried && fetchAsset.recoverAfterSuspend && (isNetworkSuspended(error)
        || (index === routes.length - 1 && interruptedRoute >= 0))) {
        sessionRetried = true;
        clearTimeout(timer);
        await fetchAsset.recoverAfterSuspend(signal);
        index = isNetworkSuspended(error) ? index - 1 : interruptedRoute - 1;
        interruptedRoute = -1;
        continue;
      }
      if (index === routes.length - 1) throw error;
    } finally {
      clearTimeout(timer);
      await response?.body?.cancel().catch(() => {});
    }
  }
}

async function writeReleaseManifest(manifest, directory) {
  const file = path.join(directory, 'runtime.json');
  await writeFile(file, JSON.stringify(manifest), { mode: 0o600, flag: 'wx' });
  return file;
}

export async function downloadReleaseUpdate(manifest, directory, onProgress, fetchAsset = fetch, signal = new AbortController().signal, mirrorBase) {
  await downloadUpdateArchive(manifest, directory, onProgress, fetchAsset, signal, mirrorBase);
  return writeReleaseManifest(manifest, directory);
}

export async function prepareReleaseUpdate({ manifest, current, directory, root, publicKey,
  onProgress, onInstall, fetchAsset = fetch, signal = new AbortController().signal, mirrorBase }) {
  verifyManifest(manifest, publicKey);
  const delta = compatibleCoreDelta(manifest, current);
  const file = await writeReleaseManifest(manifest, directory);
  if (delta) {
    try {
      await downloadUpdateArchive(delta, directory, onProgress, fetchAsset, signal, mirrorBase, delta.bytes);
      signal.throwIfAborted();
      onInstall();
      return await installBundle(file, root, publicKey, undefined, { current, signal });
    } catch (error) {
      signal.throwIfAborted();
      if (['ENOSPC', 'EEXIST'].includes(error.code)) throw error;
      console.warn('Incremental desktop update unavailable; downloading the complete core:', error.message);
      await rm(path.join(directory, delta.archive), { force: true });
      onProgress(2, { received: 0, total: 0 });
    }
  }
  await downloadUpdateArchive(manifest, directory, onProgress, fetchAsset, signal, mirrorBase);
  signal.throwIfAborted();
  onInstall();
  return installBundle(file, root, publicKey);
}
