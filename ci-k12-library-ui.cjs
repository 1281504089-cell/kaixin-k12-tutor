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
const calibratedWheelDelta = (delta, event) => !event?.trusted || !Number.isFinite(event.deltaY) || event.deltaY === 0 ? null : event.deltaY < 0 ? delta : -delta;
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
  const bounds = rect(node), clip = { left:0, top:0, right:innerWidth, bottom:innerHeight };
  let root;
  for (let parent=node.parentElement; parent && parent !== document.documentElement; parent=parent.parentElement) {
    const style=getComputedStyle(parent), box=rect(parent);
    const left=box.left+(parent.clientLeft||0), top=box.top+(parent.clientTop||0);
    const right=left+(typeof parent.clientWidth==='number'?parent.clientWidth:box.width), bottom=top+(typeof parent.clientHeight==='number'?parent.clientHeight:box.height);
    if (/auto|scroll|hidden|clip/.test(style.overflowX)) { clip.left=Math.max(clip.left,left); clip.right=Math.min(clip.right,right); }
    if (/auto|scroll|hidden|clip/.test(style.overflowY)) { clip.top=Math.max(clip.top,top); clip.bottom=Math.min(clip.bottom,bottom); }
    if (!root && /auto|scroll/.test(style.overflowY) && parent.scrollHeight > parent.clientHeight + 1) root=parent;
  }
  const exposed=[...node.getClientRects()].map(box=>({left:Math.max(box.left,clip.left),top:Math.max(box.top,clip.top),right:Math.min(box.right,clip.right),bottom:Math.min(box.bottom,clip.bottom)}))
    .filter(box=>box.right>box.left&&box.bottom>box.top).sort((a,b)=>(b.right-b.left)*(b.bottom-b.top)-(a.right-a.left)*(a.bottom-a.top));
  const choices=exposed.map(box=>{const point={x:Math.floor((box.left+box.right)/2),y:Math.floor((box.top+box.bottom)/2)};return {point,box,hit:document.elementFromPoint(point.x,point.y)};});
  const actionable=choice=>choice.point.x>=choice.box.left&&choice.point.x<choice.box.right&&choice.point.y>=choice.box.top&&choice.point.y<choice.box.bottom&&!!choice.hit&&node.contains(choice.hit)&&(!spec.href||choice.hit.closest('a[href]')?.getAttribute('href')===spec.href);
  const chosen=choices.find(actionable), fallback=choices[0], point=chosen?.point||fallback?.point||{x:Math.round(bounds.left+bounds.width/2),y:Math.round(bounds.top+bounds.height/2)};
  const hit=chosen?.hit||fallback?.hit||document.elementFromPoint(point.x,point.y);
  if (root) root.setAttribute('data-k12-scroll-id', token);
  return { found:true, rect:bounds, point, clippedRect:chosen?.box||fallback?.box||null,clip,candidates:all, selectedIndex:candidates.indexOf(node), color:getComputedStyle(node).color,
    clickable:!!chosen,
    hit:hit ? { tag:hit.tagName, text:hit.innerText?.slice(0,120), href:hit.closest('a[href]')?.getAttribute('href') } : null,
    root:root ? { rect:rect(root), scrollTop:root.scrollTop, scrollHeight:root.scrollHeight, clientHeight:root.clientHeight, className:root.className } : null };
}

