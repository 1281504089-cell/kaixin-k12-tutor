const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

module.exports = async function verifyBank(view) {
  const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'online-bank-expectations.json')));
  const result = await view.executeJavaScript(`(${async function check(fixture) {
    async function fetchLocal(pathname) {
      const url = new URL(pathname, location.href);
      if (url.origin !== location.origin) throw new Error('Question asset escaped localhost');
      const response = await fetch(url, { cache: 'no-store' });
      if (!response.ok) throw new Error(url.pathname + ' returned ' + response.status);
      return response;
    }
    const detail = (id, revision) => fetchLocal('/api/student/question-bank/questions/' + encodeURIComponent(id) + '?revision=' + revision).then(response => response.json());
    async function hash(response) {
      return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await response.arrayBuffer())), byte => byte.toString(16).padStart(2, '0')).join('');
    }
    const questions = [];
    for (const expected of fixture.questions) {
      const row = await detail(expected.id, fixture.revision);
      if (row.qualified_id !== expected.id || row.bank_revision !== fixture.revision || row.source_hash !== expected.source ||
          row.source_payload_sha256 !== expected.payload || row.source.native_required !== false || !row.content_read) {
        throw new Error('Question identity or inline original mismatch: ' + expected.id);
      }
      for (const [id, sha] of Object.entries(expected.assets)) {
        const asset = row.assets.find(asset => asset.id === id);
        if (!asset || await hash(await fetchLocal(asset.url)) !== sha) throw new Error('Wrong original figure: ' + expected.id);
      }
      if (expected.previous) {
        const old = await detail(expected.id, fixture.previous_revision);
        if (old.source_payload_sha256 !== expected.previous || old.source_hash !== expected.source) throw new Error('Retained reference changed: ' + expected.id);
      }
      questions.push(expected.id);
    }
    const original = [];
    for (const revision of [fixture.previous_revision, fixture.revision]) {
      const sample = await detail(fixture.native_sample.id, revision);
      const pdf = await fetchLocal(sample.source.native.url);
      if (pdf.headers.get('content-type') !== 'application/pdf' || await hash(pdf) !== fixture.native_sample.sha256) throw new Error('Existing original page changed: ' + revision);
      original.push(revision);
    }
    return { questions, original, revision: fixture.revision };
  }})(${JSON.stringify(fixture)})`);
  assert.equal(result.questions.length, 38);
  assert.equal(result.original.length, 2);
  return result;
};
