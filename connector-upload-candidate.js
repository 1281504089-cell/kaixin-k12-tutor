// Run only after ROOT freezes CONNECTOR-UPLOAD-PLAN.json, inside functions.exec.
// No Node/fs/private credentials. Transport bytes never go through text()/notify().
const recipe = '/Users/Admin1/Documents/Kaixin-20261115-K12题库工程/release-20261116/recipe';
const bankOnly = typeof load === 'function' && load('connector_upload_mode') === 'bank-only-frozen';
const helper = 'connector-part.py --plan ' + (bankOnly ? 'BANK-CONNECTOR-UPLOAD-PLAN.json' : 'CONNECTOR-UPLOAD-PLAN.json');
async function local(args) {
  const result = await tools.exec_command({cmd: 'python3 -B ' + helper + ' ' + args, workdir: recipe, max_output_tokens: 1500000});
  if (result.exit_code !== 0) throw new Error('Local connector helper failed');
  return JSON.parse(result.output); // Truncation/invalid JSON fails before creating a blob.
}
const state = await local('state');
const plan = state.plan;
if (plan.never_merge_into_main !== true || (bankOnly
  ? plan.status !== 'bank-only-frozen' || plan.source_pending !== true || plan.no_tree_commit_branch_ref_or_ci !== true
  : !/^codex\/k12-core-202611(?:16|17)-/.test(plan.branch))) throw new Error('Wrong transport scope');
const complete = new Map(state.checkpoint.filter(row => row.file).map(row => [row.file, row]));
let final = state.checkpoint.find(row => !row.file);
async function save(record) {
  // Encode fixed ASCII paths/hashes in JS; no JSON string is interpolated into shell code.
  const value = JSON.stringify(record), alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  if ([...value].some(character => character.charCodeAt(0) > 127)) throw new Error('Non-ASCII checkpoint');
  let encoded = '';
  for (let i = 0; i < value.length; i += 3) {
    const a = value.charCodeAt(i), b = value.charCodeAt(i + 1), c = value.charCodeAt(i + 2);
    encoded += alphabet[a >> 2] + alphabet[((a & 3) << 4) | ((b || 0) >> 4)];
    encoded += i + 1 < value.length ? alphabet[((b & 15) << 2) | ((c || 0) >> 6)] : '=';
    encoded += i + 2 < value.length ? alphabet[c & 63] : '=';
  }
  return local('checkpoint --record-base64 ' + encoded);
}
let pending = plan.files.filter(row => {
  const old = complete.get(row.file);
  return !old || old.sha256 !== row.sha256 || old.blob_sha !== row.git_blob_sha;
});
let uploaded = plan.files.length - pending.length;
const limit = bankOnly && typeof load === 'function' ? load('connector_upload_limit') : undefined;
if (Number.isInteger(limit) && limit > 0) pending = pending.slice(0, limit);
notify({resuming_verified_blobs: uploaded, remaining: pending.length, temporary_branch: plan.branch});
for (let offset = 0; offset < pending.length; offset += 4) {
  const results = await Promise.allSettled(pending.slice(offset, offset + 4).map(async row => {
    let content = '';
    for (let position = 0; position < row.bytes;) {
      if (!/^[A-Za-z0-9._\/-]+$/.test(row.file)) throw new Error('Unexpected connector filename');
      const part = await local('read --file ' + row.file + ' --offset ' + position);
      const expected = Math.min(row.bytes <= 512 * 1024 ? 512 * 1024 : 384 * 1024, row.bytes - position);
      if (part.offset !== position || part.bytes !== expected || part.base64.length !== 4 * Math.ceil(expected / 3)) throw new Error('Truncated connector bytes');
      content += part.base64; position += part.bytes;
    }
    const blob = await tools.mcp__codex_apps__github_create_blob({repository_full_name: plan.repository, content, encoding: 'base64'});
    if (blob.isError || blob.structuredContent?.sha !== row.git_blob_sha) throw new Error('Blob SHA mismatch: ' + row.file);
    const record = {file: row.file, sha256: row.sha256, blob_sha: row.git_blob_sha};
    await save(record); complete.set(row.file, record); uploaded++;
  }));
  if (results.some(result => result.status === 'rejected')) {
    notify({checkpointed: uploaded, total: plan.files.length, errors: results.filter(result => result.status === 'rejected').map(result => String(result.reason))});
    throw new Error('Stopped after this batch; preserve checkpoints and resume only missing blobs');
  }
  if (offset % 20 === 0) notify({checkpointed: uploaded, total: plan.files.length});
}
if (bankOnly) {
  text({status: 'bank-only-frozen', source_pending: true, checkpointed: uploaded, total: plan.files.length, no_tree_commit_branch_ref_or_ci: true});
} else {
if (!final) {
  const tree = await tools.mcp__codex_apps__github_create_tree({repository_full_name: plan.repository, base_tree_sha: plan.base_tree_sha, tree_elements: plan.files.map(row => ({path: row.file, mode: '100644', type: 'blob', sha: complete.get(row.file).blob_sha}))});
  if (tree.isError || !tree.structuredContent?.sha) throw new Error('Candidate tree failed');
  const commit = await tools.mcp__codex_apps__github_create_commit({repository_full_name: plan.repository, parent_sha: plan.parent_sha, tree_sha: tree.structuredContent.sha, message: 'Build isolated frozen K12 candidate ' + plan.tag + '; temporary payload branch, never merge into main'});
  if (commit.isError || !commit.structuredContent?.sha) throw new Error('Candidate commit failed');
  final = {branch: plan.branch, parent_sha: plan.parent_sha, commit_sha: commit.structuredContent.sha, tree_sha: tree.structuredContent.sha, status: 'commit_created_branch_pending'};
  await save(final);
}
try {
  const result = await tools.mcp__codex_apps__github_create_branch({repository_full_name: plan.repository, branch_name: plan.branch, sha: final.commit_sha});
  if (result.isError) throw new Error('Branch creation returned an error');
} catch (error) {
  const readback = await tools.mcp__codex_apps__github_fetch({url: 'https://api.github.com/repos/' + plan.repository + '/git/ref/heads/' + plan.branch});
  if (readback.isError || JSON.parse(readback.structuredContent.content).object.sha !== final.commit_sha) throw error;
}
await save({...final, status: 'temporary_candidate_branch_created'});
text({branch: plan.branch, commit: final.commit_sha, files: plan.files.length, main_changed: false, candidate_workflow_trigger_requires_readback: true});
}