function inspectPreparedPicture() {
  const image=document.querySelector('[aria-label="题库原题图"] img'),root=image?.closest('[data-chat-scroll-root]');
  const rect=node=>{const r=node.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
  return {viewport:{width:innerWidth,height:innerHeight},image:image?{src:image.src,currentSrc:image.currentSrc,complete:image.complete,naturalWidth:image.naturalWidth,naturalHeight:image.naturalHeight,loading:image.loading,decoding:image.decoding,rect:rect(image)}:null,
    root:root?{rect:rect(root),scrollTop:root.scrollTop,scrollHeight:root.scrollHeight,clientHeight:root.clientHeight}:null};
}

module.exports = async function verifyK12Library(view, evidence, seed, options = {}) {
  const requestedEntry = options.entry ?? 'current';
  assert(['current','oldest','update-entry','oldest-update-entry','materials-update-entry','materials-oldest-update-entry','fresh'].includes(requestedEntry));
  const entry = requestedEntry.includes('oldest') ? 'oldest' : requestedEntry === 'fresh' ? 'fresh' : 'current';
  const run = `${Date.now()}-${process.pid}-${++runSequence}`;
  const js = (fn, ...args) => view.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`, true);
  const frames = () => js(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const origin = new URL(view.getURL()).origin;
  assert(['127.0.0.1','localhost','[::1]'].includes(new URL(origin).hostname));
  assert.equal(seed.model_calls, 0);
  assert(Number.isInteger(seed.images) && seed.images >= 0);
  const pictured = seed.picture_fixture;
  assert(pictured?.session && pictured.bank_revision === seed.bank_revision && pictured.picture?.sha256 && pictured.images > 0, 'A prepared-image history fixture is required');
  const preparedURL = new URL(pictured.picture.url,origin);
  preparedURL.searchParams.set('dt_workspace','');
  const preparedHref = preparedURL.href;
  const markers = bodyMarkers(seed.question);
  const debug = view.debugger, views = [], network = [], requestURLs = new Map();
  assert(!debug.isAttached());
  let width = 0, height = 0, phase = 'starting', lastAction, actionSequence = 0, pictureDiagnostic;
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
  async function click(spec, { activate = true } = {}) {
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
      const releaseBeforeReveal = spec.history && !activate && wheelCount === 0 && current.root;
      if (stable >= 3 && current.clickable && !releaseBeforeReveal) break;
      // A trusted upward wheel cancels chat's auto-pin. Other native directions remain unverified.
      if (stable >= 3 && current.found && (!current.clickable || releaseBeforeReveal) && current.root && spec.history && wheelCount < 2) {
        // Unknown native signs are calibrated against the real trusted DOM wheel.
        let delta = nativeWheelDelta(process.platform,process.arch) ?? 160;
        {
          const root = current.root, point = { x:Math.round((root.rect.left + root.rect.right) / 2), y:Math.round((root.rect.top + root.rect.bottom) / 2) };
          const contained = await js((token,p) => { const root=document.querySelector(`[data-k12-scroll-id="${token}"]`), hit=document.elementFromPoint(p.x,p.y); return !!root && !!hit && root.contains(hit); },token,point);
          if (contained) {
            wheelCount++;
            let feedback;
            for(let calibration=0;calibration<2;calibration++) {
              const before=await js(token=>({top:document.querySelector(`[data-k12-scroll-id="${token}"]`)?.scrollTop,sequence:window.__k12Driver.sequence}),token);
              view.sendInputEvent({ type:'mouseMove', ...point });
              view.sendInputEvent({ type:'mouseWheel', ...point, deltaX:0, deltaY:delta, canScroll:true });
              const feedbackEnd=Date.now()+5000;
              do {
                feedback=await js(token=>({top:document.querySelector(`[data-k12-scroll-id="${token}"]`)?.scrollTop,events:window.__k12Driver.events}),token);
                feedback.event=feedback.events.find(event=>event.sequence>before.sequence&&event.type==='wheel'&&event.root===token);
                const next=calibratedWheelDelta(delta,feedback.event);
                if(wheelFeedback(before.top,feedback.top,feedback.event)||next!==null&&next!==delta)break;
                await pause(50);
              } while(Date.now()<feedbackEnd);
              lastAction.wheels.push({point,nativeDeltaY:delta,beforeTop:before.top,feedback});
              if(wheelFeedback(before.top,feedback?.top,feedback?.event))break;
              const next=calibratedWheelDelta(delta,feedback?.event);
              assert(calibration===0&&next!==null&&next!==delta,'Trusted upward wheel/real scroll feedback missing');
              delta=next;
            }
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
    if (!activate) { lastAction.revealed=current; return current; }
    lastAction.dispatched = current;
    view.sendInputEvent({ type:'mouseDown', button:'left', clickCount:1, ...current.point });
    view.sendInputEvent({ type:'mouseUp', button:'left', clickCount:1, ...current.point });
    await wait(token => window.__k12Driver.events.some(event => event.type === 'click' && event.trusted && event.action === token),[token],'The native mouse did not hit its chosen target');
  }
  async function preparedPictureHistory() {
    phase='prepared-picture-history-delayed';
    const paused=[];
    pictureDiagnostic={paused};
    const listener=(_event,method,params)=>{
      if(method==='Fetch.requestPaused') paused.push({id:params.requestId,url:params.request.url,at:Date.now()});
    };
    debug.on('message',listener);
    let navigation, before, heldMs;
    try {
      await debug.sendCommand('Network.setCacheDisabled',{cacheDisabled:true});
      await debug.sendCommand('Fetch.enable',{patterns:[{urlPattern:'*question-bank/pictures/*',requestStage:'Request'}]});
      navigation=view.loadURL(`${origin}/chat/${encodeURIComponent(pictured.session)}?dt_workspace=`);
      navigation.catch(()=>{});
      await wait(marker=>document.body.innerText.includes(marker)&&!!document.querySelector('[aria-label="题库原题图"] img'),[pictured.answer_marker],'Saved image source/assistant body did not restore before image bytes');
      pictureDiagnostic.beforeReveal=await js(inspectPreparedPicture);
      await click({selector:'[aria-label="题库原题图"] a',history:true},{activate:false});
      pictureDiagnostic.afterReveal=await js(inspectPreparedPicture);
      const heldUntil=Date.now()+30000;
      while(!paused.length){assert(Date.now()<heldUntil,'Native renderer did not request the prepared image');await pause(50);}
      await pause(1000);
      before=await js((marker,url)=>{
        const image=[...document.querySelectorAll('[aria-label="题库原题图"] img')].find(node=>new URL(node.currentSrc||node.src,location.origin).pathname===new URL(url,location.origin).pathname);
        const caption=document.querySelector('[aria-label="题库原题图"] a span');
        return {bodyRendered:document.body.innerText.includes(marker),imageRequested:!!image,imageComplete:image?.complete,naturalWidth:image?.naturalWidth,decoding:image?.decoding,captionColor:caption?getComputedStyle(caption).color:null,overflow:document.documentElement.scrollWidth>innerWidth+1};
      },pictured.answer_marker,preparedHref);
      assert(before.bodyRendered&&before.imageRequested&&!before.imageComplete&&before.naturalWidth===0&&before.decoding==='async'&&!before.overflow,'Image response is blocking the saved assistant body or the wrong image was held');
      const colors=before.captionColor.match(/[\d.]+/g).map(Number);
      assert(colors[2]>colors[0]&&colors[2]>=colors[1],'Prepared image source caption is not blue');
      assert(paused.every(item=>new URL(item.url).origin===origin&&new URL(item.url).pathname===new URL(pictured.picture.url,origin).pathname&&new URL(item.url).searchParams.get('revision')===pictured.bank_revision),'Wrong prepared image/revision was requested');
      heldMs=Date.now()-paused[0].at;
      for(const item of paused) await debug.sendCommand('Fetch.continueRequest',{requestId:item.id});
    } finally {
      try { await debug.sendCommand('Fetch.disable'); } finally {
        debug.removeListener('message',listener);
        await debug.sendCommand('Network.setCacheDisabled',{cacheDisabled:false});
      }
    }
    await navigation;
    await wait((url,w,h)=>[...document.querySelectorAll('[aria-label="题库原题图"] img')].some(image=>image.src===new URL(url,location.origin).href&&image.complete&&image.naturalWidth===w&&image.naturalHeight===h),[preparedHref,pictured.picture.width,pictured.picture.height],'Prepared image failed native decode or changed dimensions');
    const reply=network.findLast(item=>item.type==='response'&&item.status===200&&item.url===preparedHref);
    assert(reply,'The prepared image has no successful native HTTP response');
    const responseBody=await debug.sendCommand('Network.getResponseBody',{requestId:reply.id});
    const raw=Buffer.from(responseBody.body,responseBody.base64Encoded?'base64':'utf8');
    assert.equal(raw.length,pictured.picture.bytes);
    assert.equal(require('node:crypto').createHash('sha256').update(raw).digest('hex'),pictured.picture.sha256,'Native image response changed from the frozen display');
    await click({selector:'[aria-label="题库原题图"] a'});
    await wait((id,revision,w,h)=>{
      const body=document.querySelector('[data-testid="question-source-preview"]'),images=body?[...body.querySelectorAll('img')]:[];
      return body?.dataset.questionId===id&&body.dataset.bankRevision===revision&&body.dataset.sourceRenderer==='prepared-picture'&&body.dataset.sourceReady==='true'&&images.length===1&&images[0].complete&&images[0].naturalWidth===w&&images[0].naturalHeight===h;
    },[pictured.qualified_id,pictured.bank_revision,pictured.picture.width,pictured.picture.height],'Prepared card opened wrong source/revision, fallback or incomplete image');
    const modal=await js(()=>{const node=document.querySelector('[role="dialog"]'),r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:document.documentElement.scrollWidth>innerWidth+1};});
    assert(modal.left>=-1&&modal.right<=width+1&&modal.top>=-1&&modal.bottom<=height+1&&!modal.overflow,'Prepared-image dialog escapes viewport');
    writeFileSync(file('prepared-source','png'),(await view.capturePage()).toPNG(),{flag:'wx'});
    await click('button[aria-label="关闭题源"]');
    await wait(()=>!document.querySelector('[role="dialog"]'),[],'Prepared image preview did not close');
    // Reload the persisted history again: a live event alone is insufficient.
    await view.loadURL(`${origin}/chat/${encodeURIComponent(pictured.session)}?dt_workspace=`);
    await wait((marker,url)=>document.body.innerText.includes(marker)&&[...document.querySelectorAll('[aria-label="题库原题图"] img')].some(image=>image.src===new URL(url,location.origin).href),[pictured.answer_marker,preparedHref],'Prepared image did not survive a second history load');
    return {qualified_id:pictured.qualified_id,bank_revision:pictured.bank_revision,sha256:pictured.picture.sha256,width:pictured.picture.width,height:pictured.picture.height,body_dom_before_image_response:true,held_response_ms:heldMs,async_decode:true,native_http_image_sha_verified:true,source_caption_blue:true,correct_source_opened:true,dialog_within_viewport:true,second_history_restore:true,body_probe:before};
  }
  const networkListener = (_event, method, params) => {
    if (method === 'Network.requestWillBeSent' && params.request.url.includes('/api/student/question-bank/')) {
      requestURLs.set(params.requestId,params.request.url);
      network.push({ entry,width,height,phase,type:'request',id:params.requestId,url:params.request.url,at:params.timestamp });
    } else if (method === 'Network.responseReceived' && params.response.url.includes('/api/student/question-bank/')) network.push({ entry,width,height,phase,type:'response',id:params.requestId,url:params.response.url,status:params.response.status,fromDiskCache:params.response.fromDiskCache,at:params.timestamp });
    else if (method === 'Network.loadingFailed' && requestURLs.has(params.requestId)) network.push({ entry,width,height,phase,type:'failed',id:params.requestId,url:requestURLs.get(params.requestId),error:params.errorText,at:params.timestamp });
  };
  async function failure(error) {
    const record = { entry,requestedEntry,width,height,phase,error:String(error.stack ?? error),action:lastAction,network,pictureDiagnostic };
    try { record.preparedPicture=await js(inspectPreparedPicture); } catch(captureError) { record.preparedPictureCaptureError=String(captureError); }
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
      const preparedPicture = await preparedPictureHistory();
      views.push({width,height,twoLibraryEntries:true,separateUploads:true,sourceCardOpened:true,restoredCitationBlue:true,exactQuestionAndRevision:true,allOriginalImagesLoaded:true,originalBodyStartEnd:true,dialogWithinViewport:true,closeReturned:true,preparedPicture});
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
module.exports._test = { normalize, bodyMarkers, sameGeometry, nativeWheelDelta, wheelFeedback, calibratedWheelDelta, imagesReady, inspectTarget, inspectPreparedPicture };
