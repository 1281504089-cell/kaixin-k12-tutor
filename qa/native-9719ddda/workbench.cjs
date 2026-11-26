const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright-core');
const port = +process.argv[2];
const report = {native:true, entry:'边读边问 → 教材', books:[], errors:[], sceneErrors:[], attempts:[]};
const workbenchOnly=process.env.LIVEBOOK_NATIVE_ONLY==='workbench';
const save = () => fs.writeFileSync(workbenchOnly?'native-workbench.json':'final-context-native-textbook.json',JSON.stringify(report,null,2)+'\n');
const sleep = ms => new Promise(ok=>setTimeout(ok,ms));

async function test(browser) {
  const context=browser.contexts()[0];
  let page;
  for(let i=0;i<400 && !page;i++){
    page=context.pages().find(p=>/^http:\/\/127\.0\.0\.1:\d+\//.test(p.url()));
    if(!page) await sleep(750);
  }
  assert(page,'Native window could not start');
  page.setDefaultTimeout(18000);
  await page.bringToFront();
  page.on('pageerror',error=>report.errors.push(error.message));
  page.on('console',message=>{
    if (message.type()==='error' && /Livebook|WebGL|experiment-scenes|Content Security Policy/i.test(message.text())) {
      report.sceneErrors.push(message.text().slice(0,300));
    }
  });
  page.on('response',response=>{
    if (response.status()>=400 && response.url().includes('/experiment-scenes/')) {
      report.sceneErrors.push(response.status()+' '+new URL(response.url()).pathname);
    }
  });
  const origin=new URL(page.url()).origin;
  await page.waitForLoadState('domcontentloaded');
  if (!workbenchOnly && !new URL(page.url()).pathname.startsWith('/chat')) {
    await page.goto(origin+'/chat?dt_workspace=',{waitUntil:'domcontentloaded'});
  }
  if (!workbenchOnly) {
  const activity=page.locator('button[aria-label="活动"]').first();
  if(await activity.getAttribute('aria-pressed')!=='true') await activity.click();
  const panel=page.locator('.dt-viewer-panel');
  await panel.locator('button[aria-label="新标签页"]').last().click();
  await panel.getByRole('button',{name:'边读边问',exact:true}).click();
  await panel.getByRole('button',{name:'教材',exact:true}).click();
  const reader=panel.getByRole('region',{name:'当前阅读资料'});
  const pageNumber=reader.getByRole('spinbutton');
  const close=page.getByRole('button',{name:'关闭互动实验',exact:true});
  const jump=async n=>{await pageNumber.fill(String(n));await pageNumber.press('Enter');};
  const getBoat=canvas=>{
    const {stage}=window.__lb;
    let boat;
    stage.scene.traverse(node=>{
      if(node.userData.pick && node.geometry?.type==='CircleGeometry' && node.geometry.parameters.radius===.011) boat=node;
    });
    if(!boat) throw new Error('Boat pick mesh unavailable');
    const world=boat.getWorldPosition(boat.position.clone());
    const p=world.clone().project(stage.camera);
    return {world:world.toArray(),x:(p.x+1)/2*canvas.clientWidth,y:(1-p.y)/2*canvas.clientHeight,fov:stage.camera.fov};
  };
  for(const spec of [
    {title:'物理 8年级上册',page:33,printed:26,entry:'pep-wuli-8s-avgspeed',lesson:'avgspeed',updated:true},
    {title:'化学 9年级上册',page:59,printed:52,entry:'pep-huaxue-9s-oxygenprep',lesson:'oxygenprep',updated:true},
    {title:'数学 7年级下册',page:131,printed:125,entry:'pep-shuxue-7x-budengshi',lesson:'budengshi'},
    {title:'数学 9年级上册',page:134,printed:127,entry:'pep-shuxue-9s-inscribed',lesson:'inscribed'}
  ]) {
    await panel.getByRole('textbox',{name:'搜索阅读资料'}).fill(spec.title);
    await panel.getByRole('button',{name:spec.title,exact:true}).click();
    await reader.waitFor();
    await jump(spec.page-1);
    const prior=reader.locator('[data-reader-unit="'+(spec.page-1)+'"]');
    await prior.locator('canvas').waitFor();
    assert.equal(await prior.locator('[data-experiment-hotspot="'+spec.entry+'"]').count(),0);
    const opened=[];
    for(const [width,height] of spec.updated ? [[1280,760]] : [[820,960],[1280,760],[1440,900]]) {
      await page.setViewportSize({width,height});
      await jump(spec.page);
      const spot=reader.locator('[data-reader-unit="'+spec.page+'"] [data-experiment-hotspot="'+spec.entry+'"]');
      await spot.locator('img').waitFor({state:'visible'});
      await spot.locator('img').evaluate(img=>img.decode());
      const started=Date.now();
      await spot.click();
      const iframe=page.locator('dialog iframe[src*="entry='+spec.entry+'"]');
      const frame=iframe.contentFrame();
      const canvas=frame.locator('#c');
      const attempt={lesson:spec.lesson,width,height};
      report.attempts.push(attempt);
      try {
        await iframe.waitFor({state:'attached',timeout:15000});
        attempt.src=await iframe.getAttribute('src');
        await frame.locator('body[data-scene-ready="'+spec.lesson+'"], #scene-status[data-error]').first()
          .waitFor({state:'attached',timeout:65000});
        assert.equal(await frame.locator('body').getAttribute('data-scene-ready'),spec.lesson);
      } catch (error) {
        attempt.status=await frame.locator('#scene-status').textContent({timeout:1000}).catch(()=>null);
        attempt.frames=page.frames().map(current=>current.url().split('?')[0]);
        await page.screenshot({path:'native-reader-diagnostic.png',timeout:9000}).catch(()=>{});
        throw error;
      }
      const drawn=await canvas.evaluate(c=>new Promise((resolve,reject)=>{
        const {stage}=window.__lb;
        const t=performance.now();
        function check() {
          const gl=stage.renderer.getContext();
          if (!gl.isContextLost()&&stage.renderer.info.render.calls>0) resolve({calls:stage.renderer.info.render.calls,width:c.width,height:c.height});
          else if(performance.now()-t>12000) reject(new Error('The textbook scene did not draw'));
          else requestAnimationFrame(check);
        }
        check();
      }));
      const result={width,height,clickToDrawMs:Date.now()-started,drawn};
      if (spec.lesson==='avgspeed') {
        const state=frame.locator('body');
        await canvas.evaluate(() => {
          window.testGLLoss=window.__lb.stage.renderer.getContext().getExtension('WEBGL_lose_context');
          if (!window.testGLLoss) throw new Error('The renderer did not expose the WebGL recovery probe');
          window.testGLLoss.loseContext();
        });
        await frame.getByText('正在恢复实验画面…').waitFor();
        await sleep(600);
        await canvas.evaluate(() => window.testGLLoss.restoreContext());
        await state.and(frame.locator('body[data-scene-ready="avgspeed"]')).waitFor();
        result.webglRecovered=true;
        await frame.locator('.p-tab').nth(1).click();
        const release=frame.getByRole('button',{name:/释放小车（停表开始走）/});
        const stop=frame.getByRole('button',{name:/按停表/});
        await release.click();
        await stop.click();
        const rejected=frame.getByRole('row').filter({hasText:/第 1 次 · 不采用：车还没到金属片就按了停表/});
        await rejected.waitFor({timeout:8000});
        result.earlyStopRow=await rejected.innerText();
        await page.screenshot({path:'native-speed-early-stop.png',timeout:12000});
      }
      if(spec.lesson==='inscribed' && width===1440) {
        const point=await canvas.boundingBox();
        await sleep(7500);
        const initial=await canvas.evaluate(getBoat);
        if(initial.fov>40){
          await page.mouse.click(point.x+point.width*.85,point.y+point.height*.4);
          await sleep(1700);
        }
        const positions=[];
        for(const delta of [-42,35]) {
          const box=await canvas.boundingBox();
          const before=await canvas.evaluate(getBoat);
          assert(before.x>0&&before.x<box.width&&before.y>0&&before.y<box.height,JSON.stringify(before));
          const x=box.x+before.x,y=box.y+before.y;
          await page.mouse.move(x,y);
          await page.mouse.down();
          await page.mouse.move(x+delta,y-12,{steps:14});
          await page.mouse.up();
          const after=await canvas.evaluate(getBoat);
          assert(Math.hypot(after.world[0]-before.world[0],after.world[2]-before.world[2])>.001,
                 JSON.stringify({before,after}));
          positions.push({before:before.world,after:after.world});
        }
        result.boatPositions=positions;
        await page.screenshot({path:'final-context-textbook-boat.png',timeout:12000});
      }
      await close.click();
      await iframe.waitFor({state:'detached'});
      await page.waitForFunction(entry=>document.activeElement?.dataset.experimentHotspot===entry,spec.entry);
      assert.equal(await pageNumber.inputValue(),String(spec.page));
      result.restoredSamePageAndFocus=true;
      opened.push(result);
    }
    report.books.push({...spec, adjacentPageClear:true, opened});
    save();
    await reader.getByRole('button',{name:'换资料',exact:true}).click();
  }
  }
  await page.setViewportSize({width:1440,height:900});
  const activityEntry=page.locator('button[aria-label="活动"]').first();
  await activityEntry.waitFor({timeout:30000});
  if (await activityEntry.getAttribute('aria-pressed')!=='true') await activityEntry.click();
  const shelf=page.locator('.dt-viewer-panel');
  await shelf.locator('button[aria-label="新标签页"]').last().click();
  await shelf.getByRole('button',{name:'互动实验',exact:true}).click();
  await shelf.getByRole('group',{name:'科目'}).getByRole('button',{name:'物理',exact:true}).click();
  const rail=shelf.getByRole('navigation',{name:'教材册次'});
  if(await rail.isVisible()) {
    await rail.locator('section').filter({has:page.getByRole('heading',{name:'人教版',exact:true})})
      .getByRole('button',{name:'八年级上册',exact:true}).click();
  } else {
    await shelf.getByRole('combobox',{name:'教材'}).selectOption({label:'人教版 · 八年级上册'});
  }
  const speed=shelf.getByRole('button',{name:/测量小车速度的实验装置/});
  const started=Date.now();
  await speed.click();
  const speedScene=page.locator('.dt-viewer-panel iframe[src*="entry=pep-wuli-8s-avgspeed"]');
  await speedScene.contentFrame().locator('body[data-scene-ready="avgspeed"]').waitFor({state:'attached',timeout:45000});
  const scene=speedScene.contentFrame();
  const operation=scene.locator('.p-tab').nth(1);
  const release=scene.getByRole('button',{name:/释放小车/});
  let method='pointer';
  try {
    await operation.click({timeout:25000});
  } catch(error) {
    if(error.name!=='TimeoutError')throw error;
    if(!await release.isVisible()){
      method='keyboard';
      await operation.press('Enter',{timeout:65000});
    }
  }
  await release.waitFor({state:'visible',timeout:65000});
  await release.press('Enter',{timeout:65000});
  await scene.getByText(/小车下滑了|小车撞上金属片|停表走了好久/).first().waitFor({state:'visible',timeout:65000});
  report.workbench={scene:await speedScene.getAttribute('src'),clickToReadyMs:Date.now()-started,
    operationVisible:true,released:true,operationInput:method};
  save();
  assert.deepEqual(report.errors,[]);
}
(async()=>{
  const browser=await chromium.connectOverCDP('http://127.0.0.1:'+port);
  try{await test(browser);}catch(e){report.failure=e.message;throw e;}finally{save();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
