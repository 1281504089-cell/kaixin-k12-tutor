/** Verify the immutable feed graph using the application's actual Ed25519 parser. */
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const source=path.resolve(process.env.QA_SOURCE_ROOT??process.cwd());
const desktop=path.join(source,'apps/desktop');
const {verifyManifest,coreDeltaDescriptor}=await import(pathToFileURL(path.join(desktop,'src/bundles.mjs')));
const key=readFileSync(path.join(desktop,'assets/runtime-public.pem'));
const read=p=>JSON.parse(readFileSync(p));
const lock=read(path.join(here,'deployment-lock.json'));
const archived=process.argv[2];
const platform={ 'macos-x64':['x64','darwin'], 'macos-arm64':['arm64','darwin'], 'windows-x64':['x64','win32'] };
const assets=new Map(lock.archives.map(item=>[item.name,item]));
const expectedAliases=new Set();
const verify=(record,target)=>verifyManifest(record,key,...platform[target]);
for(const target of Object.keys(platform)) {
  const stableName=`runtime-${target}.json`;
  const previous=verify(read(path.join(here,'previous',stableName)),target);
  assert(!previous.baseRuntimeId);
  const now=verify(read(path.join(here,'feed/github',stableName)),target);
  assert(now.commit===lock.source_commit&&now.corePayloadSha256===lock.core.sha256&&now.builtAt===lock.built_at);
  assert(now.builtAt>previous.builtAt&&now.coreVersion===previous.coreVersion&&!now.baseRuntimeId);
  assert.equal(assets.get(now.archive).sha256,now.sha256);
  const safe=new Set(now.compatibleBaseManifests.map(row=>row.baseRuntimeId));
  assert(safe.size===now.compatibleBaseManifests.length&&safe.has(previous.runtimeId));
  for(const row of previous.compatibleBaseManifests)assert(safe.has(row.baseRuntimeId),row.baseRuntimeId);
  for(const {baseRuntimeId,file} of now.compatibleBaseManifests) {
    assert(file.startsWith(`runtime-${target}-20261126-43dba66-`)&&!expectedAliases.has(file));
    expectedAliases.add(file);
    const child=verify(read(path.join(here,'feed/github',file)),target);
    assert.equal(child.baseRuntimeId,baseRuntimeId);
    assert.equal(child.archive,lock.core.name);
    assert.equal(child.sha256,lock.core.sha256);
    for(const field of ['commit','builtAt','coreVersion','corePayloadSha256'])assert.equal(child[field],now[field]);
    const delta=coreDeltaDescriptor(child);
    assert(delta);
    assert.equal(assets.get(delta.archive).sha256,delta.sha256);
    assert.equal(assets.get(delta.archive).bytes,delta.bytes);
  }
}
assert.equal(expectedAliases.size,lock.feeds.length-3);
if(archived) {
  const retired=new Set(lock.retire.map(item=>item.name));
  assert.equal(readdirSync(archived).length,retired.size);
  for(const name of retired) {
    const group=/^runtime-(macos-x64|macos-arm64|windows-x64)-20261117-k12-(?:13|16)-base-[a-f0-9]{12}\.json$/.exec(name);
    assert(group,name);
    const old=verify(read(path.join(archived,name)),group[1]);
    assert(old.baseRuntimeId && !old.compatibleBaseManifests && old.commit!==lock.source_commit,
      'Only superseded signed compatibility descriptors may be moved');
  }
}
console.log(JSON.stringify({verified:true,aliases:expectedAliases.size,retirement:archived?lock.retire.length:0}));
