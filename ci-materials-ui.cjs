// Synthetic native acceptance against the exact updated production renderer.
const assert = require('node:assert/strict');
const { writeFile } = require('node:fs/promises');
const path = require('node:path');
async function loadInitialLibrary(view, evidence) {
  const initial = new URL(view.getURL());
  const target = new URL('/space?dt_workspace=', initial).href;
  try {
    return await view.loadURL(target);
  } catch (error) {
    const retry = initial.protocol === 'http:' && initial.hostname === '127.0.0.1'
      && !initial.username && !initial.password
      && error.code === 'ERR_NETWORK_CHANGED' && error.errno === -21 && error.url === target;
    const receipt = { url: target, first_error: { message: error.message, code: error.code, errno: error.errno, url: error.url },
      retry_count: 0, status: retry ? 'retry_scheduled' : 'failed', recorded_at: new Date().toISOString() };
    const file = path.join(evidence, `materials-navigation-${process.pid}-${Date.now()}.json`);
    await writeFile(file, JSON.stringify(receipt, null, 2));
    if (!retry) throw error;
    // Only this safe first GET can repeat; uploads and all later acceptance gates remain untouched.
    await new Promise(resolve => setTimeout(resolve, 500));
    receipt.retry_count = 1;
    try {
      const result = await view.loadURL(target);
      receipt.status = 'retry_succeeded';
      receipt.completed_at = new Date().toISOString();
      await writeFile(file, JSON.stringify(receipt, null, 2));
      return result;
    } catch (retryError) {
      receipt.status = 'retry_failed';
      receipt.retry_error = { message: retryError.message, code: retryError.code, errno: retryError.errno, url: retryError.url };
      receipt.completed_at = new Date().toISOString();
      await writeFile(file, JSON.stringify(receipt, null, 2));
      throw retryError;
    }
  }
}
module.exports = async function verifyMaterials(view, evidence, mathFixture) {
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const js = (fn, ...args) => view.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`);

  function mathReady(selector, count, identity) {
    const enough = document.querySelectorAll(selector).length >= count;
    if (!identity) return enough;
    const articles = [...document.querySelectorAll('article')];
    return enough && typeof identity.title === 'string' && identity.title.length > 0
      && new URLSearchParams(location.search).get('record') === identity.record
      && articles.length === 1 && articles[0].querySelector('h2')?.textContent.trim() === identity.title;
  }

  async function captureMathFailure(key, targetUrl, selector, count, error) {
    const stem = 'native-math-' + key + '-failure-' + process.pid + '-' + Date.now();
    const report = { key, target_url: targetUrl, expected_record: mathFixture[key], selector, expected_count: count,
      expected_title: key === 'mistake' ? (mathFixture.mistake_title ?? null) : null,
      original_error: String(error.stack || error), captured_at: new Date().toISOString() };
    try { report.actual_url = view.getURL(); } catch (caught) { report.url_capture_error = String(caught); }
    try {
      report.snapshot = await js(async (selector, expectedRecord) => {
        const article = document.querySelector('article');
        const nodes = [...document.querySelectorAll(selector)];
        const layoutVisible = node => [...node.getClientRects()].some(rect => rect.width > 0 && rect.height > 0)
          && getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none';
        const inViewport = node => layoutVisible(node) && [...node.getClientRects()].some(rect => rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth);
        const apiResources = performance.getEntriesByType('resource').filter(row => /\/api\/student\/mistakes(?:[?\/]|$)/.test(row.name))
          .slice(-20).map(row => ({ url: row.name, duration: row.duration, response_status: row.responseStatus > 0 ? row.responseStatus : null, transfer_size: row.transferSize }));
        const snapshot = { url: location.href, current_record: new URLSearchParams(location.search).get('record'),
          expected_record: expectedRecord, ready_state: document.readyState, viewport: { width: innerWidth, height: innerHeight },
          article_count: document.querySelectorAll('article').length, actual_article_h2: article?.querySelector('h2')?.textContent.trim() ?? null, katex_count: nodes.length,
          layout_visible_count: nodes.filter(layoutVisible).length, in_viewport_count: nodes.filter(inViewport).length,
          hidden_count: nodes.filter(node => !layoutVisible(node)).length,
          errors: [...document.querySelectorAll('.katex-error')].map(node => ({ text: node.textContent, title: node.getAttribute('title') })).slice(0, 20),
          formulas: nodes.slice(0, 30).map(node => ({ text: node.querySelector('.katex-html')?.textContent ?? node.textContent, layout_visible: layoutVisible(node), in_viewport: inViewport(node) })),
          details: [...document.querySelectorAll('article details')].map(node => ({ open: node.open, katex_count: node.querySelectorAll('.katex').length })),
          selected_buttons: [...document.querySelectorAll('button[aria-pressed="true"]')].map(node => node.textContent.slice(0, 300)).slice(0, 12),
          article_text: article?.innerText.slice(0, 8000) ?? '', body_text: document.body.innerText.slice(0, 8000),
          html: article?.outerHTML.slice(0, 180000) ?? document.body.outerHTML.slice(0, 30000), api_resources: apiResources,
          named_workspace: new URLSearchParams(location.search).get('dt_workspace'),
          script_resources: performance.getEntriesByType('resource').filter(row => row.initiatorType === 'script').slice(-20).map(row => ({ url: row.name, duration: row.duration, response_status: row.responseStatus > 0 ? row.responseStatus : null })) };
        try { snapshot.workspace_storage = { local: localStorage.getItem('deeptutor:workspace'), session: sessionStorage.getItem('deeptutor:workspace') }; }
        catch (caught) { snapshot.workspace_storage_error = String(caught); }
        if (new URLSearchParams(location.search).get('record') === expectedRecord) {
          const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
          const url = new URL('/api/student/mistakes?practice=' + encodeURIComponent(expectedRecord) + '&dt_workspace=', location.href).href;
          snapshot.api_probe = { kind: 'failure-time read-only practice GET; not the original request', url, requested_record: expectedRecord,
            not_exposed_by_endpoint: ['id', 'status', 'analysis', 'source'] };
          try {
            const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin', signal: controller.signal });
            snapshot.api_probe.status = response.status; snapshot.api_probe.ok = response.ok;
            if (response.ok) {
              const data = await response.json();
              snapshot.api_probe.target = { title: data.title ?? null, subject: data.subject ?? null,
                question: data.question ?? null, student_work: data.student_work ?? null,
                image_count: Array.isArray(data.images) ? data.images.length : null };
            }
          } catch (caught) { snapshot.api_probe.error = String(caught); }
          finally { clearTimeout(timer); }
        }
        return snapshot;
      }, selector, mathFixture[key]);
      if (report.snapshot.html) {
        try { await writeFile(path.join(evidence, stem + '.html'), report.snapshot.html); report.dom_file = stem + '.html'; }
        catch (caught) { report.dom_write_error = String(caught); }
        delete report.snapshot.html;
      }
    } catch (caught) { report.snapshot_error = String(caught); }
    try { await writeFile(path.join(evidence, stem + '.png'), (await view.capturePage()).toPNG()); report.screenshot_file = stem + '.png'; }
    catch (caught) { report.screenshot_error = String(caught); }
    try { await writeFile(path.join(evidence, stem + '.json'), JSON.stringify(report, null, 2)); }
    catch (caught) { console.warn('Math failure diagnostics could not be saved:', String(caught)); }
  }
  async function wait(code, label) {
    const deadline = Date.now() + 180000;
    while (!await view.executeJavaScript(code)) {
      assert.ok(Date.now() < deadline, label);
      await pause(250);
    }
  }
  const click = async text => {
    await wait(`([...document.querySelectorAll('button,a,[role="menuitem"]')].some(node => node.offsetHeight && node.textContent.trim() === ${JSON.stringify(text)}))`, 'Missing visible action: ' + text);
    return js(text => {
    const node = [...document.querySelectorAll('button,a,[role="menuitem"]')].find(node => node.offsetHeight && node.textContent.trim() === text);
    if (!node) throw new Error('Missing visible action: ' + text);
    node.click();
    }, text);
  };
  async function chat() {
    await js(() => {
      const link = [...document.querySelectorAll('a[href^="/chat"]')].find(node => node.offsetHeight);
      if (!link) throw new Error('No visible chat navigation');
      link.click();
    });
    await wait('location.pathname.startsWith("/chat") && Boolean(document.querySelector("textarea")?.offsetHeight)', 'Chat navigation failed');
  }
  async function library() {
    await click('资料');
    await click('资料库');
    await wait('location.pathname === "/space" && Boolean(document.querySelector(\'[role="group"][aria-label="资料类型"]\'))', 'Library navigation failed');
    await click('长期资料');
    await wait('Boolean(document.querySelector(\'input[aria-label="选择要长期保存的资料"]\'))', 'Long-term upload navigation failed');
  }
  await loadInitialLibrary(view, evidence);
  await click('长期资料');
  await wait('Boolean(document.querySelector(\'input[aria-label="选择要长期保存的资料"]\'))', 'Updated library did not expose bulk upload');
  const originals = Array.from({ length: 20 }, (_, index) => ({ name: `native-background-${index.toString().padStart(2, '0')}.txt`, text: `SYNTHETIC NATIVE ORIGINAL ${index}\n切换页面后继续保存。` }));
  originals.push({ name: 'native-listening.html', text: '<!DOCTYPE html><html><body><h1>Synthetic listening</h1><div class="row"><span class="text">Hello student.</span><button onclick="speakOne(0)">Play one</button></div><script>window.attachmentExecuted=true</script><a href="https://example.com">external</a></body></html>' });
  await js(() => {
    window.__materialsDocument = 'same-document';
    const original = window.fetch.bind(window);
    window.__materialsPosts = [];
    window.__materialsHeld = false;
    const held = new Promise(resolve => { window.__materialsRelease = resolve; });
    window.fetch = async (...args) => {
      const url = String(args[0]);
      if (args[1]?.method === 'POST') window.__materialsPosts.push(url);
      if (!window.__materialsHeld && /\/uploads\/[^/]+\/chunks\/0/.test(url)) {
        window.__materialsHeld = true;
        await held;
      }
      const response = await original(...args);
      if (url.includes('/materials/attach') && response.ok) window.__materialsAttached = await response.clone().json();
      return response;
    };
  });
  async function select(files) {
    assert.equal(await js(files => {
      const input = document.querySelector('input[aria-label="选择要长期保存的资料"]');
      const data = new DataTransfer();
      for (const file of files) data.items.add(new File([file.text], file.name, { type: file.name.endsWith('.html') ? 'text/html' : 'text/plain' }));
      input.files = data.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return input.multiple;
    }, files), true);
  }
  await select(originals.slice(0, 20));
  await wait('window.__materialsHeld', 'The real first upload chunk was not held');
  await chat();
  await js(() => {
    const profile = [...document.querySelectorAll('button')].find(node => node.offsetHeight && node.textContent.trim() === '开心动力超级学霸');
    if (!profile) throw new Error('Profile menu missing');
    profile.click();
  });
  await click('设置');
  await wait('location.pathname === "/settings/general" && document.body.innerText.includes("常规")', 'Settings navigation failed');
  await click('返回应用');
  await wait('location.pathname.startsWith("/chat")', 'Return from settings failed');
  await library();
  await wait('document.body.innerText.includes("已保存 0/20 份")', 'Queue did not survive page changes');
  await select(originals.slice(20));
  await wait('document.body.innerText.includes("已保存 0/21 份")', 'Could not append to active queue');
  await chat();
  const draft = 'SYNTHETIC retained draft; never send to a model.';
  await js(draft => {
    const input = document.querySelector('textarea');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, draft);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    window.__materialsRelease();
  }, draft);
  await wait('document.body.innerText.includes("资料上传完成：已保存 21 份，已自动加入资料库。")', 'Background upload did not finish in chat');
  assert.equal(await js(() => document.querySelector('textarea').value), draft);
  await library();
  await wait('document.body.innerText.includes("已保存 21/21 份")', 'Returning library did not refresh');
  assert.equal(await js(() => window.__materialsDocument), 'same-document');
  const retained = await js(async originals => {
    const response = await fetch('/api/student/attachments/uploads/library?dt_workspace=');
    if (!response.ok) throw new Error('Library catalogue failed');
    const uploads = (await response.json()).uploads;
    for (const file of originals) {
      const upload = uploads.find(row => row.retention === 'library' && row.records.some(row => row.filename === file.name));
      if (!upload) throw new Error('Missing retained original: ' + file.name);
      const record = upload.records.find(row => row.filename === file.name);
      const raw = await fetch(record.url);
      if (!raw.ok || await raw.text() !== file.text) throw new Error('Original changed: ' + file.name);
      if (![...document.querySelectorAll('article h2')].some(node => node.textContent === file.name)) throw new Error('Saved card missing: ' + file.name);
    }
    return uploads.length;
  }, originals);
  await js(() => {
    const card = [...document.querySelectorAll('article')].find(node => node.querySelector('h2')?.textContent === 'native-listening.html');
    [...card.querySelectorAll('button')].find(node => node.textContent.trim() === '打开原件').click();
  });
  await wait('Boolean(document.querySelector(\'iframe[title="native-listening.html"]\')?.srcdoc)', 'HTML did not render an isolated page');
  const safe = await js(() => {
    const frame = document.querySelector('iframe[title="native-listening.html"]');
    return frame.sandbox.value === 'allow-scripts' && !frame.srcdoc.includes('window.attachmentExecuted=true') && !frame.srcdoc.includes('href="https://example.com"') && frame.srcdoc.includes("connect-src 'none'");
  });
  assert.equal(safe, true);
  let frame;
  const frameDeadline = Date.now() + 30000;
  while (!(frame = view.mainFrame.framesInSubtree.find(frame => frame.url === 'about:srcdoc'))) {
    assert.ok(Date.now() < frameDeadline, 'Missing native HTML subframe: ' + JSON.stringify(view.mainFrame.framesInSubtree.map(frame => frame.url)));
    await pause(100);
  }
  const speech = await frame.executeJavaScript(`(async () => {
    let parentBlocked = false; try { parent.document.body } catch { parentBlocked = true }
    let networkBlocked = false; try { await fetch('https://example.com/kaixin-isolation-probe') } catch { networkBlocked = true }
    return { available: typeof speechSynthesis === 'object', parentBlocked, networkBlocked, attachmentScriptBlocked: !window.attachmentExecuted, noNode: typeof require === 'undefined', noDesktopIPC: !window.kaixinDesktop, localVoices: speechSynthesis.getVoices().filter(v => v.localService).length };
  })()`, true);
  assert.ok(speech.available && speech.parentBlocked && speech.networkBlocked && speech.attachmentScriptBlocked && speech.noNode && speech.noDesktopIPC);
  speech.diagnostic = await require('./native-html-speech-diagnostic.cjs')(frame);
  speech.observedStatus = speech.diagnostic.observedStatus;
  speech.playbackVerified = speech.diagnostic.nativeEnded;
  speech.diagnosticOnly = true;
  await writeFile(path.join(evidence, 'native-html-preview.png'), (await view.capturePage()).toPNG());
  await click('源码');
  await wait('Boolean(document.querySelector("pre")?.textContent.includes("window.attachmentExecuted=true"))', 'HTML source toggle failed');
  await js(() => document.querySelector('button[aria-label="关闭原件预览"]')?.click());
  await wait('!document.querySelector(\'button[aria-label="关闭原件预览"]\')', 'Preview did not close');
  await chat();
  await js(() => { document.querySelector('button[aria-label="资源"]').click(); });
  await wait('document.body.innerText.includes("引用资料")', 'Composer library action missing');
  await js(() => [...document.querySelectorAll('button')].find(node => node.offsetHeight && node.textContent.includes('引用资料')).click());
  await wait('Boolean(document.querySelector(\'[role="dialog"] [role="group"][aria-label="资料类型"]\'))', 'Shared reference shelves did not open in this chat');
  const referenceShelves=await js(()=>{const group=document.querySelector('[role="dialog"] [role="group"][aria-label="资料类型"]');return [...group.querySelectorAll('button')].map(node=>({label:node.textContent.trim(),selected:node.getAttribute('aria-pressed')==='true',visible:node.offsetHeight>0}));});
  assert.deepEqual(referenceShelves,[{label:'教材库',selected:true,visible:true},{label:'题库',selected:false,visible:true},{label:'长期资料',selected:false,visible:true}]);
  await click('长期资料');
  await wait('Boolean(document.querySelector(\'[aria-label="搜索资料库"]\')) && [...document.querySelectorAll(\'[role="dialog"] button\')].some(node => node.textContent.includes("native-background-00.txt"))', 'Library picker did not list original');
  const postsBefore = await js(() => window.__materialsPosts.length);
  await js(() => [...document.querySelectorAll('[role="dialog"] button')].find(node => node.textContent.includes('native-background-00.txt')).click());
  await wait('Boolean(window.__materialsAttached) && !document.querySelector(\'[aria-label="搜索资料库"]\')', 'Library reference failed');
  assert.equal(await js(() => document.querySelector('textarea').value), draft);
  await js(async (original, retained, postsBefore) => {
    const file = window.__materialsAttached;
    const raw = await fetch(file.url);
    if (file.filename !== original.name || !raw.ok || await raw.text() !== original.text) throw new Error('Referenced original changed');
    const response = await fetch('/api/student/attachments/uploads/library?dt_workspace=');
    if ((await response.json()).uploads.length !== retained) throw new Error('Reference duplicated a library upload');
    if (window.__materialsPosts.slice(postsBefore).some(url => /\/uploads|\/sessions$/.test(url))) throw new Error('Reference created an upload or conversation');
  }, originals[0], retained, postsBefore);
  await writeFile(path.join(evidence, 'native-library-reference.png'), (await view.capturePage()).toPNG());
  if (mathFixture) {
    for (const [key, route, selector, count] of [
      ['note', '/co-writer/', '.bn-editor .katex', 9],
      ['saved_note', '/co-writer/', '.bn-editor table .katex', 2],
      ['mistake', '/mistakes?record=', 'article .katex', 9],
    ]) {
      const targetUrl = new URL(route + encodeURIComponent(mathFixture[key]), view.getURL()).href;
      try {
        await view.loadURL(targetUrl);
        const identity = key === 'mistake' ? { record: mathFixture[key], title: mathFixture.mistake_title } : null;
        if (identity) assert.ok(typeof identity.title === 'string' && identity.title.length > 0, 'Missing unique mistake fixture title');
        await wait('(' + mathReady.toString() + ')(...' + JSON.stringify([selector, count, identity]) + ')', 'Native math rendering failed: ' + key);
        assert.equal(await js(() => document.querySelectorAll('.katex-error').length), 0);
        assert.equal(await js(() => document.documentElement.scrollWidth <= innerWidth), true);
        await writeFile(path.join(evidence, 'native-math-' + key + '.png'), (await view.capturePage()).toPNG());
      } catch (error) {
        await captureMathFailure(key, targetUrl, selector, count, error);
        throw error;
      }
    }
  }
  const report = { multiple: true, saved_files: 21, library_retention: true, originals_byte_identical: true, original_preview_opened: true,
    held_real_chunk: true, chat_and_settings_navigation: true, appended_while_active: true, completed_in_chat: true,
    document_not_reloaded: true, draft_preserved: true, three_reference_shelves: referenceShelves, picker_reference_byte_identical: true, no_duplicate_upload_or_new_chat: true,
    html_safe_preview: true, source_toggle: true, device_speech: speech, native_math_display: Boolean(mathFixture), real_model_calls: 0 };
  await writeFile(path.join(evidence, 'library-bulk.json'), JSON.stringify(report, null, 2));
  return report;
};
module.exports.loadInitialLibrary = loadInitialLibrary;
