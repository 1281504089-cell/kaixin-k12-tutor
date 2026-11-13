import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { verifyManifest } from './student-source/apps/desktop/src/bundles.mjs';
import { checkUpdateBatch } from './student-source/apps/desktop/scripts/check-update-batch.mjs';
const batch = JSON.parse(await readFile('online-update-manifests.json'));
const config = JSON.parse(await readFile('ci-core-release.json'));
const key = await readFile('delivery-runtime-public.pem');
const rows = await checkUpdateBatch('promotion', key);
assert.equal(rows.length, 3);
assert.equal(batch.source_commit, config.source_commit);
assert.equal(batch.desktop_patch_sha256, config.desktop_patch_sha256);
for (const [target, thin] of Object.entries(config.thin)) {
  const main = batch.manifests[`runtime-${target}.json`];
  assert.equal(main.baseRuntimeId, undefined);
  const previous = JSON.parse(await readFile(`current-feeds/runtime-${target}.json`));
  verifyManifest(previous, key, thin.arch, thin.platform);
  assert.ok((previous.builtAt ?? 0) <= main.builtAt, 'Refusing to replace a newer production release');
  if (previous.builtAt === main.builtAt) assert.equal(previous.sha256, main.sha256, 'A different release already has this timestamp');
  for (const suffix of ['20261112', 'early']) {
    const value = batch.manifests[`runtime-${target}-${suffix}.json`];
    verifyManifest(value, key, thin.arch, thin.platform);
    for (const name of ['commit', 'builtAt', 'coreVersion', 'corePayloadSha256']) assert.equal(main[name], value[name]);
    assert.equal(value.baseRuntimeId, (suffix === 'early' ? config.legacy[target] : thin).baseRuntimeId);
  }
  const report = JSON.parse(await readFile(`native-results/verification-${target}.json`));
  assert.deepEqual(report, batch.reports[target]);
  assert.equal(report.fresh_full_installer, 'passed');
  assert.equal(report.native_bridge.textbooks, 136);
  for (const name of ['ready', 'chat_preserved', 'task_preserved', 'saved_key_preserved']) assert.equal(report.native_bridge[name], true);
}
console.log('PASS: three native platforms, nine production signatures, archive hashes and the same frozen core.');
