const assert = require('node:assert/strict');
const { writeFileSync } = require('node:fs');
const { join } = require('node:path');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let runSequence = 0;

const normalize = text => String(text).normalize('NFKC').replace(/\s+/g, '');
function bodyMarkers(text) {
  const lines = String(text).replace(/\[图片:[^\]]+\]/g, '').split(/\n+/).map(normalize).filter(line => /[\p{L}\p{N}]/u.test(line));
  const meaningful = lines.filter(line => line.length >= 12);
  const selected = meaningful.length ? meaningful : lines;
  assert(selected.length, 'The source fixture has no complete text to verify');
  return [selected[0], selected.at(-1)];
}
const sameGeometry = (a, b) => !!a && !!b && ['left', 'top', 'width', 'height'].every(key => Math.abs(a[key] - b[key]) < 1);
const nativeWheelDelta = (platform, arch) => platform === 'darwin' && arch === 'x64' ? 160 : null;
const wheelFeedback = (before, after, event) => !!event?.trusted && event.deltaY < 0 && (before <= 0 || after < before - 1);
const imagesReady = (images, expected) => images.length === expected && images.every(image => image.complete && image.width > 0 && image.height > 0);

// Runs in the renderer. Selecting a visible candidate does not activate it.
function inspectTarget(spec, token, scroll = false) {
  const rect = node => { const r = node.getBoundingClientRect(); return { left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:r.width, height:r.height }; };
  const candidates = spec.href ? [...document.querySelectorAll('a[href]')].filter(node => node.getAttribute('href') === spec.href)
    : spec.text ? [...document.querySelectorAll('button')].filter(node => node.textContent.trim() === spec.text)
      : [...document.querySelectorAll(spec.selector)];
  const visible = node => { const style = getComputedStyle(node); return [...node.getClientRects()].some(r => r.width > 0 && r.height > 0) && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && !node.disabled && node.getAttribute('aria-disabled') !== 'true'; };
  const node = candidates.find(visible);
  const all = candidates.map((candidate,index) => ({ index, text:candidate.innerText, rect:rect(candidate), display:getComputedStyle(candidate).display, visibility:getComputedStyle(candidate).visibility }));
  if (!node) return { found:false, candidates:all };
  node.setAttribute('data-k12-click-id', token);
  if (scroll) node.scrollIntoView({ block:'center', inline:'nearest', behavior:'instant' });
  const bounds = rect(node), point = { x:Math.round(bounds.left + bounds.width / 2), y:Math.round(bounds.top + bounds.height / 2) };
  const hit = document.elementFromPoint(point.x, point.y);
  let root;
  for (let parent=node.parentElement; parent && parent !== document.documentElement; parent=parent.parentElement) {
    if (/auto|scroll/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight + 1) { root=parent; break; }
  }
  if (root) root.setAttribute('data-k12-scroll-id', token);
  return { found:true, rect:bounds, point, candidates:all, selectedIndex:candidates.indexOf(node), color:getComputedStyle(node).color,
    clickable:point.x >= 0 && point.y >= 0 && point.x < innerWidth && point.y < innerHeight && !!hit && node.contains(hit) && (!spec.href || hit.closest('a[href]')?.getAttribute('href') === spec.href),
    hit:hit ? { tag:hit.tagName, text:hit.innerText?.slice(0,120), href:hit.closest('a[href]')?.getAttribute('href') } : null,
    root:root ? { rect:rect(root), scrollTop:root.scrollTop, scrollHeight:root.scrollHeight, clientHeight:root.clientHeight, className:root.className } : null };
}

