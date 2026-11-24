import assert from 'node:assert/strict';
import { readFile, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [launcher, seed, alias, profile] = process.argv.slice(2);
const { installBundle } = await import(pathToFileURL(join(launcher, 'src/bundles.mjs')));
const key = await readFile(join(launcher,'assets/runtime-public.pem'));
const donor = await installBundle(seed, profile, key);
const actual = await installBundle(alias, profile, key, ()=>{}, {current:donor.manifest});
assert.equal(actual.manifest.baseRuntimeId,donor.manifest.runtimeId);
assert.equal((await readFile(join(actual.destination,'BUILD_COMMIT'),'utf-8')).trim(), actual.manifest.commit);
assert.deepEqual(JSON.parse(await readFile(join(actual.destination,'installed.json'),'utf-8')),actual.manifest);
// The synthetic prior profile points only to a runtime installed and verified by the production installer.
const temp = join(profile,'active.json.seed.tmp');
await writeFile(temp,JSON.stringify(actual.manifest),{flag:'wx'});
await rename(temp,join(profile,'active.json'));
console.log(JSON.stringify({source:donor.manifest.runtimeId,signedInstalledRuntime:actual.manifest.runtimeId,commit:actual.manifest.commit,core:actual.manifest.corePayloadSha256}));
