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
  async function wait(fn, label) {
    const until = Date.now() + 60000;
    while (!await js(fn)) { assert(Date.now() < until, label); await pause(100); }
  }
  async function moveTo(selector, click = false) {
    const point = await js(selector => {
      const el = document.querySelector(selector);
      if (!el) throw Error('Missing preview action: ' + selector);
      el.scrollIntoView({block:'nearest'});
      const r = el.getBoundingClientRect();
      return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};
    }, selector);
    view.sendInputEvent({type:'mouseMove',...point}); await pause(200);
    if (click) {
      view.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,...point});
      view.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,...point});
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
        return {visible:getComputedStyle(el).visibility,overflow:document.documentElement.scrollWidth>innerWidth};
      });
      assert.equal(rail.visible,'visible'); assert(!rail.overflow);
      const mark = '[data-chat-turn-navigator] [data-tick]';
      await moveTo(mark);
      await wait(() => Boolean(document.querySelector('[data-turn-preview]')), 'Hover did not open preview');
      const card = await js(() => {
        const el = document.querySelector('[data-turn-preview]'),r=el.getBoundingClientRect();
        return {text:el.innerText,left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth,height:innerHeight};
      });
      assert(card.text.includes(seed.titles[0]));
      assert(card.text.includes(seed.answers[0]));
      assert(card.left>=0 && card.right<=card.width+1 && card.top>=0 && card.bottom<=card.height+1,JSON.stringify(card));
      writeFileSync(join(evidence,`quick-preview-${width}x${height}.png`),(await view.capturePage()).toPNG());
      await moveTo(mark,true);
      await pause(700);
      const jumped = await js(() => {
        const root=document.querySelector('[data-chat-scroll-root]'),mark=document.querySelector('[data-tick]');
        const target=root.querySelector(`[data-turn-key="${mark.dataset.tick}"]`);
        return Math.abs(target.getBoundingClientRect().top-root.getBoundingClientRect().top)<160;
      });
      assert(jumped,'Click did not reach original question');
      await moveTo('[data-turn-preview] button',true);
      await pause(250);
      assert.equal(await js(() => document.querySelectorAll('[data-turn-preview]').length),0);
      views.push({width,height,visible:true,previewCorrect:true,jumpToOriginal:true,cardWithinViewport:true});
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
