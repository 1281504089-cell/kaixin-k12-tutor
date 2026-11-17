const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const t=require('./ci-k12-library-ui.cjs')._test,baseline=require('./ci-k12-library-ui.click-baseline.cjs')._test;
const a={rect:{left:370,top:726,width:114,height:32},clip:{left:308,top:60,right:1319,bottom:809},point:{x:427,y:742}};
const checks=[];function check(name,fn){fn();checks.push(name);console.log('PASS',name)}
check('stable target includes the same hit point and ancestor clipping',()=>{assert(t.sameClickGeometry(a,structuredClone(a)));assert(!t.sameClickGeometry(a,{...a,clip:{...a.clip,bottom:900}}));assert(!t.sameClickGeometry(a,{...a,point:{x:427,y:870}}));assert(!t.sameClickGeometry(undefined,a))});
check('a 128px late reflow invalidates previously stable coordinates',()=>assert(!t.sameClickGeometry(a,{...a,rect:{...a.rect,top:854},point:{x:427,y:870}})));
function probe({fonts='loaded',animation}={}){
  const rect={left:370,top:726,right:484,bottom:758,width:114,height:32};
  const node={parentElement:null,innerText:'查看完整原题',textContent:'查看完整原题',getBoundingClientRect:()=>rect,getClientRects:()=>[rect],getAttribute:key=>key==='href'?'#original':null,setAttribute(){},contains:other=>other===node,closest:()=>node,getAnimations:()=>animation?[animation]:[]};
  const document={fonts:{status:fonts},documentElement:{},querySelectorAll:()=>[node],elementFromPoint:()=>node};
  return vm.runInNewContext(`(${t.inspectTarget.toString()})({href:'#original'},'target',false)`,{document,getComputedStyle:()=>({display:'block',visibility:'visible',opacity:'1'}),innerWidth:1366,innerHeight:900});
}
check('loading font metrics prevent committing a click',()=>assert(probe({fonts:'loading'}).layoutPending));
check('a running finite target animation prevents committing a click',()=>assert(probe({animation:{playState:'running',effect:{getTiming:()=>({iterations:1})}}}).layoutPending));
check('a pending finite animation also prevents committing a click',()=>assert(probe({animation:{pending:true,playState:'idle',effect:{getTiming:()=>({iterations:1})}}}).layoutPending));
check('an infinite decoration does not block the target forever',()=>assert.equal(probe({animation:{playState:'running',effect:{getTiming:()=>({iterations:Infinity})}}}).layoutPending,false));
check('settled geometry remains actionable',()=>{const p=probe();assert(p.clickable&&!p.layoutPending)});
check('original PDF, identity, private-header, cancellation and wheel gates are unchanged',()=>{for(const name of ['nativeSpec','inspectNativePages','assertNativeResponse','captureNativeResponse','continueNativeRequest','waitReady','nativeWheelDelta','wheelFeedback','calibratedWheelDelta'])assert.equal(t[name].toString(),baseline[name].toString(),name)});
check('trusted click identity assertion and old prepared IMG function are unchanged',()=>{
  const before=fs.readFileSync(__dirname+'/ci-k12-library-ui.click-baseline.cjs','utf8'),after=fs.readFileSync(__dirname+'/ci-k12-library-ui.cjs','utf8');
  const gate=source=>source.slice(source.indexOf("    await wait(token => window.__k12Driver.events.some"),source.indexOf('  async function preparedPictureHistory('));assert.equal(gate(after),gate(before));
  const prepared=source=>source.slice(source.indexOf('  async function preparedPictureHistory('),source.indexOf('  async function nativeHTTP('));assert.equal(prepared(after),prepared(before));assert(!/\.click\s*\(/.test(after));
});
fs.writeFileSync(__dirname+'/NATIVE-CLICK-SELFCHECK.json',JSON.stringify({passed:true,checks:checks.length,names:checks,network_calls:0,browser_calls:0,model_calls:0},null,2)+'\n');
