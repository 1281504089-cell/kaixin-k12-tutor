// QA-only entry; this file is never copied into a distributable installer.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const { readFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const output = process.env.KX_PICTURE_FRESH_OUTPUT;
const timer = setTimeout(() => { console.error('Fresh picture UI timed out'); app.exit(1); }, 660000);
(async()=>{
  try {
    const fixture=JSON.parse(readFileSync(process.env.KX_PICTURE_FIXTURE));
    const active=JSON.parse(readFileSync(path.join(process.env.OPEN_DEEPTUTOR_TEST_HOME,'active.json')));
    await import(pathToFileURL(path.join(__dirname,'../src/main.mjs')));
    await app.whenReady();
    let view;
    const until=Date.now()+120000;
    while(!view){
      for(const window of BrowserWindow.getAllWindows()){
        for(const child of window.contentView.children){
          const candidate=child.webContents;
          if(candidate?.getURL().startsWith('http://127.0.0.1:')&&await candidate.executeJavaScript('Boolean(window.kaixinDesktop?.checkForUpdates)').catch(()=>false)){view=candidate;break;}
        }
      }
      assert(Date.now()<until,'Fresh candidate did not open the trusted native renderer');
      if(!view) await pause(200);
    }
    const k12=await require('./ci-k12-library-ui.cjs')(view,path.dirname(output),fixture,{entry:'fresh'});
    assert(k12.passed&&k12.views.length===4);
    const citation = fixture.desktop_citation_fixture;
    assert(citation?.session && citation.sha256 && citation.href.endsWith('#page=3'));
    const origin = new URL(view.getURL()).origin;
    const chat = new URL('/chat/' + encodeURIComponent(citation.session) + '?dt_workspace=', origin).href;
    const js = (fn, ...args) => view.executeJavaScript('(' + fn.toString() + ')(...' + JSON.stringify(args) + ')', true);
    const wait = async (fn, ...args) => {
      const before = Date.now() + 45000;
      while (Date.now() < before) {
        const found = await js(fn, ...args).catch(() => null);
        if (found) return found;
        await pause(150);
      }
      throw new Error('Citation candidate renderer did not show the expected original');
    };
    await view.loadURL(chat);
    const history = (s) => {
      const message = document.querySelector('[data-chat-message-id="' + s.message + '"]');
      const links = [...(message?.querySelectorAll('a.dt-reading-citation') ?? [])];
      if (!links.length || !document.body.innerText.includes('第二轮已保留。')) return null;
      return { links: links.length, paragraph: links[0].closest('p')?.innerText,
        href: links[0].getAttribute('href'), noFalseOriginal: !message.querySelector('a[href*="quote.md"]'),
        noFooter: !message.querySelector('details'), selectionPreserved: document.body.innerText.includes('选段留在学生消息里。') };
    };
    const first = await wait(history, citation);
    assert.equal(first.links, 1);
    assert(first.paragraph?.includes(citation.paragraph) && first.href === citation.href);
    assert(first.noFalseOriginal && first.noFooter && first.selectionPreserved);
    await js(href => [...document.querySelectorAll('a.dt-reading-citation')].find(a => a.getAttribute('href') === href).focus(), citation.href);
    view.sendInputEvent({type:'keyDown',keyCode:'Enter'});
    view.sendInputEvent({type:'keyUp',keyCode:'Enter'});
    const pdf = await wait((filename, proof) => {
      const viewer = [...document.querySelectorAll('[aria-label]')].find(el => el.getAttribute('aria-label')===filename && el.querySelector('canvas'));
      if (!viewer) return null;
      const canvas = [...viewer.querySelectorAll('canvas')].find(image => image.width > 0 && image.height > 0);
      const locator = viewer.querySelector('input[type=number]');
      return canvas && locator?.value === '3' && viewer.innerText.includes(proof)
        ? { realViewer:true, textLayer:true, initialPage:3 } : null;
    }, citation.filename, citation.page_text);
    const checksum = await js(async href => {
      const response = await fetch(href);
      if (!response.ok) return null;
      const bytes = await response.arrayBuffer();
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('');
    }, citation.href);
    assert.equal(checksum, citation.sha256);
    await view.loadURL(chat);
    assert.deepEqual(await wait(history, citation), first);
    const desktopCitation = { passed:true, history:first, pdf, raw_pdf_sha256:checksum, reopened_history:true };

    writeFileSync(output,JSON.stringify({passed:true,active_runtime_id:active.runtimeId,k12_library:k12,desktop_citation:desktopCitation,model_calls:0,formal_data_used:false},null,2)+'\n');
    clearTimeout(timer);
    app.quit();
  }catch(error){
    console.error(error.stack||error);
    try{writeFileSync(output+'.error.json',JSON.stringify({passed:false,error:String(error.stack||error)},null,2)+'\n');}catch{}
    clearTimeout(timer);app.exit(1);
  }
})();
