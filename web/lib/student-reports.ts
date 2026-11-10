import { apiFetch, apiUrl, asJsonOrThrow } from './api'

export const reportSubjectNames = { chinese: '语文', math: '数学', english: '英语', physics: '物理', chemistry: '化学', biology: '生物', history: '历史', geography: '地理', politics: '政治' }
export type ReportSubject = keyof typeof reportSubjectNames
export const reportSubjectHints: Record<ReportSubject, string> = {
  chinese: '字词、篇章与表达', math: '算理、题型与错因', english: '课文、词汇与语法',
  physics: '现象、公式与实验', chemistry: '现象、方程式与实验', biology: '结构、功能与过程',
  history: '时间线、史料与影响', geography: '读图、区域与成因', politics: '概念、材料与生活案例',
}
export type ReportSession = { workspace_id: string; session_id: string }
export type ReportSessionChoice = ReportSession & { title: string; workspace_name: string; kind: 'chat' | 'reading'; updated_at: number }
export type ReportPeriod = { from_date: string; to_date: string; subject?: ReportSubject; textbook_id?: string; extra_sessions?: ReportSession[] }
export const reportSessionKey = (session: ReportSession) => `${session.workspace_id}:${session.session_id}`
export const MAX_EXTRA_REPORT_SESSIONS = 20
export type ReportClaim = { text: string; title?: string; subject?: string; next?: string; refs: string[]; contextRefs: string[] }
export type ReportEvidence = { id: string; role: 'user' | 'assistant'; content: string; date: string | null; recordedAt?: string; kind?: string; projectName: string; title: string; status: string; has_images: boolean; content_excerpt?: boolean }
export type ReportMetrics = { message_count: number; conversation_count: number; active_days: number; minutes: number | null; exercise_count: number | null; accuracy: number | null; reflection_count?: number }
export type ReflectionAnswers = { goal: string; state: string; process: string; adjustment: string }
export type ReportReflection = { id?: string; revision: number; answers: ReflectionAnswers; saved_at: number | null }
type SubjectExercise = { id: number; question: string; options: string[]; answer: string; explanation: string }
export type TextbookScope = { title: string; matched: boolean; pages: number[]; outline: { title: string; page?: number }[] }
type ReportFigure = { section: number; caption: string; alt: string; png: string }
export type SubjectReview = { figure?: ReportFigure; title: string; cover: string; learningSummary?: string[]; sections: (ReportClaim & { title: string })[]; exercises: SubjectExercise[] }
export type LearningReport = { id: string; range: { from: string; to: string }; subject?: ReportSubject; extra_session_count?: number; created_at: number; state: 'pending' | 'ready' | 'failed'; stage: 'generating' | 'reviewing' | null; message: string; metrics: ReportMetrics; stale: boolean; summary?: { overview: ReportClaim; records: ReportClaim[]; observations: ReportClaim[]; nextSteps: ReportClaim[] } | null; subject_review?: SubjectReview; result_level?: 'records' | 'full'; evidence?: ReportEvidence[]; textbook_scope?: TextbookScope[]; coverage?: { factDates: string[]; missingDates: string[]; partialDates: string[] } }
export type ReportOverview = { range: { from: string; to: string }; metrics: ReportMetrics; coverage: { factDates: string[]; missingDates: string[]; partialDates: string[] }; reflection?: ReportReflection; report: LearningReport | null; history: LearningReport[]; missing_extra_sessions?: number }

export function beijingDate(now = new Date()) {
  return new Date(now.getTime() + 8 * 3600_000).toISOString().slice(0, 10)
}

export function presetPeriod(days: number, now = new Date(), yesterday = false): ReportPeriod {
  const end = Date.parse(beijingDate(now) + 'T00:00:00+08:00') - (yesterday ? 86400_000 : 0)
  return { from_date: beijingDate(new Date(end - (days - 1) * 86400_000)), to_date: beijingDate(new Date(end)) }
}

