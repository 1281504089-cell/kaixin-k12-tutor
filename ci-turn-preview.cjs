const assert = require('node:assert/strict');
const {writeFileSync} = require('node:fs');
const {join} = require('node:path');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

module.exports = async function verifyPreview(view, evidence, seed) {
  const js = (fn, ...args) => view.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`, true);
  const origin = new URL(view.getURL()).origin;
  assert(['127.0.0.1','localhost','[::1]'].includes(new URL(origin).hostname));
  assert.equal(seed.titles.length, 8);
  const debug = view.debugger;
  assert(!debug.isAttached());
  const views = [];
  async function wait(fn, label, timeout = 60000) {
    const until = Date.now() + timeout;
    while (!await js(fn)) { assert(Date.now() < until, label); await pause(100); }
  }
  async function moveTo(selector, click = false) {
    if (!click) await debug.sendCommand('Input.dispatchMouseEvent',{type:'mouseMoved',x:2,y:2});
    let point;
    let lastHit;
    const deadline = Date.now()+5000;
    while (!point) {
      const sample = await js(selector => {
        const element = document.querySelector(selector);
        if (!element) return null;
        element.scrollIntoView({block:'nearest'});
        const rect = element.getBoundingClientRect();
        const x = Math.round(rect.left+rect.width/2);
        const y = Math.round(rect.top+rect.height/2);
        const hit = document.elementFromPoint(x,y);
        return {x,y,actionable:!!hit&&element.contains(hit),hit:hit?.closest('button,[role="dialog"]')?.getAttribute('aria-label')||hit?.tagName};
      }, selector);
      lastHit = sample?.hit;
      if (sample?.actionable) point = {x:sample.x,y:sample.y};
      else {
        assert(Date.now()<deadline, `Preview action unavailable: ${selector}, hit ${lastHit}`);
        await pause(100);
      }
    }
    await debug.sendCommand('Input.dispatchMouseEvent',{type:'mouseMoved',...point});
    if (click) {
      await debug.sendCommand('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
      await debug.sendCommand('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
    }
  }
  debug.attach('1.3');
  try {
    for (const [width,height] of [[390,844],[844,390],[1366,900],[1920,1080]]) {
      await debug.sendCommand('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
      await view.loadURL(`${origin}/chat/${encodeURIComponent(seed.session)}?dt_workspace=`);
      await wait(() => document.querySelectorAll('[data-chat-turn-navigator] [data-tick]').length === 8, 'Eight question marks did not render');
      await pause(500);
      const rail = await js(() => {
        const el = document.querySelector('[data-chat-turn-navigator]');
        if (!el) return {visible:'missing',overflow:false};
        return {visible:getComputedStyle(el).visibility,overflow:document.documentElement.scrollWidth>innerWidth};
      });
      assert.equal(rail.visible,'visible'); assert(!rail.overflow);
      const viewer = '.dt-viewer-panel[data-open="true"]';
      if (await js(selector => Boolean(document.querySelector(selector)), viewer)) {
        await moveTo(viewer+' button[aria-label="关闭查看器"],'+viewer+' button[aria-label="Close viewer"]',true);
        await wait(() => !document.querySelector('.dt-viewer-panel[data-open="true"]'), 'The existing activity drawer stayed open');
      }
      const mark = '[data-chat-turn-navigator] [data-tick]';
      await moveTo(mark);
      await wait(() => Boolean(document.querySelector('[data-turn-preview]')), 'Hover did not open preview');
      const card = await js(() => {
        const el = document.querySelector('[data-turn-preview]'),r=el.getBoundingClientRect();
        const root=document.querySelector('[data-chat-scroll-root]').getBoundingClientRect();
        return {text:el.innerText,left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth,height:innerHeight,paneTop:root.top,paneBottom:root.bottom};
      });
      assert(card.text.includes(seed.titles[0]));
      assert(card.text.includes(seed.answers[0]));
      assert(card.top>=card.paneTop-1 && card.bottom<=card.paneBottom+1,'Preview covers composer: '+JSON.stringify(card));
      assert(card.left>=0 && card.right<=card.width+1 && card.top>=0 && card.bottom<=card.height+1,JSON.stringify(card));
      writeFileSync(join(evidence,`quick-preview-${width}x${height}.png`),(await view.capturePage()).toPNG());
      await moveTo(mark,true);
      const jumpStarted=Date.now();
      await wait(() => {
        const root=document.querySelector('[data-chat-scroll-root]'),mark=document.querySelector('[data-tick]');
        const target=root.querySelector(`[data-turn-key="${mark.dataset.tick}"]`);
        return Math.abs(target.getBoundingClientRect().top-root.getBoundingClientRect().top)<160;
      },'Click did not reach original question',3000);
      const jumpMilliseconds=Date.now()-jumpStarted;
      await moveTo(mark);
      await wait(() => Boolean(document.querySelector('[data-turn-preview] button')), 'Hover did not reopen the preview after jumping');
      await moveTo('[data-turn-preview] button',true);
      await wait(() => !document.querySelector('[data-turn-preview]'), 'The preview did not close after clicking the card',3000);
      views.push({width,height,visible:true,previewCorrect:true,jumpToOriginal:true,jumpMilliseconds,cardWithinViewport:true,cardWithinMessagePane:true});
    }
    await view.loadURL(`${origin}/chat?dt_workspace=`);
    await wait(() => Boolean(document.querySelector('textarea')), 'New conversation did not load');
    assert.equal(await js(() => document.querySelectorAll('[data-tick],[data-turn-preview]').length),0,'Preview leaked into another conversation');
    const result={passed:true,actualNativeRenderer:true,views,conversationSwitchCleared:true,paidModelCalls:0,realStudentData:false};
    writeFileSync(join(evidence,'quick-preview.json'),JSON.stringify(result,null,2)+'\n');
    return result;
  } finally {
    await debug.sendCommand('Emulation.clearDeviceMetricsOverride');
    debug.detach();
  }
};
