import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { splitPayload } from '../scripts/lib/split-payload.mjs';

test('download parts reconstruct exactly and have independent checksums', async () => {
  const folder = await mkdtemp(path.join(os.tmpdir(), 'kx-parts-'));
  try {
    const original = Buffer.from('a'.repeat(29));
    const source = path.join(folder, 'input'); await writeFile(source, original);
    const parts = await splitPayload(source, path.join(folder, 'runtime'), 10);
    assert.deepEqual(parts.map(p => p.bytes), [10, 10, 9]);
    const buffers = [];
    for (const part of parts) {
      const bytes = await readFile(path.join(folder, part.file)); buffers.push(bytes);
      assert.equal(createHash('sha256').update(bytes).digest('hex'), part.sha256);
    }
    assert.deepEqual(Buffer.concat(buffers), original);
    await assert.rejects(splitPayload(source, path.join(folder, 'runtime'), 10), { code: 'EEXIST' });
  } finally { await rm(folder, { recursive: true, force: true }); }
});
