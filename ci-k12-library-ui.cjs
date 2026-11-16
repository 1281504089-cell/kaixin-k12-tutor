const assert = require('node:assert/strict');
const { writeFileSync } = require('node:fs');
const { join } = require('node:path');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

module.exports = async function verifyK12Library(view, evidence, seed) {
  const js = (fn, ...args) => view.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`, true);
  const origin = new URL(view.getURL()).origin;
  assert(['127.0.0.1', 'localhost', '[::1]'].includes(new URL(origin).hostname));
  assert.equal(seed.model_calls, 0);
  const debug = view.debugger;
  assert(!debug.isAttached());
  const views = [];
  async function wait(fn, args, label, timeout = 60000) {
    const until = Date.now() + timeout;
    while (!await js(fn, ...args)) { assert(Date.now() < until, label); await pause(100); }
  }
  async function click(selector) {
    const point = await js(selector => {
      const el = document.querySelector(selector);
      if (!el) throw Error('Missing source action: ' + selector);
      el.scrollIntoView({ block: 'nearest' });
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
    }, selector);
    view.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
    view.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...point });
  }
  debug.attach('1.3');
  try {
    for (const [width, height] of [[390, 844], [844, 390], [1366, 900], [1920, 1080]]) {
      await debug.sendCommand('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await view.loadURL(`${origin}/space?dt_workspace=`);
      await wait(() => [...document.querySelectorAll('button')].some(el => el.textContent.trim() === '题库'), [], 'Two library entries did not render');
      const shelf = await js(() => {
        const buttons = [...document.querySelectorAll('button')];
        const main = buttons.filter(el => ['教材库', '题库'].includes(el.textContent.trim()));
        const upload = buttons.find(el => el.getAttribute('aria-expanded') !== null && /我的上传资料/.test(el.textContent));
        return { count: main.length, selected: main.filter(el => el.getAttribute('aria-pressed') === 'true').length, uploadSeparate: !!upload, overflow: document.documentElement.scrollWidth > innerWidth + 1 };
      });
      assert.deepEqual(shelf, { count: 2, selected: 1, uploadSeparate: true, overflow: false });
      await js(() => [...document.querySelectorAll('button')].find(el => el.textContent.trim() === '题库').click());
      await wait(() => !!document.querySelector('[aria-label="按学科筛选题库"] button[aria-pressed="true"]') && !!document.querySelector('button[aria-label^="查看题源："]'), [], 'Real question-pack catalog did not render');
      await click('button[aria-label^="查看题源："]');
      await wait(() => !!document.querySelector('section[aria-label="题库"] a[href^="#dt-question-"]'), [], 'Source did not list complete original-material links');
      await click('section[aria-label="题库"] a[href^="#dt-question-"]');
      await wait(() => document.querySelector('[data-testid="question-source-preview"]')?.getAttribute('data-source-ready') === 'true', [], 'Library question did not finish original images');
      await click('button[aria-label="关闭题源"]');
      await wait(() => !document.querySelector('[role="dialog"]'), [], 'Source did not close');
      writeFileSync(join(evidence, `k12-library-${width}x${height}.png`), (await view.capturePage()).toPNG());
      await view.loadURL(`${origin}/chat/${encodeURIComponent(seed.session)}?dt_workspace=`);
      await wait(href => [...document.querySelectorAll('a[href]')].some(el => el.getAttribute('href') === href), [seed.href], 'Persisted answer did not restore its actual-source link');
      const link = await js(href => {
        const el = [...document.querySelectorAll('a[href]')].find(el => el.getAttribute('href') === href);
        el.scrollIntoView({ block: 'center' });
        return { color: getComputedStyle(el).color, text: el.textContent };
      }, seed.href);
      const colors = link.color.match(/[\d.]+/g).map(Number);
      assert(colors[2] > colors[0] && colors[2] >= colors[1], 'Actual source is not visibly blue: ' + link.color);
      await js(href => [...document.querySelectorAll('a[href]')].find(el => el.getAttribute('href') === href).setAttribute('data-k12-probe-link', ''), seed.href);
      await click('[data-k12-probe-link]');
      await wait((id, rev) => {
        const el = document.querySelector('[data-testid="question-source-preview"]');
        return el?.dataset.questionId === id && el.dataset.bankRevision === rev && el.dataset.sourceReady === 'true';
      }, [seed.qualified_id, seed.bank_revision], 'History citation opened the wrong question/revision or lost an original image');
      const dialog = await js(() => {
        const el = document.querySelector('[role="dialog"]'), r = el.getBoundingClientRect();
        const body = document.querySelector('[data-testid="question-source-preview"]');
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, text: body.innerText, images: [...body.querySelectorAll('img')].map(img => img.complete && img.naturalWidth > 0), overflow: document.documentElement.scrollWidth > innerWidth + 1 };
      });
      assert(dialog.text.trim().length > 20 && dialog.images.every(Boolean));
      assert(dialog.left >= -1 && dialog.right <= width + 1 && dialog.top >= -1 && dialog.bottom <= height + 1 && !dialog.overflow, 'Original source escapes the viewport');
      writeFileSync(join(evidence, `k12-source-${width}x${height}.png`), (await view.capturePage()).toPNG());
      await click('button[aria-label="关闭题源"]');
      await wait(() => !document.querySelector('[role="dialog"]'), [], 'History source did not close');
      views.push({ width, height, twoLibraryEntries: true, separateUploads: true, sourceCardOpened: true, restoredCitationBlue: true, exactQuestionAndRevision: true, allOriginalImagesLoaded: true, dialogWithinViewport: true, closeReturned: true });
    }
    const result = { passed: true, actualNativeRenderer: true, bank_revision: seed.bank_revision, views, model_calls: 0, formal_data_used: false };
    writeFileSync(join(evidence, 'k12-library.json'), JSON.stringify(result, null, 2) + '\n');
    return result;
  } finally {
    await debug.sendCommand('Emulation.clearDeviceMetricsOverride');
    debug.detach();
  }
};
