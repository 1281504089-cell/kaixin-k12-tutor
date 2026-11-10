const {renderMessage}=require('./message-render.cjs');
const templates=require('./templates.json');
const foundations=require('../../deeptutor/services/student_learning/miniapp/reports/subject-foundations.json');
function englishExerciseTargets(n){
 const total=Math.max(7,n*3);if(!n)return Array(total).fill(null);
 const counts=Array(n).fill(3);for(let i=0;i<total-n*3;i++)counts[i%n]++;
 return counts.flatMap((count,i)=>Array(count).fill('W'+(i+1)));
}
function englishExerciseHeading(report){
 const n=report.weaknesses.length,count=report.exercises.length;
 if(!count)return '06 专项巩固：无可核实薄弱点，本次不生成伪个性化题目';
 if(!n)return '06 通用巩固（非个性化薄弱点）：'+count+' 题';
 return count===n*3?'06 专项巩固：'+n+' 个薄弱点 × 每点 3 题 = '+count+' 题':'06 专项巩固：'+n+' 个实证薄弱点 · '+count+' 题';
}

function readable(text){
 const plain=s=>s.replace(/^\s*(?:原文)?依据[：:]\s*(?:\[m\d+\]\s*)+$/gim,'').replace(/[\[（(【]\s*m\d+(?:\s*[、,，/–-]\s*m\d+)*\s*[\]）)】]/gi,'').replace(/(^|[^a-z0-9])m\d+(?=$|[^a-z0-9])/gi,(_,before)=>before);
 // Preserve original quoted answers, code and formulas; m can also be a mathematical variable.
 const protectedText=/(```[\s\S]*?```|`[^`\n]+`|\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|“[^”]*”)/g;
 return String(text).split(protectedText).map((s,i)=>i%2?s:plain(s)).join('').trim();
}
function evidenceContent(message){
 let content=String(message.content||'');
 if(message.role==='assistant'){
  const first=/^\s*(\{[^\r\n]+\})[ \t]*(?:\r?\n|$)/.exec(content);
  if(first)try{const value=JSON.parse(first[1].replace(/([{,]\s*)(kind|action)\s*:/g,'$1"$2":'));if(value.kind==='visual-decision-v1'&&['none','draw','clarify','read-source'].includes(value.action))content=content.slice(first[0].length).trimStart();}catch{}
 }
 // Old replies can contain nested inline delimiters; repair notation, never the student's calculation.
 return content.split(/(```[\s\S]*?```|`[^`\n]+`)/g).map((s,i)=>i%2?s:s.replace(/\$([^$\n]+)\$/g,(_,tex)=>'$'+tex.replace(/\\\(/g,'(').replace(/\\\)/g,')')+'$')).join('');
}
function sources(job){return (job.evidence||[]).map((m,i)=>({...m,content:evidenceContent(m),label:'记录'+(i+1),...(typeof m.inReviewScope==='boolean'?{scopeLabel:m.inReviewScope?'本次学习':'前文上下文'}:{}),roleLabel:m.role==='user'?'学生原话':'AI助手回复',timeLabel:m.createdAt&&!Number.isNaN(Date.parse(m.createdAt))?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(m.createdAt)):'时间未记录'}));}
async function word(job){
 const d=require('docx'),foundation=foundations[job.subject];
 const t=templates[job.subject]||(foundation&&{...templates.english,title:foundation.name+'学习复盘',subtitle:'STUDY REVIEW',chapterCount:7,exerciseIndex:4,answerIndex:5,headings:job.report.sectionTitles});
 if(!t||job.report.sections.length!==t.chapterCount)throw Error('Unknown report template');
 const {Document,Packer,Paragraph,TextRun,Table,TableRow,TableCell,WidthType,BorderStyle,HeadingLevel,AlignmentType,Footer,PageNumber,ImageRun,InternalHyperlink,Bookmark}=d;
 const evidence=sources(job),clean=readable,assets=new Map(),run=(text,opts={})=>new TextRun({text,...opts});
 let drawingId=0;
 const pageWidth=11906-2*templates.marginTwips,bodyWidth=pageWidth/15,muted='5B6871',line=t.line||'D5DFE4';
 const rule=(color,size=4)=>({style:BorderStyle.SINGLE,size,color,space:7});
 const inline=(nodes,style={},available=bodyWidth,display=false)=>(nodes||[]).flatMap(n=>{
  if(n.type==='text')return[run(n.text||'',style)];if(n.name==='br')return[new TextRun({break:1})];
  // Formula assets keep their original TeX in alt text; body text and source quotations remain editable.
  if(n.name==='img'){const a=assets.get(n.attrs?.src);if(!a)throw Error('Missing formula image');const scale=Math.min(display ? 0.94 : 0.84,available/a.width);return[new ImageRun({type:'png',data:Buffer.from(a.base64,'base64'),transformation:{width:Math.max(1,Math.round(a.width*scale)),height:Math.max(1,Math.round(a.height*scale))},altText:{title:'公式',description:a.alt,name:a.id,id:String(++drawingId)}})];}
  return inline(n.children,{...style,...(n.name==='strong'?{bold:true}:{}),...(n.name==='em'?{italics:true}:{}),...(n.name==='s'?{strike:true}:{}),...(n.name==='code'?{font:'Consolas'}:{})},available,display);
 });
 const paragraph=(children,opts={})=>new Paragraph({children,widowControl:true,...opts,spacing:{after:110,line:templates.lineSpacing,lineRule:'auto',...(opts.spacing||{})}});
 const blocks=(nodes,depth=0,opts={},available=bodyWidth)=>(nodes||[]).flatMap(n=>{
  if(n.name==='table'){
   const columns=n.children[0]?.children.length||1,weights=columns===3?[1.25,2.1,3.15]:columns===2?[1,1.55]:Array(columns).fill(1),sum=weights.reduce((a,b)=>a+b),widths=weights.map(w=>Math.floor(pageWidth*w/sum));widths[columns-1]+=pageWidth-widths.reduce((a,b)=>a+b);
   return[new Table({width:{size:pageWidth,type:WidthType.DXA},columnWidths:widths,borders:Object.fromEntries(['top','bottom','left','right','insideHorizontal','insideVertical'].map(k=>[k,rule('D9D9D9',4)])),rows:n.children.map((row,i)=>new TableRow({tableHeader:i===0,cantSplit:true,children:row.children.map((cell,j)=>new TableCell({width:{size:widths[j],type:WidthType.DXA},shading:{fill:i===0?t.accent:i%2?t.pale:'FFFFFF'},margins:{top:125,bottom:125,left:155,right:155},verticalAlign:'center',children:[paragraph(inline(cell.children,{size:20,...(i===0?{bold:true,color:'FFFFFF'}:{})},widths[j]/15-22),{spacing:{after:25,line:300,lineRule:'auto'}})]}))}))}),paragraph([],{spacing:{after:65,line:120}})];
  }
  if(['ul','ol'].includes(n.name))return n.children.flatMap((li,i)=>blocks([{name:'p',children:[{type:'text',text:n.name==='ol'?(i+Number(n.attrs?.start||1))+'. ':'• '},...li.children.flatMap(x=>x.name==='p'?x.children:[x])]}],depth+1,opts,available-16));
  if(/^h[1-6]$/.test(n.name||''))return[paragraph(inline(n.children),{heading:HeadingLevel.HEADING_2,keepNext:true,spacing:{before:185,after:80,line:330}})];
  if(n.name==='blockquote')return blocks(n.children,depth,{...opts,indent:{left:220,right:160},border:{left:rule(line,8)},spacing:{before:80,after:110,line:330}},available-25);
  if(n.name==='hr')return[paragraph([],{border:{bottom:rule(line,4)},spacing:{before:60,after:120,line:80}})];
  const label=n.name==='p'&&n.children?.some(x=>x.name==='strong')&&n.children.every(x=>x.name==='strong'||x.type==='text'&&!x.text.trim());
  if(n.name==='p'||n.name==='pre'||n.type==='text')return[paragraph(n.type==='text'?[run(n.text)]:inline(n.children,{},available,!!n.mathDisplay),{...(depth?{indent:{left:240}}:{}),...(label?{keepNext:true}:{}),...(n.mathDisplay?{alignment:AlignmentType.CENTER,spacing:{before:80,after:140,line:330}}:{}),...(n.name==='pre'?{shading:{fill:'F4F6F7'},indent:{left:160,right:160},spacing:{before:80,after:120,line:300}}:{}),...opts})];
  return blocks(n.children,depth,opts,available);
 });
 const formatted=async(text,opts={},original=false)=>{const r=await renderMessage(original?text:clean(text));for(const a of r.mathAssets)assets.set(a.id,a);return [...blocks(r.nodes,0,opts),...(r.renderWarnings.length?[paragraph([run('部分公式保留原始写法。',{size:19,color:muted})])]:[])];};
 const link=(label,anchor)=>new InternalHyperlink({anchor,children:[run(label,{color:t.accent,size:18,underline:{}})]});
 const headings=t.headings.map((title,i)=>(job.report.sectionTitles?job.report.sectionTitles[i]:job.subject==='english'&&i===t.exerciseIndex?englishExerciseHeading(job.report):title).replace(/[：:]依据真实作答记录$/,''));
 const chapter=(title,bookmark,opts={},extra=[])=>paragraph([new Bookmark({id:bookmark,children:[run(title)]}),...extra],{heading:HeadingLevel.HEADING_1,keepNext:true,shading:{fill:t.pale},border:{left:rule(t.accent,18)},indent:{left:170,right:110},spacing:{before:260,after:135,line:390},...opts});
 const date=job.range?.label||evidence[0]?.timeLabel.slice(0,10)||'未记录';
 const children=[paragraph([run('开心动力  /  超级学霸',{size:19,color:t.accent,bold:true})],{spacing:{after:190,line:260}}),paragraph([run(t.title)],{style:'Title',spacing:{after:100,line:760,lineRule:'exact'}}),paragraph([run(t.subtitle,{size:17,color:muted,characterSpacing:24})],{spacing:{after:205,line:260}}),paragraph([run(clean(job.report.title),{bold:true,size:27})],{keepNext:true,spacing:{after:140,line:380}}),paragraph([run('学习日期  '+date,{size:20,color:muted})],{spacing:{after:210,line:290}})];
 const takeaway=job.report.learningSummary?.length ? job.report.learningSummary : [
  '回看本次的知识点与例题。','把关键步骤用自己的话讲一遍。','独立做完练习，再对照答案和解析。',
 ];
 for(const [i,text] of takeaway.entries())children.push(paragraph([run(['学了什么','记住这一点','下一步怎么练'][i],{bold:true,color:t.accent,size:25})],{keepNext:true,spacing:{before:160,after:90}}),...await formatted(text));
 children.push(paragraph([link('查看复盘正文','chapter_0')],{spacing:{before:210}}));
 const body=[];
 for(const[i,s]of job.report.sections.entries()){
  children.push(chapter(headings[i],'chapter_'+i,{pageBreakBefore:job.report.exercises.length>0&&(i===t.answerIndex||i===t.exerciseIndex&&!job.report.recordSummary)}));
  if(i===t.exerciseIndex){
   children.push(...await formatted(s.text));if(!job.report.exercises.length&&s.text!==job.report.trainingNotice)children.push(paragraph([run(job.report.trainingNotice||'本次没有可核实的个人薄弱项，不编造专项练习。')]));
   let previousType='';
   for(const e of job.report.exercises){
    if(job.subject==='math'&&e.type!==previousType){children.push(paragraph([run(e.type==='choice'?'A  选择题':e.type==='fill'?'B  填空题':'C  解答题',{bold:true,size:24})],{keepNext:true,spacing:{before:170,after:105,line:330}}));previousType=e.type;}
    children.push(paragraph([run('第 '+e.id+' 题',{bold:true,size:23})],{keepNext:true,shading:{fill:t.exercisePale||'F7F8FA'},border:{bottom:rule(line,4)},indent:{left:110,right:100},spacing:{before:170,after:90,line:330}}),...await formatted(e.question,{keepNext:true}));
    for(const[o,k]of e.options.map((o,k)=>[o,k]))children.push(...await formatted(String.fromCharCode(65+k)+'. '+o,{keepNext:true,spacing:{after:60,line:280}}));
    children.push(paragraph([run(e.type==='choice'?'我的选择  ______':e.type==='fill'?'我的答案  __________________________':'我的思路与作答',{color:muted,size:20})],{keepNext:e.type==='solution',spacing:{before:80,after:95,line:300}}));
    if(e.type==='solution'){const lines=job.subject==='math'?3:2;for(let k=0;k<lines;k++)children.push(paragraph([],{keepNext:k<lines-1,border:{bottom:rule('D8DEE3',4)},spacing:{after:100,line:280,lineRule:'exact'}}));}
   }
  }else if(i===t.answerIndex){
   children.push(...await formatted(s.text),paragraph([run(job.report.exercises.length?'完成所有练习后，再对照本节。开放题可接受合理的等价表达。':'本次没有专项训练题，不虚构答案或正确率。',{color:muted,size:20})],{spacing:{after:150,line:310}}));
   for(const e of job.report.exercises)children.push(paragraph([run('第 '+e.id+' 题',{bold:true,size:23})],{keepNext:true,shading:{fill:t.exercisePale||'F7F8FA'},indent:{left:110,right:100},spacing:{before:170,after:90,line:330}}),...await formatted('**参考答案**  '+e.answer,{keepNext:true}),...await formatted(e.explanation));
  }else children.push(...await formatted(s.text));
 }
 children.push(chapter('教材与记录依据','source_appendix',{pageBreakBefore:true}),paragraph([run(evidence.length?'节选处已标注，完整内容可在原对话查看。此处保留学生原始作答。':'这个时段没有可用于复盘的对话原文。正文提供学科知识与练习。',{size:20,color:muted})]));
 children.push(paragraph([run('资料范围说明',{bold:true,size:22})],{keepNext:true}),...await formatted(job.report.cover));
 for(const book of job.textbookScope||[]){
  children.push(paragraph([run(book.title,{bold:true,size:22})],{keepNext:true}));
  children.push(paragraph([run(book.matched?'已定位本次讨论的教材章节':book.outline.length?'教材目录参考，未确认具体学习进度':'PDF 没有可核对的目录',{size:20,color:muted})]));
  if(book.pages.length)children.push(paragraph([run('阅读对话涉及 PDF 第 '+book.pages.join('、')+' 页')]));
  for(const entry of book.outline)children.push(paragraph([run(entry.title+(entry.page?' · PDF 第 '+entry.page+' 页':''))],{spacing:{after:60}}));
 }

 for(const[i,s]of job.report.sections.entries())if(s.refs.length)children.push(paragraph([new Bookmark({id:'evidence_'+i,children:[run(String(i+1).padStart(2,'0')+'  ',{bold:true})]}),...s.refs.flatMap(id=>{const m=evidence.find(x=>x.id===id);return m?[link(m.label,'record_'+m.id.slice(1)),run('  ')]:[];}),link('返回正文','chapter_'+i)],{spacing:{after:105,line:300}}));
 for(const m of evidence){
  children.push(paragraph([new Bookmark({id:'record_'+m.id.slice(1),children:[run(m.label+'  '+m.roleLabel+(m.scopeLabel?'  · '+m.scopeLabel:''),{bold:true,size:20})]}),run('  '+m.timeLabel,{size:18,color:muted})],{keepNext:true,shading:{fill:t.exercisePale||'F7F8FA'},spacing:{before:110,after:65,line:300}}));
  children.push(...await formatted(m.content,{spacing:{after:80,line:330}},true));if(m.hasUnseenImage)children.push(paragraph([run('该条含图片，本次没有读取原图。',{color:muted,size:18})]));
 }
 children.push(...body);
 const font={ascii:'Noto Sans CJK SC',hAnsi:'Noto Sans CJK SC',eastAsia:'Noto Sans CJK SC'};
 const doc=new Document({creator:'开心动力',title:t.title,description:'学生学习复盘',styles:{default:{document:{run:{font,size:templates.bodyPoints*2,color:'000000'},paragraph:{spacing:{line:templates.lineSpacing,lineRule:'auto',after:110},widowControl:true}}},paragraphStyles:[{id:'Title',name:'Title',basedOn:'Normal',run:{size:54,bold:true,color:'000000',font},paragraph:{keepNext:true,spacing:{line:760,lineRule:'exact'}}},{id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',run:{size:28,bold:true,color:'000000'},paragraph:{keepNext:true,spacing:{line:390,lineRule:'auto'}}},{id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',run:{size:24,bold:true,color:'000000'},paragraph:{keepNext:true,spacing:{line:330,lineRule:'auto'}}}]},sections:[{properties:{page:{size:{width:11906,height:16838},margin:{top:templates.marginTwips,bottom:templates.marginTwips,left:templates.marginTwips,right:templates.marginTwips,footer:600}}},footers:{default:new Footer({children:[paragraph([run(t.title+'  ·  ',{size:17,color:muted}),new TextRun({children:[PageNumber.CURRENT],size:17,color:muted}),run(' / ',{size:17,color:muted}),new TextRun({children:[PageNumber.TOTAL_PAGES],size:17,color:muted})],{alignment:AlignmentType.CENTER,spacing:{after:0,line:250}})]})},children}]});
 return Packer.toBuffer(doc);
}
module.exports={word};
