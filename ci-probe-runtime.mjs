import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { generateKeyPairSync, sign } from 'node:crypto';
import path from 'node:path';
import { SourceRuntime } from './student-source/apps/desktop/src/runtime.mjs';
import { bundleConfig, canonicalManifest, installBundle } from './student-source/apps/desktop/src/bundles.mjs';
import { runtimeLayout, systemPath } from './student-source/apps/desktop/src/platform.mjs';

const [mode, directory, home, manifestFile, output] = process.argv.slice(2);
const runtime = new SourceRuntime({ log: line => process.stdout.write(line) });
const metadata = JSON.parse(await readFile(manifestFile, 'utf8'));
let root = directory;
if (mode === 'bridge') {
  const keys = generateKeyPairSync('ed25519');
  const trial = { ...metadata, signature: sign(null, Buffer.from(canonicalManifest(metadata)), keys.privateKey).toString('base64') };
  const trialFile = path.join(path.dirname(manifestFile), 'trial-only.json');
  await writeFile(trialFile, JSON.stringify(trial));
  const installed = await installBundle(trialFile, home, keys.publicKey);
  root = installed.destination;
}
const config = bundleConfig(root, path.join(home, 'workspace'), metadata.runtimeId);
process.env.PATH = systemPath();
let books = 0;
try {
  await runtime.start(config, path.join(home, 'cache-' + mode));
  assert.equal(runtime.state.phase, 'ready', runtime.state.message);
  assert.equal((await fetch(runtime.state.backendURL + '/health/ready')).status, 200);
  const page = await fetch(runtime.state.url + '/chat');
  assert.equal(page.status, 200);
  books = (await (await fetch(runtime.state.url + '/api/student/textbooks')).json()).books.length;
  assert.equal(books, 136, 'All preinstalled textbooks must remain available');
} finally { await runtime.stop(); }

const code = mode === 'seed' ? `
import asyncio,json
from deeptutor.services.session import get_session_store
from deeptutor.services.task_board import get_task_board_store,CreateCard
from deeptutor.services.config.model_catalog import get_model_catalog_service
async def f():
 s=get_session_store(); r=await s.create_session(title='before update'); await s.add_message(r['id'],'user','existing learning record')
 b=get_task_board_store().create(CreateCard(title='existing task'),'')
 c=get_model_catalog_service(); d=c.load(); d['services']['llm']={'active_profile_id':'test','active_model_id':'test-model','profiles':[{'id':'test','name':'test','binding':'openai','base_url':'http://127.0.0.1:9/v1','api_key':'fixture-only-not-a-real-key','models':[{'id':'test-model','model':'gpt-4o-mini','name':'test'}]}]}; c.save(d)
 return {'session_id':r['id'],'task_id':b.cards[-1].id}
print(json.dumps(asyncio.run(f())))
` : `
import asyncio,json
from pathlib import Path
from deeptutor.services.session import get_session_store
from deeptutor.services.task_board import get_task_board_store
from deeptutor.services.config.model_catalog import get_model_catalog_service
d=json.loads(Path(${JSON.stringify(path.join(home, 'before.json'))}).read_text())
async def f():
 s=await get_session_store().get_session_with_messages(d['session_id'])
 return {'chat_preserved':any(x.get('content')=='existing learning record' for x in s['messages']), 'task_preserved':any(x.id==d['task_id'] and x.title=='existing task' for x in get_task_board_store().read().cards), 'saved_key_preserved':'fixture-only-not-a-real-key' in json.dumps(get_model_catalog_service().load())}
r=asyncio.run(f()); assert all(r.values()),r; print(json.dumps(r))
`;
const result = execFileSync(path.join(root, runtimeLayout().python), ['-c', code], {
  encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.join(root, 'core'), DEEPTUTOR_HOME: config.runtimeHome,
    PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, maxBuffer: 2 * 1024 ** 2,
});
const data = JSON.parse(result.trim().split('\n').at(-1));
if (mode === 'seed') await writeFile(path.join(home, 'before.json'), JSON.stringify(data));
await writeFile(output, JSON.stringify({ mode, native_platform: process.platform, native_arch: process.arch,
  ready: true, textbooks: books, real_keys_used: false, ...(mode === 'bridge' ? data : {}) }, null, 2) + '\n');
