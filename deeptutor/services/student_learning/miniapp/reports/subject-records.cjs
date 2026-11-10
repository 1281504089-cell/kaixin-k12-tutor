const {practice}=require('./subject-practice.cjs');
const foundations=require('./subject-foundations.json');
const name=subject=>foundations[subject]?.name || (subject==='math'?'数学':'英语');
function sample(messages,limit=52000){
 if(messages.length<=180&&JSON.stringify(messages).length<=limit)return messages;
 const byConversation=new Map();for(const m of messages){const key=m.conversationId||'current';if(!byConversation.has(key))byConversation.set(key,[]);byConversation.get(key).push(m);}const groups=[...byConversation.values()];
 const preferred=groups.filter(g=>g.some(m=>m.inReviewScope!==false)),chosen=new Set();let size=0;
 // Keep complete conversation context; large individual conversations still get a factual record summary.
 const order=[];for(let n=0;n<preferred.length;n++){const i=n===0?preferred.length-1:n===1?0:Math.floor((n-1)*(preferred.length-1)/Math.max(1,preferred.length-2));if(!order.includes(i))order.push(i);}for(let i=0;i<preferred.length;i++)if(!order.includes(i))order.push(i);
 for(const i of order){const g=preferred[i],bytes=JSON.stringify(g).length;if(size+bytes>limit||chosen.size+g.length>180)continue;for(const m of g)chosen.add(m);size+=bytes;}
 return messages.filter(m=>chosen.has(m));
}
function records(input,headings){
 const available=input.messages.filter(m=>m.content?.trim()),targets=available.filter(m=>m.inReviewScope!==false);
 const student=targets.filter(m=>m.role==='user'),assistant=targets.filter(m=>m.role==='assistant');
 const bounds=(input.coverageNote?input.coverageNote+'。':'')+(input.omittedIncompleteAssistant?'仍在生成或未完成的助手回复未作为结论依据。':'');
 const scope='范围：'+(input.range?.label||'所选学习记录')+'。已读取'+targets.length+'条记录，其中学生发言'+student.length+'条、已完成的AI助手回复'+assistant.length+'条。'+bounds;
 const {exercises: foundationExercises,topic,guide,matched,passage,workedExample}=practice(input.subject,available);
 const book=input.textbookScope?.find(item=>item.outline?.length);
 const chapters=book?.outline.slice(0,4).map(row=>row.title).join('、');
 const focus=book?.outline.find(row=>!/^(目\s*录|contents)$/i.test(row.title.trim()))?.title;
 const subjectBasics=foundations[input.subject];
 const scoped=subjectBasics&&focus;
 const tasks=scoped?[
  ['翻到「'+focus+'」，写下两个关键词，再用自己的话解释。','两个词都能在这一节找到；解释能说清它们各指什么。'],
  ['从同一节找一个例子、图或材料，说它怎样说明其中一个关键词。','先说材料里的一个具体细节，再说明它和概念的关系。'],
  ['合上教材，试着用一个不同的例子讲同一要点。','新例子符合教材给出的条件；再翻书核对有没有遗漏或套错。'],
 ]:[];
 const exercises=scoped?tasks.map(([question,answer],i)=>({id:i+1,type:'solution',question,answer,explanation:'用所选教材核对，措辞可以不同；遇到说不清的一步，标出来下次复习。',options:[],weaknessId:null})):foundationExercises;
 const trainingNotice=scoped?'用手边这份教材完成三步复习。':(matched?'围绕记录可辨认的知识点':'基础巩固')+' · '+topic+'。以下为新编巩固题。'+(chapters?'这组题用于补练同学科的基础方法。':'')+(passage?'\n\n**阅读材料**\n\n'+passage:'');
 const answers='完成本组练习后，再逐题对照参考答案和解析。';
 const map='**复习主线**\n\n'+topic+' → 写出中间步骤 → 独立练习 → 对照解析。';
 const diagnostic='本次未评估独立作答。做完下方练习，先标出自己有把握的题，再回看犹豫的题。';
 const next='1. 不看解析，先完成练习。\n2. 对照参考答案，圈出最先出现差异的一步。\n3. 合上解析，口述规律并重做一道同类题。';
 const learningSummary=chapters ? [
  '从「'+chapters.slice(0,60)+'」挑一个知识点，用自己的话解释。',
  '合上教材，用自己的话说出一个重点，再翻回去核对。',
  scoped?'用同一章的例子自检，再对照答案。':'做一道相关题，再回到目录定位要复习的章节。',
 ] : [topic+'：'+guide.slice(0,80), '先弄清关键步骤，再用自己的话讲一遍。', '独立练习后再对照答案和解析。'];
 const knowledge = '**核心知识点**';
 const exam = '**常见考法**';
 const pitfalls = '**易错点与纠正**';
 const sections=subjectBasics ? [
  chapters ? '复习从「'+chapters+'」入手。先挑出最难说清的一点，再完成下文的例题和巩固练习。' : '本次可从「'+topic+'」开始做基础回顾。先读下方的解题步骤，再独立用到一个新情境。',
  [knowledge, chapters ? '先挑一个小节，写下「知识点 → 关键条件 → 一句自己的解释」。下面用本学科的基础例子示范这种复习方法。' : guide, ...subjectBasics.studyNotes, exam, subjectBasics.examPatterns].join('\n\n'),
  (scoped?'以下是复习方法的示范例子，请在所选章另找同类材料。\n\n':'')+'**新编基础示例 · '+topic+'**\n\n'+subjectBasics.example,
  pitfalls+'\n\n'+subjectBasics.pitfall+'\n\n不看例题，先用自己的话复述关键步骤。再找一个新例子，写出你用的是哪条规律，以及它在这个例子里为什么成立。做完按三项自检：条件是否写全、理由能否从材料里找出来、结果能否解释清楚。', trainingNotice, answers, next,
 ] : input.subject==='math'?
  [map, knowledge+'\n\n'+guide+'\n\n'+exam+'\n\n选择题先核对条件再比较选项，填空题写下关键计算，解答题写清依据和验算。先确定题目要计算、比较还是说明。用一句话说清所用规则的条件，写出必要的中间式。完成后，先估计答案大小，再用逆运算、代回或另一种解法验算。', pitfalls+'\n\n容易漏掉条件、单位或中间步骤。把自己的解法与例题逐行对照，找出第一次改变结果的步骤，并用代回或逆运算核对。', '**先做一例**\n\n'+workedExample, diagnostic, '重做一题，圈出第一次改变等式、单位或运算顺序的地方。', trainingNotice, answers, next]:
  [chapters?'按教材目录回看「'+chapters+'」对应的练习句。':'回看上次读过的句子，用一句中文复述大意。', '回看原句时先标词性，再根据句中人物、动作和上下文确定词义。给一个重点词写两个搭配，分别造句，检查换了主语或时间之后动词形式要不要跟着变。', '把词组放回完整句子，标出动词与主语、宾语或时间短语。先保留句型、换一个人物，再保留人物、换一个时间。读出改写后的句子，检查意思和形式是否都正确。', [knowledge,guide,exam,'常见任务有动词填空、句型改写、阅读定位。先圈时间与主语，再判断句型，阅读题回到原句核对。',pitfalls,'容易沿用原句的动词形式。换主语、时态或加入助动词后，把整句再读一遍。'].join('\n\n'), diagnostic, trainingNotice, answers, next];
 const sectionTitles=headings[input.subject].map((h,i)=>input.subject==='math'?(i===6?'七、知识点巩固训练（10题）':h):input.subject==='english'&&i===5?'06 知识点巩固练习（7题）':h);
 return {report:{recordSummary:true,sectionTitles,title:name(input.subject)+'学习复盘 · '+topic,cover:scope+' 练习用于巩固，个人掌握情况以实际作答为准。',sections:headings[input.subject].map((_,i)=>({text:sections[i],refs:[]})),weaknesses:[],exercises,trainingNotice,learningSummary}};
}
module.exports={sample,records};
