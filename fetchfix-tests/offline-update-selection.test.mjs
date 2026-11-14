import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { canonicalManifest } from '../src/bundles.mjs';
import { selectOfflineUpdate } from '../scripts/select-offline-update.mjs';

const { publicKey, privateKey } = generateKeyPairSync('ed25519');
function signed(values) {
  const manifest = { formatVersion: 1, protocolVersion: 1, coreVersion: '1.7.1',
    archive: 'core.tar.gz', sha256: '0'.repeat(64), ...values };
  manifest.signature = sign(null, Buffer.from(canonicalManifest(manifest)), privateKey).toString('base64');
  return manifest;
}

for (const [target, platform, arch] of [['windows-x64', 'win32', 'x64'], ['macos-x64', 'darwin', 'x64'], ['macos-arm64', 'darwin', 'arm64']]) {
  for (const legacy of [false, true]) {
    test(`${target} selects the installed ${legacy ? 'early' : '20261112'} base without altering it`, async t => {
      const root = await mkdtemp(path.join(os.tmpdir(), 'scholar 更新选择 '));
      t.after(() => rm(root, { recursive: true, force: true }));
      const updates = path.join(root, 'updates');
      const home = path.join(root, 'home');
      const baseId = `1.7.1-${legacy ? '77f2ba387' : '04276f68a'}-${arch}`;
      await mkdir(path.join(home, 'runtimes', baseId), { recursive: true });
      await mkdir(updates);
      const active = signed({ platform, arch, runtimeId: 'existing-overlay', baseRuntimeId: baseId, builtAt: 100 });
      const base = signed({ platform, arch, runtimeId: baseId, builtAt: 50 });
      const activeText = JSON.stringify(active);
      const baseText = JSON.stringify(base);
      await writeFile(path.join(home, 'active.json'), activeText);
      await writeFile(path.join(home, 'runtimes', baseId, 'installed.json'), baseText);
      const bytes = Buffer.from('verified code-only update');
      await writeFile(path.join(updates, 'core.tar.gz'), bytes);
      for (const [suffix, id] of [['', '04276f68a'], ['-early', '77f2ba387']]) {
        await writeFile(path.join(updates, `runtime-${target}${suffix}.json`), JSON.stringify(signed({ platform, arch,
          runtimeId: `update${suffix || '-new'}`, baseRuntimeId: `1.7.1-${id}-${arch}`, builtAt: 200,
          sha256: createHash('sha256').update(bytes).digest('hex') })));
      }
      const selected = await selectOfflineUpdate(updates, home, publicKey, platform);
      assert.equal(JSON.parse(await readFile(selected.file)).baseRuntimeId, baseId);
      assert.equal((await selectOfflineUpdate(updates, home, publicKey, platform)).file, selected.file);
      assert.equal(await readFile(path.join(home, 'active.json'), 'utf8'), activeText);
      assert.equal(await readFile(path.join(home, 'runtimes', baseId, 'installed.json'), 'utf8'), baseText);
      await writeFile(path.join(updates, 'core.tar.gz'), 'corrupt');
      await assert.rejects(selectOfflineUpdate(updates, home, publicKey, platform), /校验失败/);
    });
  }
}
