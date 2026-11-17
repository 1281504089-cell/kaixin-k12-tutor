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
    writeFileSync(output,JSON.stringify({passed:true,active_runtime_id:active.runtimeId,k12_library:k12,model_calls:0,formal_data_used:false},null,2)+'\n');
    clearTimeout(timer);
    app.quit();
  }catch(error){
    console.error(error.stack||error);
    try{writeFileSync(output+'.error.json',JSON.stringify({passed:false,error:String(error.stack||error)},null,2)+'\n');}catch{}
    clearTimeout(timer);app.exit(1);
  }
})();
