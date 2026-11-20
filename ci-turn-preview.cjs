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
  const viewer = '.dt-viewer-panel[data-open="true"]';
  const closeViewer = viewer+' button[aria-label="关闭查看器"],'+viewer+' button[aria-label="Close viewer"]';
  const mark = '[data-chat-turn-navigator] [data-tick]';
  const preview = '[data-turn-preview]';
  const views = [];
  async function wait(fn, label, timeout = 60000) {
    const until = Date.now() + timeout;
    while (!await js(fn)) { assert(Date.now() < until, label); await pause(100); }
  }
  async function moveTo(selector, click = false) {
    if (!click) await debug.sendCommand('Input.dispatchMouseEvent',{type:'mouseMoved',x:2,y:2});
    let point;
    let lastSample;
    let dismissedViewer = false;
    const deadline = Date.now()+5000;
    while (!point) {
      const sample = await js((selector, viewer) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        element.scrollIntoView({block:'nearest'});
        const rect = element.getBoundingClientRect();
        const x = Math.round(rect.left+rect.width/2);
        const y = Math.round(rect.top+rect.height/2);
        const hit = document.elementFromPoint(x,y);
        return {x,y,actionable:!!hit&&element.contains(hit),hit:hit?.tagName,viewerBlocks:!!hit?.closest(viewer)};
      }, selector, viewer);
      lastSample = sample;
      if (sample?.actionable) point = {x:sample.x,y:sample.y};
      else if (selector === mark && sample?.viewerBlocks && !dismissedViewer) {
        // Restoring the workspace drawer can complete after the conversation mounts.
        await moveTo(closeViewer,true);
        await wait(() => !document.querySelector('.dt-viewer-panel[data-open="true"]'), 'The restored activity drawer stayed open', 2000);
        dismissedViewer = true;
      }
      else {
        if (Date.now() >= deadline) {
          const diagnostics = await js((selector, point, viewer) => {
            const describe = node => {
              const style = getComputedStyle(node);
              return {
                tag: node.tagName, role: node.getAttribute('role'), label: node.getAttribute('aria-label'),
                className: node.getAttribute('class'), open: node.getAttribute('data-open'),
                visibility: style.visibility, zIndex: style.zIndex, pointerEvents: style.pointerEvents,
                rect: node.getBoundingClientRect().toJSON(),
              };
            };
            const element = document.querySelector(selector);
            const hits = point ? document.elementsFromPoint(point.x, point.y) : [];
            const ancestors = [];
            for (let node = hits[0]; node && ancestors.length < 8; node = node.parentElement) ancestors.push(describe(node));
            return {
              width: innerWidth, height: innerHeight, scrollX, scrollY,
              target: element && describe(element), point, hitText: hits[0]?.textContent?.trim().slice(0, 120),
              hits: hits.slice(0, 8).map(describe), ancestors,
              viewers: [...document.querySelectorAll(viewer)].map(describe),
            };
          }, selector, lastSample, '.dt-viewer-panel,[role="dialog"]');
          writeFileSync(join(evidence,'quick-preview-failure.json'),JSON.stringify({selector,...diagnostics},null,2));
          writeFileSync(join(evidence,'quick-preview-failure.png'),(await view.capturePage()).toPNG());
          assert.fail(`Preview action unavailable: ${selector}, hit ${diagnostics.hitText || lastSample?.hit}`);
        }
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
    async function openConversation() {
      await view.loadURL(`${origin}/chat/${encodeURIComponent(seed.session)}?dt_workspace=`);
      await wait(() => document.querySelectorAll('[data-chat-turn-navigator] [data-tick]').length === 8, 'Eight question marks did not render');
      await pause(500);
      if (await js(selector => Boolean(document.querySelector(selector)), viewer)) {
        await moveTo(closeViewer,true);
        await wait(() => !document.querySelector('.dt-viewer-panel[data-open="true"]'), 'The existing activity drawer stayed open');
      }
      await wait(() => {
        const rail = document.querySelector('[data-chat-turn-navigator]');
        return rail && getComputedStyle(rail).visibility === 'visible';
      }, 'Question navigator did not become visible', 6000);
      assert.equal(await js(() => document.documentElement.scrollWidth>innerWidth),false);
    }
    const reachedFirstQuestion = () => {
      const root = document.querySelector('[data-chat-scroll-root]');
      const first = document.querySelector('[data-tick]');
      const target = first && root?.querySelector(`[data-turn-key="${first.dataset.tick}"]`);
      return !!target && Math.abs(target.getBoundingClientRect().top-root.getBoundingClientRect().top)<160;
    };
    for (const [width,height] of [[390,844],[844,390],[1366,900],[1920,1080]]) {
      await debug.sendCommand('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
      await openConversation();
      assert.deepEqual(await js(() => [innerWidth,innerHeight]),[width,height]);
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
      await moveTo(preview+' button',true);
      await wait(reachedFirstQuestion, 'Clicking the preview did not reach the original question',3000);
      await wait(() => !document.querySelector('[data-turn-preview]'), 'The preview did not close after clicking the card',3000);

      // Test the rail click independently from the preview click's scroll and flash.
      await openConversation();
      await moveTo(mark,true);
      const jumpStarted=Date.now();
      await wait(reachedFirstQuestion,'Click did not reach original question',3000);
      const jumpMilliseconds=Date.now()-jumpStarted;
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
