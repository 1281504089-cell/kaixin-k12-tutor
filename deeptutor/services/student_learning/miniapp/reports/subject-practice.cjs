// Reviewed practice templates used when an independently checked AI report is unavailable.
const mathTopics = [
  {
    name: '空间向量的数量积', pattern: /空间向量|数量积|点积/,
    guide: '把向量写成坐标。对应坐标相乘再相加得到数量积。非零向量数量积为零时，两向量垂直。',
    problem(n) {
      const a = n + 2, dot = 2*a - n + 3;
      return [`已知向量 $\\vec a=(${a},${n},1)$，$\\vec b=(2,-1,3)$，求数量积 $\\vec a\\cdot\\vec b$`,
        String(dot), `分别乘对应坐标，再相加。$${a}\\times2+${n}\\times(-1)+1\\times3=${dot}$。第二个分量的乘积带负号。`,
        [dot - 1, dot + 1, dot + 2*n].map(String)];
    },
  },
  {
    name: '分数与通分', guide: '先找公分母，再把每个分数变成等值分数。分母相同时只把分子相加，最后检查能否约分。', pattern: /异分母|通分|分数加减|分数加法|分数的加/,
    problem(n) {
      const d = n + 2;
      return [`计算 $\\frac{1}{${d}}+\\frac{1}{${2*d}}$`, `$\\frac{3}{${2*d}}$`,
        `最小公分母是 ${2*d}。把第一项化成 $\\frac{2}{${2*d}}$，分母不变，分子相加得 $\\frac{3}{${2*d}}$。接受约分后的等价结果。`,
        [`$\\frac{2}{${2*d}}$`, `$\\frac{4}{${2*d}}$`, `$\\frac{5}{${2*d}}$`]];
    },
  },
  {
    name: '一元一次方程', guide: '目标是把未知数单独留在等式一边。等式两边做相同运算，解出后代回原式检验。', pattern: /一元一次方程|解方程|移项/,
    problem(n) {
      const a = n + 2, b = n + 1, x = n + 3;
      return [`解方程 $${a}x+${b}=${a*x+b}$`, String(x),
        `等式两边同时减去 ${b}，得到 $${a}x=${a*x}$。再同时除以 ${a}，得 $x=${x}$，代回原式成立。`,
        [x - 1, x + 1, x + 2].map(String)];
    },
  },
  {
    name: '长方形的面积', guide: '用相同长度单位量出长和宽，再将二者相乘。周长用长度单位，面积用平方单位。', pattern: /长方形面积|长方形的面积|矩形面积/,
    problem(n) {
      const a = n + 3, b = n + 2;
      return [`一个长方形长 ${a} 厘米，宽 ${b} 厘米，求面积`, `${a*b} 平方厘米`,
        `长方形的面积等于长乘宽，$${a}\\times${b}=${a*b}$。面积用平方厘米作单位。`,
        [a*b - 1, a*b + 1, a+b].map(v => `${v} 平方厘米`)];
    },
  },
  {
    name: '运算顺序与验算', guide: '有括号先算括号，乘除优先于加减。同级运算一般从左到右，写下中间结果便于验算。', pattern: /运算顺序|混合运算|四则运算/,
    problem(n) {
      const a = n + 1, b = n + 3, c = n + 2;
      return [`计算 $${a}+${b}\\times${c}$`, String(a+b*c),
        `先乘后加。$${b}\\times${c}=${b*c}$，再算 $${a}+${b*c}=${a+b*c}$。`,
        [(a+b)*c, a+b*c-1, a+b*c+1].map(String)];
    },
  },
];
const englishTopics = [
  { name: '一般过去时', guide: '先圈出 yesterday、last week 等时间线索。肯定句注意规则和不规则过去式，did 后用动词原形。', pattern: /一般过去时|simple past|past tense/i, rows: [
    ['Yesterday, Mia ___ (walk) to school.', 'walked', 'Yesterday 指过去，规则动词 walk 加 -ed。'],
    ['We ___ (visit) the museum last Sunday.', 'visited', 'last Sunday 指过去，visit 加 -ed。'],
    ['Tom ___ (go) home at five yesterday.', 'went', 'go 的过去式是不规则形式 went。'],
    ['They ___ (have) lunch at noon yesterday.', 'had', 'have 的不规则过去式是 had。'],
    ['I ___ (see) a fox in the park last week.', 'saw', 'see 的不规则过去式是 saw。'],
    ['改成一般疑问句。She played chess yesterday.', 'Did she play chess yesterday?', '一般疑问句用 Did，后面的 played 还原成 play。'],
    ['翻译。昨天我没有看电视。', 'I did not watch TV yesterday.', '否定句用 did not 加动词原形 watch。'],
  ]},
  { name: '一般现在时与动词形式', guide: '先看主语和时间。肯定句中第三人称单数常用 -s、-es 或 -ies，does 后用动词原形。', pattern: /一般现在时|第三人称单数|simple present|present simple/i, rows: [
    ['Nina ___ (read) every day.', 'reads', 'Nina 是第三人称单数，一般现在时用 reads。'],
    ['They ___ (read) every day.', 'read', '主语是 They，动词用原形 read。'],
    ['Leo ___ (go) to school by bus.', 'goes', 'Leo 是第三人称单数，go 变为 goes。'],
    ['Anna ___ (study) after dinner.', 'studies', 'study 以辅音字母加 y 结尾，变 y 为 i，再加 -es。'],
    ['We ___ (play) football on Fridays.', 'play', '主语是 We，动词用原形 play。'],
    ['改成一般疑问句。She likes apples.', 'Does she like apples?', '用 Does 提问，likes 还原成 like。'],
    ['改成否定句。He watches TV every evening.', 'He does not watch TV every evening.', '用 does not 加动词原形 watch 表达否定。'],
  ]},
  { name: '短文阅读与词句理解', guide: '先圈出人物、时间和动作，再回到原句找证据。because 后通常说明原因，about 可以引出主题。', pattern: /阅读理解|短文|reading comprehension/i, passage: 'On Friday, Lily goes to the library with Ben. She borrows a book about birds. Ben chooses a book about trains. They leave at four because the library closes then.', rows: [
    ['Which day do Lily and Ben go to the library?', 'Friday.', '首句 On Friday 明确说明日期。'],
    ['Who goes with Lily?', 'Ben.', '首句 with Ben 表示和 Ben 一起。'],
    ['What is Lily’s book about?', 'Birds.', '第二句中的 about birds 说明书的主题。'],
    ['What is Ben’s book about?', 'Trains.', '第三句中的 about trains 说明书的主题。'],
    ['What time do they leave?', 'At four.', '末句的 leave at four 直接给出时间。'],
    ['Why do they leave at four?', 'Because the library closes at four.', 'because 后面的内容解释了离开的原因。'],
    ['根据上下文写出 borrows 的中文意思。', '借入。', '图书馆的情境中，borrows a book 表示借入一本书。'],
  ]},
];

