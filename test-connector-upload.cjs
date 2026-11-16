const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const script = readFileSync(join(__dirname, 'connector-upload-candidate.js'), 'utf8');
const files = new Map(Array.from({ length: 5 }, (_, i) => [`source-overlay.${i}`, Buffer.alloc(i === 4 ? 600001 : 524288, 65 + i)]));
const hash = (value, kind = 'sha256') => createHash(kind).update(value).digest('hex');
const rows = [...files].map(([file, data]) => ({ file, bytes: data.length, sha256: hash(data), git_blob_sha: hash(Buffer.concat([Buffer.from(`blob ${data.length}\0`), data]), 'sha1') }));
const plan = { repository: '1281504089-cell/kaixin-k12-tutor', branch: 'codex/k12-core-20261117-offline-test', parent_sha: 'a'.repeat(40), base_tree_sha: 'b'.repeat(40), tag: 'student-20261117-k12-1', files: rows, never_merge_into_main: true };
const checkpoint = new Map();
const uploads = new Map();
let failOnce = true, commits = 0, branches = 0, trees = 0, branchHead, output;
const tools = {
  async exec_command({ cmd }) {
    let result;
    if (cmd.endsWith(' state')) result = { plan, checkpoint: [...checkpoint.values()] };
    else if (cmd.includes(' checkpoint ')) {
      const record = JSON.parse(Buffer.from(cmd.split(' ').at(-1), 'base64').toString());
      checkpoint.set(record.file || 'FINAL', record); result = { saved: true };
    } else {
      const [, file, offset] = /--file (\S+) --offset (\d+)/.exec(cmd);
      const size = files.get(file).length <= 512 * 1024 ? 512 * 1024 : 384 * 1024;
      const data = files.get(file).subarray(Number(offset), Number(offset) + size);
      result = { file, offset: Number(offset), bytes: data.length, base64: data.toString('base64') };
    }
    return { exit_code: 0, output: JSON.stringify(result) };
  },
  async mcp__codex_apps__github_create_blob({ content, encoding }) {
    assert.equal(encoding, 'base64');
    const data = Buffer.from(content, 'base64');
    const row = rows.find(row => files.get(row.file).equals(data));
    assert(row, 'Chunk concatenation changed the bytes');
    uploads.set(row.file, (uploads.get(row.file) || 0) + 1);
    if (row.file === 'source-overlay.1' && failOnce) { failOnce = false; throw Error('synthetic API failure'); }
    return { structuredContent: { sha: row.git_blob_sha } };
  },
  async mcp__codex_apps__github_create_tree({ tree_elements }) { trees++; assert.equal(tree_elements.length, 5); return { structuredContent: { sha: 'c'.repeat(40) } }; },
  async mcp__codex_apps__github_create_commit() { commits++; return { structuredContent: { sha: 'd'.repeat(40) } }; },
  async mcp__codex_apps__github_create_branch({ branch_name, sha }) { branches++; assert.equal(branch_name, plan.branch); branchHead = sha; throw Error('synthetic lost response after branch creation'); },
  async mcp__codex_apps__github_fetch() { return { structuredContent: { content: JSON.stringify({ object: { sha: branchHead } }) } }; },
};
(async () => {
  const run = () => new AsyncFunction('tools', 'notify', 'text', script)(tools, () => {}, value => { output = value; });
  await assert.rejects(run(), /Stopped after this batch/);
  assert.equal(checkpoint.size, 3); assert.equal(trees, 0); assert.equal(commits, 0); assert.equal(branches, 0);
  await run();
  assert.equal(checkpoint.size, 6); assert.equal(trees, 1); assert.equal(commits, 1); assert.equal(branches, 1);
  assert.equal(uploads.get('source-overlay.1'), 2);
  for (const row of rows.filter(row => row.file !== 'source-overlay.1')) assert.equal(uploads.get(row.file), 1);
  assert.equal(output.main_changed, false); assert.equal(checkpoint.get('FINAL').status, 'temporary_candidate_branch_created');
  checkpoint.clear(); uploads.clear();
  Object.assign(plan, {status:'bank-only-frozen',source_pending:true,no_tree_commit_branch_ref_or_ci:true});
  let limit = 2;
  const bankRun = () => new AsyncFunction('tools','notify','text','load',script)(tools,()=>{},value=>{output=value;},key=>key==='connector_upload_mode'?'bank-only-frozen':key==='connector_upload_limit'?limit:undefined);
  await bankRun(); assert.equal(checkpoint.size,2); assert.equal(trees,1); assert.equal(branches,1);
  limit = undefined;
  await bankRun(); assert.equal(checkpoint.size,5); assert.equal(trees,1); assert.equal(commits,1); assert.equal(branches,1);
  assert.equal(output.status,'bank-only-frozen');assert.equal(output.source_pending,true);assert.equal(output.no_tree_commit_branch_ref_or_ci,true);
  assert([...uploads.values()].every(value=>value===1));
  console.log('PASS: exact multichunk bytes, four-call failure checkpoint, missing-only resume, and unknown branch outcome readback; 0 real API calls');
  console.log('PASS: bank-only two-blob probe then missing-only continuation creates no tree, commit, branch or ref');
})().catch(error => { console.error(error); process.exitCode = 1; });
