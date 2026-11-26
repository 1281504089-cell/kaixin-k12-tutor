const {chromium}=require('playwright-core'),fs=require('node:fs'),path=require('node:path');
const question="请你根据旋转缩放帮我出 3 道选择题测试一下，不查资料，自己出题。每道题旁边必须给我配一个图。";
(async()=>{const b=await chromium.connectOverCDP('http://127.0.0.1:'+process.env.QA_CDP);
const label=(process.env.QA_TRIAL||'')+process.argv[2],record={question, cards:[], submitted:false};let page,start;
try{for(let i=0;i<160&&!page;i++){page=b.contexts()[0].pages().find(p=>p.url().startsWith('http://127.0.0.1:'));if(!page)await new Promise(r=>setTimeout(r,750));}if(!page)throw Error('隔离桌面未打开聊天窗口');await page.locator('textarea:visible').last().waitFor({timeout:50000});const resume=process.env.QA_RESUME==='1';const url=resume?'/chat/'+fs.readFileSync(path.join(__dirname,'已核三题会话.txt'),'utf8').trim()+'?dt_workspace=':'/chat?dt_workspace=';await page.goto(new URL(url,page.url()).href,{waitUntil:'domcontentloaded'});await page.setViewportSize({width:1360,height:920});
fs.writeFileSync(path.join(__dirname,'case'),process.env.QA_CASE_ID||'quiz');if(!resume)await page.locator('textarea:visible').last().fill(question);
start=performance.now();if(!resume)await page.getByRole('button',{name:'发送',exact:true}).click();
const msg=page.locator('[data-chat-message-role=assistant]').last(), figures=msg.locator('section[aria-label="本题配图"]');
let last=null;
for(let i=0;i<3;i++){
 let limit=i?7000:(['once','always'].includes(process.env.QA_CASE_ID)?45000:100000);
 await Promise.race([figures.last().waitFor({timeout:limit}),msg.getByText(/这道题的配图没有通过核对|请求的操作未完成/).first().waitFor({timeout:limit}).then(()=>{throw Error('本轮配图或题卡未交付')})]);
 const figure=figures.last();await figure.scrollIntoViewIfNeeded();const svg=figure.locator('svg[viewBox],canvas[data-board-ready=true],img');
 await svg.first().waitFor({timeout:limit});const opt=msg.locator('button[aria-pressed]:enabled').filter({hasNotText:'自己填写'});await Promise.race([opt.first().waitFor({timeout:limit}),msg.getByText(/这道题的配图没有通过核对|请求的操作未完成/).first().waitFor({timeout:limit}).then(()=>{throw Error('未交付可答题卡')})]);
 const card=await figure.evaluate(el=>({stem:el.parentElement.previousElementSibling?.innerText,options:[...el.parentElement.nextElementSibling?.querySelectorAll('button')||[]].map(b=>b.innerText),t:el.parentElement.innerText.slice(0,1400),svg:el.querySelector('svg[viewBox]')?.outerHTML.slice(0,24000),canvas:!!el.querySelector('canvas[data-board-ready=true]')}));
 if (!card.stem || !card.options.length) throw Error('题干或选项缺失');
 if (last===card.stem) throw Error('题卡未切换');last=card.stem;record.cards.push({...card,ms:Math.round(performance.now()-start)});
 await figure.screenshot({path:path.join(__dirname,label+'-q'+(i+1)+'.png')});const wasLast=await msg.getByRole('button',{name:/^提交(回答)?$/}).count();await opt.first().click();
 if(wasLast)break;
 await page.waitForTimeout(150);
}
const submit=msg.getByRole('button',{name:/^提交(回答)?$/});if(await submit.count()){await submit.click();record.submitted=true;await msg.locator('button[aria-pressed]:enabled').first().waitFor({state:'hidden',timeout:12000}).catch(()=>{});await page.waitForTimeout(1000);}
}catch(e){record.error=String(e).slice(0,420);}finally{if(page){record.final=(await page.locator('[data-chat-message-role=assistant]').last().innerText().catch(()=>'' )).slice(-4600);}record.endMs=start?Math.round(performance.now()-start):null;fs.writeFileSync(path.join(__dirname,label+'-quiz.json'),JSON.stringify(record,null,2));console.log(label,record.cards.map(c=>c.ms),record.submitted);await b.close();}})().catch(e=>{console.error(e);process.exitCode=1});
