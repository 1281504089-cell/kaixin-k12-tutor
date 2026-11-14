import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { studentEnvironment } from '../src/student-runtime.mjs';

test('bundled support supplies isolated tools and writable caches without changing chat settings', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'Kaixin 安装 '));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'support'));
  const config = { sourcePath: path.join(root, 'core'), pythonPath: path.join(root, 'python/bin/python3'), nodePath: path.join(root, 'node/bin/node') };
  const env = studentEnvironment(config, path.join(root, 'cache'));
  assert.equal(env.PATH.split(path.delimiter)[0], path.join(root, 'support/bin'));
  assert.equal(env.DEEPTUTOR_REMOTION_RUNTIME, path.join(root, 'support/remotion'));
  assert.equal(env.MPLCONFIGDIR, path.join(root, 'cache/matplotlib'));
  assert.ok(!Object.keys(env).some(key => /API|KEY|MODEL|REASON/i.test(key)));
});
