// Offline only: no Electron, browser, network, model, or product mutation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const t = require('./ci-k12-library-ui.cjs')._test;
let checked = 0;
function check(name, fn) { fn(); checked++; console.log('PASS',name); }
check('complete seed first/last body, not metadata',()=>{
  const markers=t.bodyMarkers('五、综合性学习\n31．2020年春节热播的影片引发同学的深思，请完成第一项活动。\n[图片:abc]\n________\n32．请结合材料谈谈你会用哪些具体行动回报父母。（写出两点）');
  assert.equal(markers.length,2);
  assert(markers[0].startsWith('31.2020'));
  assert(markers[1].endsWith('(写出两点)'));
  assert(!markers.every(m=>t.normalize('完整练习题 · 标题 · 原始资料').includes(m)));
});
check('geometry needs position and size stability',()=>{
  const a={left:4,top:35.5,width:83,height:26};
  assert(t.sameGeometry(a,{...a,top:35.7}));
  assert(!t.sameGeometry(a,{...a,top:36.5}));
  assert(!t.sameGeometry(a,{...a,height:28}));
});
check('native wheel is Intel macOS only',()=>{
  assert.equal(t.nativeWheelDelta('darwin','x64'),160);
  assert.equal(t.nativeWheelDelta('darwin','arm64'),null);
  assert.equal(t.nativeWheelDelta('win32','x64'),null);
});
check('wheel must be trusted, upward and move a non-top scroller',()=>{
  assert(t.wheelFeedback(208.5,75,{trusted:true,deltaY:-320}));
  assert(!t.wheelFeedback(208.5,208.5,{trusted:true,deltaY:-320}));
  assert(!t.wheelFeedback(208.5,75,{trusted:false,deltaY:-320}));
  assert(!t.wheelFeedback(208.5,75,{trusted:true,deltaY:320}));
  assert(t.wheelFeedback(0,0,{trusted:true,deltaY:-160}));
});
check('all expected original images, including exact count',()=>{
  const images=Array.from({length:3},()=>({complete:true,width:12,height:9}));
  assert(t.imagesReady(images,3));
  assert(!t.imagesReady(images.slice(0,2),3));
  assert(!t.imagesReady([...images,{complete:true,width:12,height:9}],3));
  assert(!t.imagesReady([{...images[0],width:0},...images.slice(1)],3));
});
function fakeNode(rect, style={}, attrs={}) {
  return {attrs,style:{display:'flex',visibility:'visible',opacity:'1',color:'rgb(30,58,138)',overflowY:'visible',...style},innerText:'来源',textContent:'来源',parentElement:null,
    getBoundingClientRect(){return {...rect,right:rect.left+rect.width,bottom:rect.top+rect.height};},
    getClientRects(){return this.style.display==='none'?[]:[this.getBoundingClientRect()];},
    getAttribute(key){return this.attrs[key]??null;},setAttribute(key,value){this.attrs[key]=value;},
    scrollIntoView(){},contains(other){for(let p=other;p;p=p.parentElement)if(p===this)return true;return false;},
    closest(selector){for(let p=this;p;p=p.parentElement){if(selector==='a[href]'&&p.attrs.href)return p;}return null;}};
}
check('visible duplicate selection and NAV occlusion are not actionable',()=>{
  const href='#dt-question-safe',hidden=fakeNode({left:0,top:0,width:0,height:0},{display:'none'},{href});
  const visible=fakeNode({left:504,top:35.5,width:83,height:26},{},{href});
  const nav=fakeNode({left:0,top:0,width:844,height:52});nav.tagName='NAV';
  const document={documentElement:{},querySelectorAll:()=>[hidden,visible],elementFromPoint:()=>nav};
  const context={document,getComputedStyle:node=>node.style,innerWidth:844,innerHeight:390};
  const result=vm.runInNewContext(`(${t.inspectTarget.toString()})({href:${JSON.stringify(href)}},'test',false)`,context);
  assert.equal(result.selectedIndex,1);assert.equal(result.clickable,false);assert.equal(result.hit.tag,'NAV');
  document.elementFromPoint=()=>visible;
  assert.equal(vm.runInNewContext(`(${t.inspectTarget.toString()})({href:${JSON.stringify(href)}},'test',false)`,context).clickable,true);
});
check('history and all navigation activation use native mouse, no DOM click',()=>{
  const source=fs.readFileSync(path.join(__dirname,'ci-k12-library-ui.cjs'),'utf8');
  assert(!/\.click\s*\(/.test(source));
  assert(source.includes("type:'mouseDown'"));assert(source.includes("type:'mouseUp'"));
  assert(source.includes("{ flag:'wx' }"));assert(source.includes('expected,markers'));
});
const evidence = process.argv.indexOf('--evidence-root');
if (evidence >= 0) check('frozen native source outputs retain complete first/last and all 3 images',()=>{
  const root=process.argv[evidence+1],seed=JSON.parse(fs.readFileSync(path.join(root,'k12-seed.json'))),markers=t.bodyMarkers(seed.question);
  for(const name of ['01-wheel-fix-cpu4-cache-disabled.json','02-wheel-fix-cpu4-cache-disabled.json']){
    const result=JSON.parse(fs.readFileSync(path.join(root,'evidence-wheel-fix',name))),body=result.after.preview;
    assert(markers.every(marker=>t.normalize(body.text).includes(marker)));
    assert(t.imagesReady(body.images.map(i=>({complete:i.complete,width:i.naturalWidth,height:i.naturalHeight})),seed.images));
  }
});
console.log(JSON.stringify({passed:true,checks:checked,network_calls:0,browser_calls:0,model_calls:0}));
