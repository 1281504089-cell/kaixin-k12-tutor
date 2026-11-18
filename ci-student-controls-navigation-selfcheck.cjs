// Offline QA-only selector/contract check. No Electron, HTTP, model or user data.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {inspectMaterialShelves,assertMaterialShelves}=require('./ci-k12-library-ui.cjs')._test;
let checks=0;
const check=(name,fn)=>{fn();checks++;console.log('PASS '+name);};
const labels=['教材库','题库','长期资料'];
function fixture({names=labels,selected=['教材库'],groups=1,hidden=-1,uploadInput=false,uploadAction=false,overflow=false}={}) {
 const buttons=names.map((textContent,index)=>({textContent,offsetHeight:index===hidden?0:44,getAttribute:name=>name==='aria-pressed'?String(selected.includes(textContent)):null}));
 const group={querySelectorAll:selector=>{assert.equal(selector,'button');return buttons;}};
 const document={documentElement:{scrollWidth:overflow?1368:1366},querySelectorAll:selector=>selector==='[role="group"][aria-label="资料类型"]'?Array.from({length:groups},()=>group):selector==='button'?(uploadAction?[...buttons,{textContent:'批量上传资料',offsetHeight:44}]:buttons):[],querySelector:selector=>selector==='input[aria-label="选择要长期保存的资料"]'&&uploadInput?{}:null};
 return JSON.parse(JSON.stringify(vm.runInNewContext(`(${inspectMaterialShelves.toString()})()`,{document,innerWidth:1366})));
}
check('exact shared three shelves, one initial textbook selection, no upload controls',()=>assertMaterialShelves(fixture(),'教材库',false));
check('long-term selection exposes actual input plus a visible upload action',()=>assertMaterialShelves(fixture({selected:['长期资料'],uploadInput:true,uploadAction:true}),'长期资料',true));
check('old two-shelf UI is rejected rather than reported as the new three-shelf UI',()=>assert.throws(()=>assertMaterialShelves(fixture({names:labels.slice(0,2)}),'教材库',false)));
check('duplicated or absent shelf groups are rejected',()=>{for(const groups of [0,2])assert.throws(()=>assertMaterialShelves(fixture({groups}),'教材库',false));});
check('wrong order, unknown category and duplicated labels are rejected',()=>{for(const names of [[labels[1],labels[0],labels[2]],[...labels.slice(0,2),'知识库'],[labels[0],labels[1],labels[1]]])assert.throws(()=>assertMaterialShelves(fixture({names}),'教材库',false));});
check('hidden shelf button is not accepted as a visible student entry',()=>assert.throws(()=>assertMaterialShelves(fixture({hidden:2}),'教材库',false)));
check('none, multiple, or incorrect selected states are rejected',()=>{for(const selected of [[],['题库'],['教材库','题库']])assert.throws(()=>assertMaterialShelves(fixture({selected}),'教材库',false));});
check('file input alone cannot stand in for real long-term upload action',()=>assert.throws(()=>assertMaterialShelves(fixture({selected:['长期资料'],uploadInput:true}),'长期资料',true)));
check('upload controls leaking into default textbook shelf are rejected',()=>assert.throws(()=>assertMaterialShelves(fixture({uploadInput:true,uploadAction:true}),'教材库',false)));
check('viewport overflow still rejects the shelf layout',()=>assert.throws(()=>assertMaterialShelves(fixture({overflow:true}),'教材库',false)));
check('native driver actually executes strict default/long-term shelf checks and retains full source gates',()=>{
 const source=fs.readFileSync(__dirname+'/ci-k12-library-ui.cjs','utf8');
 assert(source.includes("const shelf=await js(inspectMaterialShelves);assertMaterialShelves(shelf,'教材库',false)"));
 assert(source.includes("assertMaterialShelves(longtermShelf,'长期资料',true)"));
 assert(source.includes('threeMaterialEntries:true,materialShelves:{initial:shelf,longterm:longtermShelf}'));
 assert(source.includes('twoLibraryEntries:true,separateUploads:true'));
 assert(source.includes('originalBodyStartEnd:historySource.originalBodyStartEnd'));
 assert(source.includes('const nativePages = await nativePageHistory()'));
 assert(!/\.click\s*\(/.test(source),'Native K12 navigation must still use trusted mouse activation');
});
check('bulk and reference paths explicitly navigate to long-term originals without removing byte guards',()=>{
 const source=fs.readFileSync(__dirname+'/ci-materials-ui.cjs','utf8');
 assert(source.includes("await click('资料库')"));
 assert.equal((source.match(/await click\('长期资料'\)/g)||[]).length,3);
 assert(!source.includes('资料库 · 教材与长期资料'));assert(!source.includes('从资料库选择'));
 assert(source.includes('Shared reference shelves did not open in this chat'));
 assert(source.includes("assert.deepEqual(referenceShelves,[{label:'教材库',selected:true,visible:true},{label:'题库',selected:false,visible:true},{label:'长期资料',selected:false,visible:true}])"));
 for(const gate of ['Referenced original changed','Reference duplicated a library upload','Reference created an upload or conversation','same-document','native-background-00.txt'])assert(source.includes(gate),gate);
});
console.log(JSON.stringify({passed:true,checks,network_calls:0,browser_calls:0,model_calls:0,formal_data_used:false}));
