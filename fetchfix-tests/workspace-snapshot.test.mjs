import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, writeFile, readFile, stat, rm, access } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { snapshotWorkspace } from '../src/workspace-snapshot.mjs';

test('snapshots share verified immutable PDFs and independently copy learning records', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-backup-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = path.join(root, 'workspace'), destination = path.join(root, 'snapshot');
  const bytes = Buffer.from('immutable textbook'), digest = createHash('sha256').update(bytes).digest('hex');
  const pdf = path.join(source, 'reading', digest, 'raw', 'book.pdf');
  await mkdir(path.dirname(pdf), { recursive: true });
  await writeFile(pdf, bytes);
  const changed = path.join(source, 'reading', '0'.repeat(64), 'raw', 'changed.pdf');
  await mkdir(path.dirname(changed), { recursive: true });
  await writeFile(changed, 'original');
  await writeFile(path.join(source, 'notes.json'), 'before');
  await snapshotWorkspace(source, destination);
  const saved = path.join(destination, path.relative(source, pdf));
  assert.equal((await stat(saved)).ino, (await stat(pdf)).ino);
  await writeFile(path.join(source, 'notes.json'), 'after');
  await writeFile(changed, 'changed');
  assert.equal(await readFile(path.join(destination, 'notes.json'), 'utf8'), 'before');
  assert.equal(await readFile(path.join(destination, path.relative(source, changed)), 'utf8'), 'original');
  await assert.rejects(snapshotWorkspace(source, destination), { code: 'EEXIST' });
  assert.equal(await readFile(path.join(destination, 'notes.json'), 'utf8'), 'before');
});

test('a failed snapshot removes only its own incomplete copy', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kaixin-backup-fail-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const destination = path.join(root, 'new-snapshot');
  await assert.rejects(snapshotWorkspace(path.join(root, 'absent'), destination), { code: 'ENOENT' });
  await assert.rejects(access(destination), { code: 'ENOENT' });
});