function practice(subject, messages) {
  const fallback = require('./subject-foundations.json')[subject];
  if (fallback) return {topic:fallback.topic,guide:fallback.guide,matched:false,exercises:fallback.questions.map(([question,answer,explanation],i)=>({id:i+1,type:'solution',question,answer,explanation,options:[],weaknessId:null}))};
  const topics = subject === 'math' ? mathTopics : englishTopics;
  const turns = messages.filter(m => m.role === 'user' && m.kind !== 'student_reflection').slice(-12).reverse();
  const matched = turns.map(m => topics.find(t => t.pattern.test(m.content + '\n' + (m.title || '')))).find(Boolean)
    || topics.find(t => messages.some(m => t.pattern.test(m.title || '')));
  const topic = matched || topics.at(-1);
  const exercises = subject === 'math' ? Array.from({length: 10}, (_, i) => {
    const [stem, answer, explanation, alternatives] = topic.problem(i + 1);
    const type = i < 4 ? 'choice' : i < 8 ? 'fill' : 'solution';
    const options = type === 'choice' ? [...alternatives] : [];
    if (type === 'choice') options.splice(i, 0, answer);
    return {id: i + 1, type, question: stem + (type === 'solution' ? '，写出计算步骤，并检查结果。' : '。'), options,
      answer: type === 'choice' ? `${'ABCD'[i]}．${answer}` : answer, explanation, weaknessId: null};
  }) : topic.rows.map(([question, answer, explanation], i) => ({
    id: i + 1, type: question.includes('___') ? 'fill' : 'solution', question, options: [], answer, explanation, weaknessId: null,
  }));
  const example = subject === 'math' ? topic.problem(11) : null;
  return {exercises, topic: topic.name, guide: topic.guide, matched: !!matched, passage: topic.passage,
    workedExample: example ? example[0]+'。\n\n'+example[2] : undefined};
}

module.exports = {practice};