module.exports = async function verifyK12Library(view, evidence, seed, options = {}) {
  const requestedEntry = options.entry ?? 'current';
  assert(['current','oldest','update-entry','oldest-update-entry'].includes(requestedEntry));
  const entry = requestedEntry.includes('oldest') ? 'oldest' : 'current';
  const run = `${Date.now()}-${process.pid}-${++runSequence}`;
  const js = (fn, ...args) => view.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`, true);
  const frames = () => js(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const origin = new URL(view.getURL()).origin;
  assert(['127.0.0.1','localhost','[::1]'].includes(new URL(origin).hostname));
  assert.equal(seed.model_calls, 0);
  assert(Number.isInteger(seed.images) && seed.images >= 0);
  const markers = bodyMarkers(seed.question);
  const debug = view.debugger, views = [], network = [], requestURLs = new Map();
  assert(!debug.isAttached());
  let width = 0, height = 0, phase = 'starting', lastAction, actionSequence = 0;
  const file = (kind, extension) => join(evidence, `k12-${entry}-${width}x${height}-${run}-${kind}.${extension}`);
  const save = (name, value) => writeFileSync(name, typeof value === 'string' ? value : JSON.stringify(value,null,2) + '\n', { flag:'wx' });
  async function wait(fn, args, label, timeout = 60000) {
    const until = Date.now() + timeout;
    while (!await js(fn, ...args)) { assert(Date.now() < until, label); await pause(100); }
  }
  async function monitor() {
    await js(() => {
      if (window.__k12Driver) return;
      window.__k12Driver = { events:[], sequence:0 };
      for (const type of ['click','wheel','load','error']) window.addEventListener(type, event => {
        if ((type === 'load' || type === 'error') && !(event.target instanceof HTMLImageElement)) return;
        const target = event.target;
        window.__k12Driver.events.push({ sequence:++window.__k12Driver.sequence, type, trusted:event.isTrusted, at:performance.now(), deltaY:event.deltaY,
          tag:target?.tagName, text:target?.innerText?.slice(0,120), href:target?.closest?.('a[href]')?.getAttribute('href'),
          action:target?.closest?.('[data-k12-click-id]')?.getAttribute('data-k12-click-id'),
          root:target?.closest?.('[data-k12-scroll-id]')?.getAttribute('data-k12-scroll-id'),
          src:target instanceof HTMLImageElement ? target.currentSrc || target.src : undefined });
        if (window.__k12Driver.events.length > 300) window.__k12Driver.events.shift();
      }, true);
    });
  }
  async function click(spec) {
    if (typeof spec === 'string') spec = { selector:spec };
    await monitor();
    const token = `k12-${++actionSequence}`;
    lastAction = { spec, token, samples:[], wheels:[] };
    await js(inspectTarget, spec, token, true);
    await frames();
    const until = Date.now() + 60000;
    let previous, stable = 0, wheelCount = 0, current;
    while (Date.now() < until) {
      current = await js(inspectTarget, spec, token);
      lastAction.samples.push(current);
      if (lastAction.samples.length > 24) lastAction.samples.splice(4,1);
      stable = current.found && sameGeometry(previous?.rect,current.rect) ? stable + 1 : 1;
      if (stable >= 3 && current.clickable) break;
      // A trusted upward wheel cancels chat's auto-pin. Other native directions remain unverified.
      if (stable >= 3 && current.found && !current.clickable && current.root && spec.history && wheelCount < 2) {
        const delta = nativeWheelDelta(process.platform,process.arch);
        if (delta === null) lastAction.unverifiedWheelPlatform = `${process.platform}/${process.arch}`;
        else {
          const root = current.root, point = { x:Math.round((root.rect.left + root.rect.right) / 2), y:Math.round((root.rect.top + root.rect.bottom) / 2) };
          const contained = await js((token,p) => { const root=document.querySelector(`[data-k12-scroll-id="${token}"]`), hit=document.elementFromPoint(p.x,p.y); return !!root && !!hit && root.contains(hit); },token,point);
          if (contained) {
            wheelCount++;
            const beforeEvents = await js(() => window.__k12Driver.sequence);
            view.sendInputEvent({ type:'mouseMove', ...point });
            view.sendInputEvent({ type:'mouseWheel', ...point, deltaX:0, deltaY:delta, canScroll:true });
            const feedbackEnd = Date.now() + 5000;
            let feedback;
            do {
              feedback = await js(token => { const root=document.querySelector(`[data-k12-scroll-id="${token}"]`); return { top:root?.scrollTop, events:window.__k12Driver.events }; },token);
              const event = feedback.events.find(event => event.sequence > beforeEvents && event.type === 'wheel' && event.root === token);
              if (wheelFeedback(root.scrollTop,feedback.top,event)) { feedback.event=event; break; }
              await pause(50);
            } while (Date.now() < feedbackEnd);
            lastAction.wheels.push({ point, nativeDeltaY:delta, beforeTop:root.scrollTop, feedback });
            assert(wheelFeedback(root.scrollTop,feedback?.top,feedback?.event),'Trusted upward wheel/real scroll feedback missing');
            await frames();
            await js(inspectTarget,spec,token,true);
            await frames();
            previous = null; stable = 0;
            continue;
          }
        }
      }
      previous = current;
      await pause(50);
    }
    assert(stable >= 3 && current?.clickable, `No stable visible click target: ${JSON.stringify({spec,current,unverifiedWheelPlatform:lastAction.unverifiedWheelPlatform})}`);
    if (spec.blue) {
      const colors=current.color.match(/[\d.]+/g).map(Number);
      assert(colors[2]>colors[0]&&colors[2]>=colors[1],'Actual source is not visibly blue: '+current.color);
    }
    lastAction.dispatched = current;
    view.sendInputEvent({ type:'mouseDown', button:'left', clickCount:1, ...current.point });
    view.sendInputEvent({ type:'mouseUp', button:'left', clickCount:1, ...current.point });
    await wait(token => window.__k12Driver.events.some(event => event.type === 'click' && event.trusted && event.action === token),[token],'The native mouse did not hit its chosen target');
  }
  const networkListener = (_event, method, params) => {
    if (method === 'Network.requestWillBeSent' && params.request.url.includes('/api/student/question-bank/')) {
      requestURLs.set(params.requestId,params.request.url);
      network.push({ entry,width,height,phase,type:'request',id:params.requestId,url:params.request.url,at:params.timestamp });
    } else if (method === 'Network.responseReceived' && params.response.url.includes('/api/student/question-bank/')) network.push({ entry,width,height,phase,type:'response',id:params.requestId,url:params.response.url,status:params.response.status,fromDiskCache:params.response.fromDiskCache,at:params.timestamp });
    else if (method === 'Network.loadingFailed' && requestURLs.has(params.requestId)) network.push({ entry,width,height,phase,type:'failed',id:params.requestId,url:requestURLs.get(params.requestId),error:params.errorText,at:params.timestamp });
  };
  async function failure(error) {
    const record = { entry,requestedEntry,width,height,phase,error:String(error.stack ?? error),action:lastAction,network };
    try { record.dom = await js(href => {
      const rect = node => { const r=node.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}; };
      const anchors = [...document.querySelectorAll('a[href]')].filter(node => node.getAttribute('href') === href).map((node,index) => {
        const r=rect(node),point={x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)},hit=document.elementFromPoint(point.x,point.y),roots=[];
        for(let parent=node.parentElement;parent;parent=parent.parentElement)if(/auto|scroll/.test(getComputedStyle(parent).overflowY))roots.push({tag:parent.tagName,className:parent.className,rect:rect(parent),scrollTop:parent.scrollTop,scrollHeight:parent.scrollHeight,clientHeight:parent.clientHeight});
        return {index,text:node.innerText,rect:r,clientRects:[...node.getClientRects()].map(r=>({left:r.left,top:r.top,width:r.width,height:r.height})),display:getComputedStyle(node).display,visibility:getComputedStyle(node).visibility,point,hit:hit?{tag:hit.tagName,href:hit.closest('a[href]')?.getAttribute('href')}:null,roots};
      });
      const preview=document.querySelector('[data-testid="question-source-preview"]');
      return {viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},anchors,events:window.__k12Driver?.events,
        statuses:[...document.querySelectorAll('[role="status"]')].map(node=>node.innerText),dialogText:document.querySelector('[role="dialog"]')?.innerText,
        preview:preview?{id:preview.dataset.questionId,revision:preview.dataset.bankRevision,ready:preview.dataset.sourceReady,text:preview.innerText,images:[...preview.querySelectorAll('img')].map(image=>({src:image.src,currentSrc:image.currentSrc,complete:image.complete,width:image.naturalWidth,height:image.naturalHeight,rect:rect(image)}))}:null};
    },seed.href); } catch (captureError) { record.captureError=String(captureError); }
    save(file('failure','json'),record);
    try { save(file('failure','html'),await js(()=>document.documentElement.outerHTML)); } catch {}
    try { writeFileSync(file('failure','png'),(await view.capturePage()).toPNG(),{flag:'wx'}); } catch {}
  }
  debug.attach('1.3');
  debug.on('message',networkListener);
  try {
    await debug.sendCommand('Network.enable');
    for ([width,height] of [[390,844],[844,390],[1366,900],[1920,1080]]) {
      await debug.sendCommand('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
      phase='library-navigation';
      await view.loadURL(`${origin}/space?dt_workspace=`);
      await wait(()=>[...document.querySelectorAll('button')].some(node=>node.textContent.trim()==='题库'),[],'Two library entries did not render');
      const shelf = await js(()=>{const buttons=[...document.querySelectorAll('button')],main=buttons.filter(node=>['教材库','题库'].includes(node.textContent.trim()));return {count:main.length,selected:main.filter(node=>node.getAttribute('aria-pressed')==='true').length,uploadSeparate:buttons.some(node=>node.getAttribute('aria-expanded')!==null&&/我的上传资料/.test(node.textContent)),overflow:document.documentElement.scrollWidth>innerWidth+1};});
      assert.deepEqual(shelf,{count:2,selected:1,uploadSeparate:true,overflow:false});
      await click({text:'题库'});
      await wait(()=>!!document.querySelector('[aria-label="按学科筛选题库"] button[aria-pressed="true"]')&&!!document.querySelector('button[aria-label^="查看题源："]'),[],'Real question-pack catalog did not render');
      await click('button[aria-label^="查看题源："]');
      await wait(()=>!!document.querySelector('section[aria-label="题库"] a[href^="#dt-question-"]'),[],'Source did not list complete original-material links');
      await click('section[aria-label="题库"] a[href^="#dt-question-"]');
      await wait(()=>{const body=document.querySelector('[data-testid="question-source-preview"]');return body?.dataset.sourceReady==='true'&&body.innerText.trim().length>20&&[...body.querySelectorAll('img')].every(image=>image.complete&&image.naturalWidth>0);},[],'Library question did not finish original images');
      await click('button[aria-label="关闭题源"]');
      await wait(()=>!document.querySelector('[role="dialog"]'),[],'Source did not close');
      writeFileSync(file('library','png'),(await view.capturePage()).toPNG(),{flag:'wx'});
      phase='history-source';
      await view.loadURL(`${origin}/chat/${encodeURIComponent(seed.session)}?dt_workspace=`);
      await wait(href=>[...document.querySelectorAll('a[href]')].some(node=>node.getAttribute('href')===href),[seed.href],'Persisted answer did not restore its actual-source link');
      await frames();
      await click({href:seed.href,history:true,blue:true});
      await wait((id,revision,expected,markers)=>{
        const body=document.querySelector('[data-testid="question-source-preview"]');
        if(!body||body.dataset.questionId!==id||body.dataset.bankRevision!==revision||body.dataset.sourceReady!=='true')return false;
        const images=[...body.querySelectorAll('img')],text=body.innerText.normalize('NFKC').replace(/\s+/g,'');
        return images.length===expected&&images.every(image=>image.complete&&image.naturalWidth>0&&image.naturalHeight>0)&&markers.every(marker=>text.includes(marker));
      },[seed.qualified_id,seed.bank_revision,seed.images,markers],'History citation opened the wrong question/revision or lost original body/images');
      await frames();
      const dialog=await js(()=>{const node=document.querySelector('[role="dialog"]'),r=node.getBoundingClientRect(),body=document.querySelector('[data-testid="question-source-preview"]');return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,text:body.innerText,images:[...body.querySelectorAll('img')].map(image=>({complete:image.complete,width:image.naturalWidth,height:image.naturalHeight})),overflow:document.documentElement.scrollWidth>innerWidth+1};});
      assert(dialog.text.trim().length>20&&imagesReady(dialog.images,seed.images));
      assert(markers.every(marker=>normalize(dialog.text).includes(marker)),'Original question start/end is missing');
      assert(dialog.left>=-1&&dialog.right<=width+1&&dialog.top>=-1&&dialog.bottom<=height+1&&!dialog.overflow,'Original source escapes the viewport');
      writeFileSync(file('source','png'),(await view.capturePage()).toPNG(),{flag:'wx'});
      await click('button[aria-label="关闭题源"]');
      await wait(()=>!document.querySelector('[role="dialog"]'),[],'History source did not close');
      views.push({width,height,twoLibraryEntries:true,separateUploads:true,sourceCardOpened:true,restoredCitationBlue:true,exactQuestionAndRevision:true,allOriginalImagesLoaded:true,originalBodyStartEnd:true,dialogWithinViewport:true,closeReturned:true});
    }
    const result={passed:true,actualNativeRenderer:true,bank_revision:seed.bank_revision,views,model_calls:0,formal_data_used:false,diagnostic_entry:entry,evidence_run:run};
    save(join(evidence,`k12-library-${entry}-${run}.json`),result);
    // Legacy success summary; immutable entry/run JSON and PNGs retain both runs.
    writeFileSync(join(evidence,'k12-library.json'),JSON.stringify(result,null,2)+'\n');
    return result;
  } catch (error) { await failure(error); throw error; }
  finally {
    debug.removeListener('message',networkListener);
    try { await debug.sendCommand('Emulation.clearDeviceMetricsOverride'); } catch {}
    if(debug.isAttached())debug.detach();
  }
};
module.exports._test = { normalize, bodyMarkers, sameGeometry, nativeWheelDelta, wheelFeedback, imagesReady, inspectTarget };
