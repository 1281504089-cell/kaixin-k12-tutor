import { spawnSync } from 'node:child_process';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { mkdir, mkdtemp, rm, readFile, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { canonicalManifest, extractVerifiedArchive, installBundle, sha256 } from './repair/bundles.mjs';
import { systemTar } from './repair/platform.mjs';

test('Windows tar boot path is short and handles a long runtime ID, a Chinese directory and Unicode input paths', async t => {
  assert.equal(process.platform, 'win32');
  const root = await mkdtemp(path.join(os.tmpdir(), '开心动力 启动 '));
  t.after(() => rm(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 150 }));
  const seed = path.join(root, '种子');
  await mkdir(seed);
  const archive = path.join(seed, 'test.tar.gz');
  const longName = 'core/' + 'a'.repeat(49) + '/' + 'b'.repeat(49) + '/' + 'c'.repeat(43) + '.txt';
  const python = String.raw`
from io import BytesIO
import sys,tarfile
with tarfile.open(sys.argv[1], 'w:gz') as bundle:
    for name in ['node/node.exe','python/python.exe','core/deeptutor_cli/main.py','web/server.js',sys.argv[2]]:
        raw = b'signed fixture'
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        bundle.addfile(info,BytesIO(raw))
`;
  assert.equal(spawnSync('python', ['-c', python, archive, longName], { stdio: 'inherit' }).status, 0);
  console.log(spawnSync(systemTar(), ['--version'], { encoding: 'utf8' }).stdout.trim());
  const id = '1.7.1-kaixin-20261117-k12-18-windows-x64-base-' + '1bb8a743bc42';
  const previous = path.join(root, 'runtimes', id + '.installing', longName);
  const improved = path.join(root, '.kx-abcdef', longName);
  assert(previous.length >= 260 && improved.length < 260, [previous.length, improved.length].join('/'));
  const keys = generateKeyPairSync('ed25519');
  const manifest = {formatVersion:1,protocolVersion:1,platform:process.platform,arch:process.arch,runtimeId:id,archive:path.basename(archive),sha256:await sha256(archive)};
  manifest.signature = sign(null, Buffer.from(canonicalManifest(manifest)), keys.privateKey).toString('base64');
  const filename = path.join(seed,'runtime.json');
  await writeFile(filename, JSON.stringify(manifest));
  const result = await installBundle(filename, root, keys.publicKey);
  assert.equal(await readFile(path.join(result.destination,longName),'utf8'), 'signed fixture');
  const output = String.raw`process.stdin.resume();process.stderr.write('real diagnostic\n' + 'x'.repeat(2*1024**2));process.exitCode=2`;
  await assert.rejects(extractVerifiedArchive(archive,root,process.execPath,['-e',output]),
    error => error.message.startsWith('Runtime extraction failed (2). real diagnostic') && error.message.length < 4200);
});
