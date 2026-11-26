const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright-core');
const cases = JSON.parse(fs.readFileSync(path.join(__dirname,'cases.json')));
const [port,lane,...names]=process.argv.slice(2);const active=path.join(__dirname,lane+'-current-case.txt');
(async()=>{const b=await chromium.connectOverCDP('http://127.0.0.1:'+port);try{
 let p;
 for(let i=0;i<600&&!p;i++){
  const student=b.contexts()[0].pages().find(t=>/^http:\/\/127\.0\.0\.1:\d+\/chat/.test(t.url()));
  if(student && await student.getByRole('button',{name:'发送',exact:true}).isVisible().catch(()=>false)
        && await student.locator('button.dt-navigation-toggle').filter({hasText:'科目项目'}).isVisible().catch(()=>false))p=student;
  if(!p)await new Promise(r=>setTimeout(r,650));
 }
 if(!p)throw Error('Student launch did not finish');
 await p.bringToFront();
 for(const item of names){ const key=item,group='results'; const dir=path.join(__dirname,group);fs.mkdirSync(dir,{recursive:true});
  const sub='物理',question=cases[key].prompt;const create=p.getByRole('button',{name:'在'+sub+'中新建对话',exact:true});
  if(key!=='carry'&&!key.startsWith('follow_')){const nav=p.locator('button.dt-navigation-toggle').filter({hasText:'科目项目'}); if(await nav.count()&&await nav.getAttribute('aria-expanded')==='false')await nav.click(); const created=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/student-study/physics/conversations'),{timeout:55000});await create.click({timeout:50000});
    const {session_id}=await (await created).json();
    await p.waitForURL(u=>u.pathname==='/chat/'+session_id,{waitUntil:'commit',timeout:75000});
    await p.waitForFunction(()=>document.querySelector('button[aria-label="选老师"]')?.innerText.includes('物理') && !document.querySelector('[data-chat-message-role="user"]'),null,{timeout:75000});
  }
  if(true){
   const receipt=p.waitForResponse(r=>r.request().method()==='POST' && /\/uploads\/[^/?]+\/complete/.test(r.url()), {timeout:30000});
   await p.getByRole('button',{name:'资源',exact:true}).click();
   await p.getByText('上传附件',{exact:true}).click();
   const picked=p.waitForEvent('filechooser');
   await p.getByText('临时使用',{exact:true}).click();
   await picked;
   const session=await p.context().newCDPSession(p);
   try{
    const {root}=await session.send('DOM.getDocument');
    const {nodeId}=await session.send('DOM.querySelector',{nodeId:root.nodeId,selector:'input[type=file][aria-hidden=true]'});
    await session.send('DOM.setFileInputFiles',{nodeId,files:[path.join(__dirname,key==='found'?'课堂练习.txt':'流体记录.txt')]});
   }finally{await session.detach();}
   const uploaded=await receipt;if(!uploaded.ok())throw Error('Upload '+uploaded.status()); await p.getByText(key==='found'?'课堂练习.txt':'流体记录.txt',{exact:true}).last().waitFor({state:'visible',timeout:45000});
  }
  const editor=p.locator('[contenteditable=true][role=textbox], textarea').last();
  await editor.fill(question);const send=p.getByRole('button',{name:'发送',exact:true}).last();await send.waitFor();fs.writeFileSync(active,key);
  const typed=await p.getByRole('button',{name:'选老师',exact:true}).innerText().catch(()=>null);
  const prior=await p.locator('[data-chat-message-role="assistant"]').count();
  const snapshot=()=>p.evaluate(prior=>{
   const turns=[...document.querySelectorAll('[data-chat-message-role="assistant"]')];const a=turns.length>prior?turns.at(-1):null;
   const blocks=a?[...a.querySelectorAll('[role="article"] .md-renderer')]:[];
   const submit=[...document.querySelectorAll('button')].find(n=>/^提交(答案|回答)?$/.test(n.innerText.trim())&&n.getBoundingClientRect().height>0);
   const body=blocks.map(e=>{const c=e.cloneNode(true);for(const math of c.querySelectorAll('.katex')){const a=math.querySelector('annotation');if(a)math.replaceWith(a.textContent)}return c.textContent}).join('\n').trim(); const rendered=blocks.map(e=>e.innerText).join('\n');
   return {body, rendered, strong:blocks.flatMap(e=>[...e.querySelectorAll('strong')].map(n=>n.innerText)),card:!!submit,cardText:submit?.closest('div.rounded-xl')?.innerText||'', send:!!document.querySelector('button[aria-label="发送"]'), error:!!document.querySelector('[data-orphaned-failed-turn]')};
  },prior);
  const t=performance.now();await send.click();
  const ms=()=>Math.round(performance.now()-t);let first=null,card=null,last={}, sawBusy=false;
  while(ms()<110000){
   last=await snapshot(); if(!last.send)sawBusy=true;
   if(last.body && first===null)first=ms();
   if(last.card && card===null)card=ms();
   if(last.card || last.error || (sawBusy&&last.send&&last.body))break;
   await p.waitForTimeout(100);
  }
  const readyMs=ms();if(!last.card){await p.waitForTimeout(800);last=await snapshot();}
  const out={key,sub,question,teacher:typed,first,cardMs:card,end:readyMs,...last};fs.writeFileSync(path.join(dir,key+'.json'),JSON.stringify(out,null,2));console.log(JSON.stringify([lane,key,first,card,out.end,last.body.length,last.strong.length,last.error]));
  if(!last.card&&!last.body||out.end>=110000) throw Error('No completed UI result '+key);
  if(key==='found'&&(!last.card||!last.cardText.includes('课堂练习.txt')))throw Error('missing attached question source');
  if(last.card){
   await p.screenshot({path:path.join(dir,key+'.png')});
   if(key==='found'){
    const submit=p.getByRole('button',{name:'提交',exact:true});
    
    const option=p.getByRole('button').filter({hasText:/0[.]8 *g/}).last();
    await option.click({timeout:8000}); await p.waitForTimeout(100); if(await option.getAttribute('aria-pressed')!=='true')throw Error('choice not selected'); fs.writeFileSync(path.join(__dirname,'grade-selected.txt'),'B'); await submit.click();
    await p.getByText(/你选 B 正确/).first().waitFor({state:'visible',timeout:60000});
    const feedback=await snapshot();out.feedback=await p.getByText(/你选 B 正确/).first().innerText();fs.writeFileSync(path.join(dir,key+'.json'),JSON.stringify(out,null,2));
   }
  }
  fs.writeFileSync(active,'');
 }
}finally{fs.writeFileSync(active,'');await b.close()}})().catch(e=>{console.error(e.stack);process.exitCode=1})
