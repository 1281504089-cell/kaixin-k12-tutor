import assert from 'node:assert/strict';
import { lstat, readFile, rename, writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';
import { snapshotWorkspace } from './repair/workspace-snapshot.mjs';

const userRoot = process.argv[2];
const runtimeHome = path.join(userRoot, 'workspace');
const activeFile = path.join(userRoot, 'active.json');
const transactionFile = path.join(userRoot, 'upgrade.json');
async function readJSON(file) {
  try { return JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
const writeJSON = (file, value) => writeFile(file, JSON.stringify(value));
if ((await readJSON(transactionFile)).phase === 'testing') {
  await assert.rejects(rename(runtimeHome, runtimeHome + '.probe'), { code: 'EPERM' });
}
const source = await readFile(new URL('./repair/main.mjs', import.meta.url), 'utf8');
const body = source.slice(source.indexOf('async function recoverInterruptedUpgrade()'), source.indexOf('async function prepareUpgrade('));
const bindings = { userRoot, runtimeHome, activeFile, transactionFile, path, readJSON, writeJSON, status: () => {},
  lstat, rename, delay, snapshotWorkspace, WINDOWS: true, interfaceWatcher: undefined };
const result = await new Function(...Object.keys(bindings), body + '\nreturn recoverInterruptedUpgrade().then(() => runtimeHome);')(...Object.values(bindings));
assert.notEqual(result, runtimeHome);
assert.equal(await readFile(path.join(result, 'history.txt'), 'utf8'), 'restored study history');
