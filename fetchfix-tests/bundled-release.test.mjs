import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { bundledRelease, canonicalManifest } from '../src/bundles.mjs';

const { publicKey, privateKey } = generateKeyPairSync('ed25519');
function signed(values) {
  const data = { formatVersion: 1, protocolVersion: 1, coreVersion: '1.7.1',
    runtimeId: 'base', builtAt: 100, archive: 'core.tar.gz', sha256: '0'.repeat(64), ...values };
  data.signature = sign(null, Buffer.from(canonicalManifest(data)), privateKey).toString('base64');
  return data;
}

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'scholar-bundled-update-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'seed'));
  await mkdir(path.join(root, 'update'));
  return root;
}

for (const [platform, arch] of [['win32', 'x64'], ['darwin', 'x64'], ['darwin', 'arm64']]) {
  test(`a fresh ${platform}/${arch} installer selects its included latest core and original base`, async t => {
    const root = await fixture(t);
    const seed = path.join(root, 'seed/runtime.json');
    const base = JSON.stringify(signed({ platform, arch }));
    await writeFile(seed, base);
    assert.equal((await bundledRelease(seed, publicKey, arch, platform)).file, seed);
    const update = path.join(root, 'update/runtime.json');
    await writeFile(update, JSON.stringify(signed({ platform, arch, runtimeId: 'updated-core', baseRuntimeId: 'base', builtAt: 200 })));
    const release = await bundledRelease(seed, publicKey, arch, platform);
    assert.equal(release.file, update);
    assert.equal(release.baseFile, seed);
    assert.equal(release.manifest.runtimeId, 'updated-core');
    assert.equal(await readFile(seed, 'utf8'), base);
  });
}

test('an included update with a wrong base, old timestamp or bad signature is rejected', async t => {
  const root = await fixture(t);
  const seed = path.join(root, 'seed/runtime.json');
  await writeFile(seed, JSON.stringify(signed({ platform: process.platform, arch: process.arch })));
  const file = path.join(root, 'update/runtime.json');
  for (const changes of [{ baseRuntimeId: 'wrong' }, { builtAt: 99 }]) {
    await writeFile(file, JSON.stringify(signed({ platform: process.platform, arch: process.arch,
      runtimeId: 'updated', baseRuntimeId: 'base', builtAt: 200, ...changes })));
    await assert.rejects(bundledRelease(seed, publicKey), /does not match/);
  }
  await writeFile(file, JSON.stringify({ ...signed({ platform: process.platform, arch: process.arch,
    runtimeId: 'updated', baseRuntimeId: 'base', builtAt: 200 }), signature: 'invalid' }));
  await assert.rejects(bundledRelease(seed, publicKey), /signature/);
});