export async function getReports(period: ReportPeriod, signal?: AbortSignal): Promise<ReportOverview> {
  const params = new URLSearchParams({ from_date: period.from_date, to_date: period.to_date })
  if (period.subject) params.set('subject', period.subject)
  if (period.textbook_id) params.set('textbook_id', period.textbook_id)
  for (const session of period.extra_sessions ?? []) params.append('extra_session', reportSessionKey(session))
  return asJsonOrThrow(await apiFetch(apiUrl('/api/student/reports?' + params), { signal }))
}
export async function getReportSessions(subject: ReportSubject, offset: number, signal: AbortSignal): Promise<{ sessions: ReportSessionChoice[]; next_offset: number | null }> {
  const params = new URLSearchParams({ subject, offset: String(offset) })
  return asJsonOrThrow(await apiFetch(apiUrl('/api/student/reports/sessions?' + params), { signal }))
}
export async function generateReport(period: ReportPeriod): Promise<LearningReport> {
  return asJsonOrThrow(await apiFetch(apiUrl('/api/student/reports'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(period) }))
}
export async function getReport(id: string, signal?: AbortSignal): Promise<LearningReport> {
  return asJsonOrThrow(await apiFetch(apiUrl('/api/student/reports/' + encodeURIComponent(id)), { signal }))
}
export async function downloadReportWord(id: string): Promise<Blob> {
  const response = await apiFetch(apiUrl('/api/student/reports/' + encodeURIComponent(id) + '/word'))
  if (!response.ok) await asJsonOrThrow(response)
  return response.blob()
}
export async function getReportHistory(signal?: AbortSignal): Promise<LearningReport[]> {
  return asJsonOrThrow(await apiFetch(apiUrl('/api/student/reports/history'), { signal }))
}
export async function removeReport(id: string): Promise<void> {
  await asJsonOrThrow(await apiFetch(apiUrl('/api/student/reports/' + encodeURIComponent(id)), { method: 'DELETE' }))
}
export async function saveReflection(period: ReportPeriod, revision: number, answers: ReflectionAnswers): Promise<ReportReflection> {
  const { from_date, to_date, subject } = period
  return asJsonOrThrow(await apiFetch(apiUrl('/api/student/reports/reflection'), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ from_date, to_date, subject, revision, ...answers }) }))
}

export function learningOnly(text: string) {
  const protectedText = /(```[\s\S]*?```|`[^`\n]+`|\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])/g
  return text.split(protectedText).map((part, i) => i % 2 ? part : part
    .replace(/^\s*(?:原文)?依据[：:]\s*(?:\[m\d+\]\s*)+$/gim, '')
    .replace(/[\[（(【]\s*m\d+(?:\s*[、,，/–-]\s*m\d+)*\s*[\]）)】]/gi, '')
    .replace(/(^|[^a-z0-9])m\d+(?=$|[^a-z0-9])/gi, '$1')
    .replace(/[（(]\s*[）)]/g, '')).join('').trim()
}

export function subjectSectionMarkdown(review: SubjectReview, subject: ReportSubject, index: number) {
  const section = review.sections[index]
  const exerciseIndex = subject === 'english' ? 5 : subject === 'math' ? 6 : 4
  if (index === exerciseIndex) {
    return [learningOnly(section.text), ...review.exercises.map(e => [
      `#### ${e.id}. ${e.question}`,
      ...e.options.map((option, i) => `${String.fromCharCode(65 + i)}. ${option}`),
    ].join('\n\n'))].join('\n\n')
  }
  if (index === exerciseIndex + 1) {
    return [learningOnly(section.text), ...review.exercises.map(e => `#### ${e.id}. 参考答案\n\n${e.answer}\n\n${e.explanation}`)].join('\n\n')
  }
  return learningOnly(section.text)
}

export function reportMarkdown(report: LearningReport, parent: boolean) {
  if (report.subject && report.subject_review) {
    const review = report.subject_review
    return [`# ${review.title}`, `${report.range.from} 至 ${report.range.to}`, ...(review.learningSummary ?? []).map(learningOnly),
      ...review.sections.map((section, i) => `## ${section.title}\n\n${subjectSectionMarkdown(review, report.subject!, i)}`),
      '## 教材与记录依据', review.cover,
      ...(report.textbook_scope ?? []).map(book => ['### ' + book.title,
        ...book.outline.map(entry => '- ' + entry.title + (entry.page ? ' · PDF 第 ' + entry.page + ' 页' : '')),
      ].join('\n')),
      ...(report.evidence ?? []).map((record, index) =>
        '### 记录 ' + (index + 1) + ' · ' + (record.role === 'user' ? '学生' : 'AI 助手') + (record.content_excerpt ? ' · 原文节选' : '') + '\n\n' + record.content),
    ].join('\n\n')
  }
  if (!report.summary) return ''
  const { summary, metrics } = report
  const lines = [`# ${parent ? '孩子的学习近况' : '我的学习报告'}`, `${report.range.from} 至 ${report.range.to}`, summary.overview.text, `记录范围：${metrics.message_count}条对话记录，${metrics.conversation_count}段对话，${metrics.active_days}个有提问的日期。`, '学习时长、练习总数与正确率：未记录，不由聊天时长或讲解内容推算。']
  for (const [title, claims] of [['实际讨论', summary.records], ['原文观察', summary.observations], ['下一步可以尝试', summary.nextSteps]] as const) {
    if (claims.length) lines.push('## ' + title, ...claims.map(c => (c.title ? '### ' + c.title + '\n' : '') + c.text + (c.next ? '\n可选建议：' + c.next : '')))
  }
  lines.push('## 记录说明', '仅依据所选日期的本机学习记录，经过生成与独立核对；助手讲解、学生自报与独立作答分开看。无记录不等于没学习，讨论不等于掌握。')
  if (parent) lines.push('家长视角展示的是当前账号同一份事实，没有向其他账号共享。')
  return lines.join('\n\n')
}
