const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const t=require('./ci-k12-library-ui.cjs')._test,baseline=require('./ci-k12-library-ui.visibility-baseline.cjs')._test;
const href='#dt-question-'+'a'.repeat(64)+'-math%3Aoriginal';
const box=(left,top,width,height)=>({left,top,width,height,right:left+width,bottom:top+height});
function node(rect,attrs={}){return {attrs,parentElement:null,innerText:'原生题卡',textContent:'原生题卡',style:{display:'block',visibility:'visible',opacity:'1',overflowY:'visible'},getBoundingClientRect:()=>rect,getClientRects:()=>[rect],getAttribute:key=>attrs[key]??null,setAttribute:(key,value)=>{attrs[key]=value},scrollIntoView(){},contains(other){for(let p=other;p;p=p.parentElement)if(p===this)return true;return false},closest(selector){if(selector==='a[href]'&&attrs.href)return this;return this.parentElement?.closest(selector)||null}}}
function fixture(cardTop){
  const root=node(box(272,52,572,138));root.style.overflowY='auto';root.clientHeight=138;root.clientWidth=572;root.scrollHeight=667;root.scrollTop=72;
  const prose=node(box(547,172.5,84,26),{href}),card=node(box(307,cardTop,502,311)),foreign=node(box(307,80,502,311));card.parentElement=root;foreign.parentElement=root;prose.parentElement=root;
  const caption=node(box(320,cardTop+285,232,16),{href});caption.parentElement=card;card.querySelectorAll=()=>[caption];foreign.querySelectorAll=()=>[node(box(0,0,5,5),{href:href+'-other'})];
  const document={documentElement:{},querySelectorAll:selector=>selector==='[aria-label="题库原题"] figure'?[foreign,card]:[prose,caption],elementFromPoint:()=>cardTop<190?card:prose};
  const probe=spec=>vm.runInNewContext(`(${t.inspectTarget.toString()})(spec,'visibility',false)`,{document,spec,getComputedStyle:n=>n.style,innerWidth:844,innerHeight:390});
  return {probe,card,root};
}
let checks=0;function check(name,fn){fn();checks++;console.log('PASS',name)}
check('native reveal selects only the figure for the exact citation identity',()=>{const f=fixture(70),p=f.probe({cardHref:href});assert(p.found&&p.clickable);assert.equal(p.candidates.length,1);assert.equal(p.rect.top,70);assert.equal(f.card.attrs['data-k12-click-id'],'visibility')});
check('a visible prose citation cannot qualify an offscreen original card',()=>{const f=fixture(211);assert(f.probe({href}).clickable);assert.equal(f.probe({cardHref:href}).clickable,false)});
check('wrong question identity cannot select a different native figure',()=>assert.equal(fixture(70).probe({cardHref:href+'-wrong'}).found,false));
check('native figure reveal calibrates against the outer chat scroll root',()=>{const f=fixture(70),p=f.probe({cardHref:href});assert.equal(p.root.clientHeight,138);assert.equal(p.root.scrollTop,72);assert.equal(f.root.attrs['data-k12-scroll-id'],'visibility')});
check('all PDF readiness, original-byte and private-header gates stay unchanged',()=>{for(const name of ['waitReady','inspectNativePages','assertNativeResponse','captureNativeResponse','nativeWheelDelta','wheelFeedback','calibratedWheelDelta'])assert.equal(t[name].toString(),baseline[name].toString().replaceAll('[aria-label="题库原题图"]','[aria-label="题库原题"]'),name)});
const expectedURL='http://127.0.0.1/api/student/question-bank/native/original',item={id:'held-original',network_id:'network-original',url:expectedURL};
const requests=()=>[{type:'request',id:item.network_id,url:expectedURL}];
const aborted=()=>({type:'failed',id:item.network_id,error:'net::ERR_ABORTED'});
async function asyncCheck(name,fn){await fn();checks++;console.log('PASS',name)}
(async()=>{
  await asyncCheck('an active held request continues with response interception',async()=>{
    const calls=[],debug={sendCommand:async(method,args)=>calls.push({method,args})};
    const result=await t.continueNativeRequest(debug,item,requests(),expectedURL);assert(result.continued);assert.deepEqual(calls,[{method:'Fetch.continueRequest',args:{requestId:item.id,interceptResponse:true}}]);
  });
  await asyncCheck('only an originally bound ERR_ABORTED retires a stale held ID',async()=>{
    const result=await t.continueNativeRequest({sendCommand:async()=>assert.fail('Cancelled ID was reused')},item,[...requests(),aborted()],expectedURL);assert(result.cancelled_before_response&&!result.continued);
  });
  await asyncCheck('Invalid InterceptionId racing its original cancellation is confirmed',async()=>{
    const network=requests(),debug={sendCommand:async()=>{setTimeout(()=>network.push(aborted()),30);throw Error('Invalid InterceptionId.')}};
    assert((await t.continueNativeRequest(debug,item,network,expectedURL)).cancelled_before_response);
  });
  await asyncCheck('Invalid InterceptionId without original ERR_ABORTED stays a failure',async()=>assert.rejects(t.continueNativeRequest({sendCommand:async()=>{throw Error('Invalid InterceptionId.')}},item,requests(),expectedURL),/Invalid InterceptionId/));
  await asyncCheck('another request cancellation cannot excuse an invalid ID',async()=>assert.rejects(t.continueNativeRequest({sendCommand:async()=>{throw Error('Invalid InterceptionId.')}},item,[...requests(),{...aborted(),id:'other'}],expectedURL),/Invalid InterceptionId/));
  await asyncCheck('other protocol failures remain failures',async()=>assert.rejects(t.continueNativeRequest({sendCommand:async()=>{throw Error('Protocol target closed')}},item,requests(),expectedURL),/Protocol target closed/));
  await asyncCheck('unbound held IDs cannot be retired or continued',async()=>assert.rejects(t.continueNativeRequest({sendCommand:async()=>assert.fail()},item,[aborted()],expectedURL),/original Network identity/));
  await asyncCheck('a held URL mismatch fails before protocol continuation',async()=>assert.rejects(t.continueNativeRequest({sendCommand:async()=>assert.fail()},item,requests(),expectedURL+'-wrong')));
  fs.writeFileSync(__dirname+'/NATIVE-VISIBILITY-SELFCHECK.json',JSON.stringify({passed:true,checks,network_calls:0,browser_calls:0,model_calls:0},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1});
