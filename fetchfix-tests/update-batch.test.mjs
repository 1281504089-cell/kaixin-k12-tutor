import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { canonicalManifest } from '../src/bundles.mjs';
import { checkUpdateBatch, UPDATE_TARGETS } from '../scripts/check-update-batch.mjs';

const { privateKey, publicKey } = generateKeyPairSync('ed25519');
async function fixture(t, overrides = {}) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'kaixin-batch-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const payload = Buffer.from('signed code-only fixture');
  await writeFile(path.join(directory, 'core.tar.gz'), payload);
  for (const [target, [arch, platform]] of Object.entries(UPDATE_TARGETS)) {
    const manifest = { formatVersion: 1, protocolVersion: 1, arch, platform,
      runtimeId: `release-${target}`, baseRuntimeId: `base-${arch}`, coreVersion: '1.7.1',
      commit: 'a'.repeat(40), builtAt: 200, archive: 'core.tar.gz',
      sha256: createHash('sha256').update(payload).digest('hex'), ...(overrides[target] || {}) };
    manifest.signature = sign(null, Buffer.from(canonicalManifest(manifest)), privateKey).toString('base64');
    await writeFile(path.join(directory, `runtime-${target}.json`), JSON.stringify(manifest));
  }
  return directory;
}

test('one signed batch covers all three real platform identities', async t => {
  const directory = await fixture(t);
  const rows = await checkUpdateBatch(directory, publicKey);
  assert.deepEqual(rows.map(row => row.target).sort(), Object.keys(UPDATE_TARGETS).sort());
});

test('missing Windows cannot pass a three-platform release', async t => {
  const directory = await fixture(t);
  await rm(path.join(directory, 'runtime-windows-x64.json'));
  await assert.rejects(checkUpdateBatch(directory, publicKey), /ENOENT/);
});

for (const values of [{ commit: 'b'.repeat(40) }, { builtAt: 201 }, { coreVersion: '1.7.2' }]) {
  test(`mixed release identity is rejected: ${Object.keys(values)[0]}`, async t => {
    const directory = await fixture(t, { 'windows-x64': values });
    await assert.rejects(checkUpdateBatch(directory, publicKey), /must share/);
  });
}

test('archive corruption and the wrong Windows architecture fail before publication', async t => {
  const directory = await fixture(t);
  await writeFile(path.join(directory, 'core.tar.gz'), 'corrupt');
  await assert.rejects(checkUpdateBatch(directory, publicKey), /Invalid update archive/);
  const incompatible = await fixture(t, { 'windows-x64': { arch: 'arm64' } });
  await assert.rejects(checkUpdateBatch(incompatible, publicKey), /not compatible/);
});
