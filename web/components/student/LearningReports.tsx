'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent } from 'react'
import { ArrowDownToLine, ArrowRight, CalendarDays, Check, CheckCheck, ChevronRight, Clipboard, FileChartColumnIncreasing, History, Leaf, Loader2, MessageCircle, Plus, Quote, RefreshCw, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { Dialog } from '@/shared/ui/Dialog'
import Tooltip from '@/shared/ui/Tooltip'
import RichMarkdownRenderer from '@/components/common/RichMarkdownRenderer'
import { listMaterials, type MaterialInfo } from '@/lib/reading-api'
import ReportSessionPicker from './ReportSessionPicker'
import { beijingDate, downloadReportWord, generateReport, getReport, getReportHistory, getReports, presetPeriod, removeReport, learningOnly, reportMarkdown, reportSubjectHints, reportSubjectNames, saveReflection, subjectSectionMarkdown, type LearningReport, type ReflectionAnswers, type ReportClaim, type ReportOverview, type ReportPeriod, type ReportSubject } from '@/lib/student-reports'
import styles from './LearningReports.module.css'

type Modal = { type: 'history' | 'dates' | 'sources' | 'sessions' | 'textbooks'; claim?: ReportClaim }
const presets = [{ label: '今天', days: 1 }, { label: '昨天', days: 1, yesterday: true }, { label: '近7天', days: 7 }, { label: '近14天', days: 14 }, { label: '近28天', days: 28 }]
const dateLabel = (value: string) => value.replaceAll('-', '.')
const label = (report: LearningReport) => report.state === 'pending' ? '正在整理' : report.state === 'failed' ? '未完成' : report.result_level === 'records' ? '知识点巩固版' : report.stale ? '有新记录' : '已核对'
const emptyReflection: ReflectionAnswers = { goal: '', state: '', process: '', adjustment: '' }
const reflectionQuestions = [{ key: 'goal', name: '目标管理', prompt: '这段时间，我想解决什么？', placeholder: '想弄懂的内容，或想完成的一件事…' }, { key: 'state', name: '状态检查', prompt: '现在的我，顺在哪里、卡在哪里？', placeholder: '按自己的感受写，不必给自己打分…' }, { key: 'process', name: '过程感知', prompt: '我具体做了什么尝试？', placeholder: '区分听讲解、跟着做和自己重做…' }, { key: 'adjustment', name: '及时调节', prompt: '接下来，我愿意怎样调整？', placeholder: '一小步就好。计划不代表已经执行…' }] as const

export default function LearningReports() {
  const [period, setPeriod] = useState<ReportPeriod>(() => presetPeriod(7))
  const [draftPeriod, setDraftPeriod] = useState(period)
  const [data, setData] = useState<ReportOverview | null>(null)
  const [report, setReport] = useState<LearningReport | null>(null)
  const [historyId, setHistoryId] = useState('')
  const [history, setHistory] = useState<LearningReport[]>([])
  const [pdfs, setPdfs] = useState<MaterialInfo[]>([])
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState(false)
  const [parent, setParent] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState('')
  const [dateError, setDateError] = useState('')
  const [reflection, setReflection] = useState<ReflectionAnswers>(emptyReflection)
  const [reflectionDirty, setReflectionDirty] = useState(false)
  const [reflectionBusy, setReflectionBusy] = useState(false)
  const [reflectionError, setReflectionError] = useState('')
  const dirtyReflection = useRef(false)
  const [copied, setCopied] = useState(false)
  const [modal, setModal] = useState<Modal | null>(null)
  const [closing, setClosing] = useState(false)
  const [origin, setOrigin] = useState({ x: 0, y: 0 })
  const dialogHost = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestVersion = useRef(0)
  const alive = useRef(true)
  const motionVersion = useRef(0)
  const pending = report?.state === 'pending'

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; requestVersion.current++; motionVersion.current++; if (closeTimer.current) clearTimeout(closeTimer.current); if (copyTimer.current) clearTimeout(copyTimer.current) }
  }, [])

  const load = useCallback(async (signal?: AbortSignal) => {
    const version = ++requestVersion.current
    try {
      const [next, historical, list] = await Promise.all([
        period.subject && !historyId ? getReports(period, signal) : Promise.resolve(null),
        historyId ? getReport(historyId, signal) : Promise.resolve(null),
        !period.subject || historyId ? getReportHistory(signal) : Promise.resolve(null),
      ])
      if (alive.current && version === requestVersion.current) {
        setData(next); setReport(historical || next?.report || null); setHistory(list || next?.history || []); setError('')
        if (!dirtyReflection.current) setReflection(next?.reflection?.answers || emptyReflection)
      }
    } catch (caught) {
      if (!signal?.aborted && alive.current && version === requestVersion.current) { setReport(null); setData(null); setError(caught instanceof Error ? caught.message : '暂时没能读取报告，请重试。') }
    } finally {
      if (alive.current && version === requestVersion.current) setLoading(false)
    }
  }, [period, historyId])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  useEffect(() => {
    if (!pending) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    async function tick() {
      if (document.hidden || controller.signal.aborted) return
      await load(controller.signal)
      if (!controller.signal.aborted) timer = setTimeout(tick, 1800)
    }
    function visible() { if (timer) clearTimeout(timer); if (!document.hidden) void tick() }
    timer = setTimeout(tick, 1800)
    document.addEventListener('visibilitychange', visible)
    return () => { if (timer) clearTimeout(timer); controller.abort(); document.removeEventListener('visibilitychange', visible) }
  }, [pending, load])

  useEffect(() => {
    if (pending) return
    const controller = new AbortController()
    function refreshVisible() { if (!document.hidden) void load(controller.signal) }
    window.addEventListener('focus', refreshVisible)
    document.addEventListener('visibilitychange', refreshVisible)
    return () => { controller.abort(); window.removeEventListener('focus', refreshVisible); document.removeEventListener('visibilitychange', refreshVisible) }
  }, [pending, load])

  useLayoutEffect(() => {
    if (!modal) return
    const panel = dialogHost.current?.querySelector<HTMLElement>('[role="dialog"]')
    if (!panel) return
    const left = (window.innerWidth - panel.offsetWidth) / 2
    const top = (window.innerHeight - panel.offsetHeight) / 2
    panel.style.transformOrigin = origin.x || origin.y ? `${origin.x - left}px ${origin.y - top}px` : '50% 50%'
    panel.dataset.originX = String(origin.x)
    panel.dataset.originY = String(origin.y)
  }, [modal, origin])

  function open(event: MouseEvent<HTMLButtonElement>, next: Modal) {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    motionVersion.current++
    const rect = event.currentTarget.getBoundingClientRect()
    setOrigin(event.detail ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : { x: 0, y: 0 })
    setClosing(false); setModal(next)
    if (next.type === 'textbooks') {
      setPdfLoading(true); setPdfError(false)
      void listMaterials().then(items => { if (alive.current) setPdfs(items.filter(item => item.render_mode === 'pdf')) })
        .catch(() => { if (alive.current) setPdfError(true) })
        .finally(() => { if (alive.current) setPdfLoading(false) })
    }
    if (next.type === 'dates') { setDraftPeriod(period); setDateError('') }
  }
  function close() {
    if (closing) return
    setClosing(true)
    const version = ++motionVersion.current
    closeTimer.current = setTimeout(() => { if (alive.current && motionVersion.current === version) { setModal(null); setClosing(false) } }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 220)
  }
  function choose(next: ReportPeriod) {
    if (dirtyReflection.current) { setError('四问补充还没保存，请先保存或放弃修改，再调整复盘范围。'); return }
    if (!historyId && period.subject === next.subject && period.textbook_id === next.textbook_id && period.from_date === next.from_date && period.to_date === next.to_date
      && JSON.stringify(period.extra_sessions ?? []) === JSON.stringify(next.extra_sessions ?? [])) return
    requestVersion.current++
    setLoading(true)
    setPeriod(next); setHistoryId(''); setReport(null); setData(null); setReflection(emptyReflection); setError(''); setReflectionError('')
  }

  async function saveSupplement() {
    if (reflectionBusy || pending) return
    setReflectionBusy(true); setReflectionError('')
    try {
      await saveReflection(period, data?.reflection?.revision || 0, reflection)
      if (alive.current) { dirtyReflection.current = false; setReflectionDirty(false); await load() }
    } catch (caught) { if (alive.current) setReflectionError(caught instanceof Error ? caught.message : '保存未完成，当前填写已保留。') }
    finally { if (alive.current) setReflectionBusy(false) }
  }

  async function generate() {
    if (!period.subject || busy || pending) return
    setBusy(true); setError('')
    try {
      const next = await generateReport(period)
      if (alive.current) { setHistoryId(''); setReport(next); await load() }
    } catch (caught) { if (alive.current) setError(caught instanceof Error ? caught.message : '这次未能开始整理，原记录保留。') }
    finally { if (alive.current) setBusy(false) }
  }
  async function copy() {
    if (!report?.summary && !report?.subject_review) return
    try {
      await navigator.clipboard.writeText(reportMarkdown(report, parent)); setCopied(true)
      if (copyTimer.current) clearTimeout(copyTimer.current)
      copyTimer.current = setTimeout(() => setCopied(false), 2000)
    } catch { setError('未能复制，请使用旁边的下载按钮保存。') }
  }
  async function download() {
    if (!report?.summary && !report?.subject_review || downloading) return
    setDownloading(true)
    setError('')
    try {
      const word = Boolean(report.subject && report.subject_review)
      const file = word ? await downloadReportWord(report.id) : new Blob([reportMarkdown(report, parent)], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(file)
      const link = document.createElement('a')
      link.href = url
      link.download = `${report.subject ? reportSubjectNames[report.subject] : ''}学习报告-${report.range.from}-${report.range.to}.${word ? 'docx' : 'md'}`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '暂时无法下载报告，请重试。')
    } finally {
      setDownloading(false)
    }
  }
  async function remove(row: LearningReport) {
    if (!window.confirm('移除这份报告？原对话和学习记录会保留。建议先下载需要保留的报告。')) return
    try {
      await removeReport(row.id)
      if (historyId === row.id) setHistoryId('')
      if (report?.id === row.id) setReport(null)
      await load()
    } catch { setError('未能移除报告，请重新读取后再试。'); close() }
  }

  const metrics = report?.metrics || data?.metrics
  const summary = report?.summary
  const subjectReview = report?.subject_review
  const directRefs = new Set(subjectReview?.sections.flatMap(section => section.refs))
  const textbookLabel = pdfs.find(book => book.material_id === period.textbook_id)?.title || '已选 PDF'
  const displayedSubject = historyId ? report?.subject : period.subject
  const missingSessions = data?.missing_extra_sessions ?? 0
  const extraCount = period.extra_sessions?.length ?? 0
  const canGenerate = !!period.subject && !historyId && !missingSessions && !loading && !pending && !busy && !reflectionDirty && !reflectionBusy
  const range = report?.range || data?.range
  const periodLabel = range && range.from === range.to ? dateLabel(range.from) : `${dateLabel(range?.from || period.from_date)} — ${dateLabel(range?.to || period.to_date)}`
  const sourceRows = modal?.claim ? (report?.evidence || []).filter(row => modal.claim!.contextRefs.includes(row.id)) : []
  const sourceButton = (claim: ReportClaim) => <button type="button" className={styles.sourceButton} onClick={event => open(event, { type: 'sources', claim })}><Quote size={13} />查看依据<ChevronRight size={12} /></button>

  return <main className={styles.page} aria-label="学习报告">
    <header className={styles.header}>
      <div><span className={styles.eyebrow}><Leaf size={13} />学习复盘</span><h1>回看这段时间，学到了什么</h1><p>选一门学科，按日期整理原项目里的学习记录和后续练习。</p></div>
      <button type="button" className={styles.quiet} onClick={event => open(event, { type: 'history' })}><History size={16} />历史报告{history.length ? <span className={styles.count}>{history.length}</span> : null}</button>
    </header>

    <section className={styles.subjectPicker} aria-label="选择复盘学科">
      {(Object.keys(reportSubjectNames) as ReportSubject[]).map(subject => <button key={subject} type="button" aria-pressed={displayedSubject === subject} disabled={busy || pending || reflectionBusy} onClick={() => choose({ ...period, subject, extra_sessions: period.subject === subject ? period.extra_sessions : undefined, textbook_id: period.subject === subject ? period.textbook_id : undefined })}>
        <strong>{reportSubjectNames[subject]}复盘</strong>
        <small>{reportSubjectHints[subject]}</small>
      </button>)}
    </section>
    {period.subject && !historyId && <section className={styles.toolbar} aria-label="选择报告日期">
      <div className={styles.presets}>{presets.map(item => {
        const selected = presetPeriod(item.days, new Date(), item.yesterday)
        return <button type="button" key={item.label} disabled={busy || pending || reflectionBusy} aria-pressed={!historyId && period.from_date === selected.from_date && period.to_date === selected.to_date} onClick={() => choose({ ...period, ...selected })}>{item.label}</button>
      })}</div>
      <button type="button" className={styles.dates} disabled={busy || pending || reflectionBusy} onClick={event => open(event, { type: 'dates' })}><CalendarDays size={15} /><span>{periodLabel}</span><ChevronRight size={13} /></button>
    </section>}

    {period.subject && !historyId && <div className={styles.sessionScope}>
      <span>默认纳入{reportSubjectNames[period.subject]}项目的对话{extraCount ? `，已补充 ${extraCount} 段` : ''}</span>
      <div className={styles.scopeActions}>
        <button type="button" className={styles.quiet} disabled={busy || pending || reflectionBusy} onClick={event => open(event, { type: 'textbooks' })}>{period.textbook_id ? textbookLabel : '选择教材 PDF'}</button>
        <button type="button" className={styles.quiet} disabled={busy || pending || reflectionBusy} onClick={event => open(event, { type: 'sessions' })}><Plus size={15} />补充对话</button>
      </div>
      {!!missingSessions && <p role="status">有 {missingSessions} 段补充对话在所选日期内没有可用记录。请调整日期或取消勾选。</p>}
    </div>}

    {(period.subject || historyId) && !subjectReview && <section className={styles.metrics} aria-label="所选日期的记录统计">
      {[{ name: '学习对话', value: metrics?.conversation_count, unit: '段', note: '有实际交流的对话' }, { name: '活跃日期', value: metrics?.active_days, unit: '天', note: '有学生消息的日期' }, { name: '对话记录', value: metrics?.message_count, unit: '条', note: '学生与老师的文字记录' }, { name: '学习时长', value: null, unit: '', note: '未开启互动计时，不作推算' }].map(item => <div key={item.name} className={styles.metric}><span>{item.name}</span><strong>{loading ? '—' : item.value == null ? '未记录' : <>{item.value}<small>{item.unit}</small></>}</strong><p>{item.note}</p></div>)}
    </section>}

    {period.subject && !historyId && <details className={styles.reflection}><summary><span><Leaf size={15} />补充四问复盘<small>选填 · 学生自报</small></span><span>{reflectionDirty ? '尚未保存' : data?.metrics.reflection_count ? '已保存' : '默认收起'}<ChevronRight size={14} /></span></summary><p>针对所选日期回忆一下。你的补充会单独保留来源；感受、计划和已完成的尝试分开写，不填也可以生成报告。</p><form onSubmit={event => { event.preventDefault(); void saveSupplement() }}><div className={styles.reflectionGrid}>{reflectionQuestions.map((item, i) => <label key={item.key}><span><small>0{i + 1}</small>{item.name}</span><strong>{item.prompt}</strong><textarea aria-label={item.name} rows={3} maxLength={1500} placeholder={item.placeholder} value={reflection[item.key]} disabled={reflectionBusy || pending} onChange={event => { dirtyReflection.current = true; setReflectionDirty(true); setReflection(previous => ({ ...previous, [item.key]: event.target.value })) }} /></label>)}</div>{reflectionError && <p role="alert" className={styles.reflectionError}>{reflectionError}</p>}<div className={styles.reflectionFooter}><small>只在本机保存，不调用模型。保存时间不当作学习发生时间。</small>{reflectionDirty && <button type="button" className={styles.quiet} disabled={reflectionBusy} onClick={() => { dirtyReflection.current = false; setReflectionDirty(false); setReflection(data?.reflection?.answers || emptyReflection); setReflectionError('') }}>放弃修改</button>}<button type="submit" className={styles.primary} disabled={!reflectionDirty || reflectionBusy || pending}>{reflectionBusy ? <Loader2 size={14} className={styles.spin} /> : <Check size={14} />}保存补充</button></div></form></details>}

    {error && <div className={styles.error} role="alert"><span>{error}</span><button type="button" onClick={() => void load()}>重新读取</button></div>}
    {historyId && <div className={styles.notice}><History size={15} />正在查看已保存的历史快照。<button type="button" onClick={() => { setHistoryId(''); setReport(null) }}>回到当前范围</button></div>}
    {report?.stale && <div className={styles.notice}><RefreshCw size={15} />这份报告之后有新记录，或整理规则已更新。原报告保留。{!historyId && <button type="button" disabled={!canGenerate} onClick={() => void generate()}>更新报告</button>}</div>}

    {!period.subject && !historyId ? <section className={styles.empty}>
      <FileChartColumnIncreasing size={32} /><h2>先选一门学科</h2><p>默认整理对应项目的记录，也可以补充普通聊天和学习栏里的对话。</p>
    </section> : loading ? <div className={styles.loading} role="status"><Loader2 className={styles.spin} size={22} />正在读取本机学习记录…</div> : pending || busy ? <section className={styles.preparing} aria-live="polite">
      <div className={styles.preparingIcon}><Loader2 className={styles.spin} size={28} /></div><h2>{report?.stage === 'reviewing' ? '再核对一遍，让回顾更可靠。' : '正在把这段学习，整理清楚。'}</h2><p>保留完整原文，区分你的作答与老师的讲解。</p>
      <div className={styles.steps}><span data-active="true">{report?.stage === 'reviewing' ? <Check size={15} /> : <Loader2 size={15} className={styles.spin} />}整理原文</span><i /><span data-active={report?.stage === 'reviewing'}><ShieldCheck size={15} />独立核对</span></div><small>可以离开本页，回来继续查看；不会因重复打开而再次生成。</small>
    </section> : report?.subject && subjectReview ? <article className={styles.report}>
      <div className={styles.reportHeader}>
        <div><h2>{learningOnly(subjectReview.title)}</h2><p>{periodLabel}</p></div>
        <div className={styles.reportTools}>
          <button className={styles.iconButton} type="button" aria-label={copied ? '已复制报告' : '复制报告'} onClick={() => void copy()}>{copied ? <Check size={17} /> : <Clipboard size={17} />}</button>
          <Tooltip label={downloading ? "正在生成 Word" : "下载 Word"}><button className={styles.iconButton} type="button" aria-label="下载 Word" disabled={downloading} onClick={() => void download()}>{downloading ? <Loader2 className={styles.spin} size={17} /> : <ArrowDownToLine size={17} />}</button></Tooltip>
        </div>
      </div>
      <div className={styles.subjectReport}>
        {!!subjectReview.learningSummary?.length && <div className={styles.subjectCover}>
          {subjectReview.learningSummary.map((line, i) => <div className={styles.learningTakeaway} key={i}><strong>{['学了什么', '记住这一点', '下一步怎么练'][i]}</strong><RichMarkdownRenderer content={learningOnly(line)} variant="compact" enableMath enableImages={false} /></div>)}
        </div>}
        {subjectReview.sections.map((section, i) => <section className={styles.subjectSection} key={section.title}>
          <h3>{section.title.replace(/[：:]依据真实作答记录$/, '')}</h3>
          <RichMarkdownRenderer content={subjectSectionMarkdown(subjectReview, report.subject!, i)} variant="compact" enableMath enableImages={false} />
        </section>)}
        <details className={styles.reportBasis} key={report.id}>
          <summary>教材与记录依据<ChevronRight size={14} /></summary>
          <div className={styles.subjectCover}><RichMarkdownRenderer content={subjectReview.cover} variant="compact" enableMath enableImages={false} /></div>
          {report.result_level === 'records' && <div className={styles.notice} role="status">{report.message}{!historyId && <button type="button" disabled={!canGenerate} onClick={() => void generate()}>重试专项报告</button>}</div>}
          <section className={styles.subjectSection}><h3>教材范围</h3>
            {report.textbook_scope?.length ? report.textbook_scope.map((book, i) => <div key={i}><h4>{book.title}</h4>
              <p>{book.matched ? '定位到本次讨论的章节' : book.outline.length ? '目录可供参考，未确认具体学到哪一章' : 'PDF 未提供可核对的目录'}</p>
              {book.pages.length > 0 && <p>阅读对话涉及 PDF 第 {book.pages.join('、')} 页</p>}
              {book.outline.length > 0 && <ul>{book.outline.map((entry, index) => <li key={index}>{entry.title}{entry.page && ` · PDF 第 ${entry.page} 页`}</li>)}</ul>}
            </div>) : <p>本次没有关联的教材 PDF，按可用学习记录整理。</p>}
          </section>
          <section className={styles.subjectSection}><h3>对话记录</h3><div className={styles.sources}>
            {report.evidence?.length ? report.evidence.map((row, i) => <section key={row.id}>
              <div><span>记录 {i + 1} · {directRefs.has(row.id) ? '直接依据' : '对话上下文'}</span><small>{row.date || '自报补充'} · {row.projectName} · {row.role === 'user' ? '我' : 'AI 助手'}</small></div>
              <h4>{row.title}{row.content_excerpt && ' · 原文节选'}</h4><RichMarkdownRenderer content={row.content} variant="compact" enableMath enableImages={false} />
            </section>) : <p>没有可展示的对话原文。</p>}
          </div></section>
        </details>
      </div>
    </article> : summary && report ? <article className={styles.report}>
      <div className={styles.reportHeader}><div><span className={styles.verified}><ShieldCheck size={14} />已完成独立核对</span><h2>{parent ? '孩子的学习近况' : '我的学习回顾'}</h2><p>{periodLabel}</p></div><div className={styles.reportTools}><div className={styles.views} aria-label="报告阅读视角"><button type="button" aria-pressed={!parent} onClick={() => setParent(false)}>学生</button><button type="button" aria-pressed={parent} onClick={() => setParent(true)}>家长</button></div><Tooltip label={copied ? '已复制' : '复制报告'}><button className={styles.iconButton} type="button" aria-label={copied ? '已复制报告' : '复制报告'} onClick={() => void copy()}>{copied ? <Check size={17} /> : <Clipboard size={17} />}</button></Tooltip><Tooltip label="下载报告"><button className={styles.iconButton} type="button" aria-label="下载报告" onClick={download}><ArrowDownToLine size={17} /></button></Tooltip></div></div>
      <div className={styles.overview}><Quote size={23} /><div><p>{summary.overview.text}</p>{sourceButton(summary.overview)}</div></div>
      {parent && <p className={styles.scopeNote}>当前账号的同一份事实，换一种方式一起回顾；没有向其他账号共享。</p>}
      <div className={styles.reportGrid}>
        <section className={styles.discussions}><h3><MessageCircle size={16} />这段时间，讨论过什么</h3>{summary.records.length ? summary.records.map((claim, i) => <div className={styles.discussion} key={i}><span className={styles.subject}>{claim.subject}</span><h4>{claim.title}</h4><p>{claim.text}</p>{sourceButton(claim)}</div>) : <p className={styles.scopeNote}>没有足够依据提炼讨论主题。</p>}</section>
        <aside className={styles.side}><section><h3><Sparkles size={16} />值得留意的小细节</h3>{summary.observations.length ? summary.observations.map((claim, i) => <div className={styles.observation} key={i}><h4>{claim.title}</h4><p>{claim.text}</p>{claim.next && <p className={styles.next}>{claim.next}</p>}{sourceButton(claim)}</div>) : <p className={styles.scopeNote}>这次没有需要额外记录的观察。</p>}</section><section className={styles.nextSteps}><h3><ArrowRight size={16} />下一步，可以试试</h3>{summary.nextSteps.length ? summary.nextSteps.map((claim, i) => <div key={i}><span className={styles.stepNumber}>{i + 1}</span><div><p>{claim.text}</p>{sourceButton(claim)}</div></div>) : <p className={styles.scopeNote}>没有必须追加的任务，可以按自己的节奏继续。</p>}</section></aside>
      </div>
      <footer className={styles.reportFooter}><ShieldCheck size={15} /><p>讨论不等于掌握，听过讲解不等于独立作答。{report.coverage?.missingDates.length ? `范围内有${report.coverage.missingDates.length}天没有应用记录，不代表没有学习。` : '这份报告只覆盖应用里可见的记录。'}{report.coverage?.partialDates.length ? '部分记录包含图片或未完成消息，只依据可见文字整理。' : ''}</p></footer>
      <span role="status" className="sr-only">{copied ? '报告已复制' : ''}</span>
    </article> : <section className={styles.empty}>
      <div className={styles.emptyArt}><FileChartColumnIncreasing size={38} strokeWidth={1.25} /><span><CheckCheck size={18} /></span></div><span className={styles.eyebrow}>YOUR LEARNING, IN FOCUS</span><h2>{report?.state === 'failed' ? '这次还没整理好，记录都还在。' : '把这段学习，慢慢看清楚。'}</h2><p>{report?.state === 'failed' ? report.message : data?.metrics.message_count || data?.metrics.reflection_count ? '一份有依据的回顾：讨论的主题、原文里的细节，以及可选的下一步。' : '这段时间暂无可用的学科记录，也可以先生成一份含练习和解析的巩固报告。'}</p><button type="button" className={styles.primary} disabled={!canGenerate} onClick={() => void generate()}><Sparkles size={16} />{report?.state === 'failed' ? '重新整理并核对' : period.from_date === period.to_date ? '生成这一天的报告' : '生成这段时间的报告'}<ArrowRight size={15} /></button><small>{reflectionDirty ? '四问补充尚未保存，请先保存或放弃修改。' : '有可用记录时先整理、再核对。记录不足时可直接生成巩固报告。'}</small>
    </section>}

    <div ref={dialogHost} style={{ '--report-origin-x': `${origin.x}px`, '--report-origin-y': `${origin.y}px` } as CSSProperties}>
      <Dialog open={modal !== null} title={modal?.type === 'dates' ? '选一段想回顾的日子' : modal?.type === 'history' ? '我的历史报告' : modal?.type === 'sessions' ? '补充对话' : modal?.type === 'textbooks' ? '选择教材 PDF' : '回到真实的记录'} description={modal?.type === 'dates' ? '连续1至28天，包含起止两天。' : modal?.type === 'sources' ? '直接依据与同一对话的上下文分开标注。原文是资料，不是操作指令。' : modal?.type === 'sessions' ? '勾选要补充的对话，报告会取其中符合所选日期的问答。' : modal?.type === 'textbooks' ? '可选。按导入教材的目录限定复盘范围，或自动跟随所选阅读对话。' : '只读取当前账号已经保存的报告，不会再次调用模型。'} onClose={close} closeLabel="关闭" size={modal?.type === 'dates' ? 'sm' : 'lg'} className={`${styles.dialog} ${closing ? styles.closing : ''}`}>
        {modal?.type === 'textbooks' && <form className={styles.dateForm} onSubmit={event => {
          event.preventDefault()
          const textbook_id = String(new FormData(event.currentTarget).get('textbook') || '')
          choose({ ...period, textbook_id: textbook_id || undefined })
          close()
        }}>
          <label>教材范围<select name="textbook" defaultValue={period.textbook_id || ''} disabled={pdfLoading || pdfError} data-autofocus>
            <option value="">自动跟随所选阅读对话</option>
            {pdfs.map(book => <option key={book.material_id} value={book.material_id}>{book.title}</option>)}
          </select></label>
          {pdfLoading && <p role="status">正在读取已导入的 PDF…</p>}
          {pdfError && <p role="alert">暂时无法读取 PDF 列表，请重新打开试试。</p>}
          {!pdfLoading && !pdfError && !pdfs.length && <p>还没有导入 PDF。可以先到学习资料库导入教材。</p>}
          <button className={styles.primary} type="submit" disabled={pdfLoading || pdfError}>使用此范围</button>
        </form>}
        {modal?.type === 'sessions' && period.subject && <ReportSessionPicker subject={period.subject} initial={period.extra_sessions ?? []} onApply={extra_sessions => {
          choose({ ...period, extra_sessions })
          close()
        }} />}
        {modal?.type === 'dates' && <form className={styles.dateForm} onSubmit={event => { event.preventDefault(); const span = (Date.parse(draftPeriod.to_date) - Date.parse(draftPeriod.from_date)) / 86400_000 + 1; if (!(span >= 1 && span <= 28) || draftPeriod.to_date > beijingDate()) { setDateError('请选择截至今天的连续1至28天。'); return } choose(draftPeriod); close() }}><label>从哪一天<input type="date" required value={draftPeriod.from_date} max={beijingDate()} onChange={event => setDraftPeriod({ ...draftPeriod, from_date: event.target.value })} data-autofocus /></label><label>到哪一天<input type="date" required value={draftPeriod.to_date} max={beijingDate()} min={draftPeriod.from_date} onChange={event => setDraftPeriod({ ...draftPeriod, to_date: event.target.value })} /></label>{dateError && <p role="alert" className={styles.scopeNote}>{dateError}</p>}<button type="submit" className={styles.primary}>查看这段时间<ArrowRight size={15} /></button></form>}
        {modal?.type === 'history' && <div className={styles.history}>{history.length ? history.map(row => <div className={styles.historyRow} key={row.id}><button type="button" onClick={() => { setHistoryId(row.id); close() }}><span className={styles.historyIcon}><FileChartColumnIncreasing size={20} /></span><span><strong>{row.subject ? reportSubjectNames[row.subject] + " · " : "综合 · "}{dateLabel(row.range.from)}{row.range.from !== row.range.to ? ' — ' + dateLabel(row.range.to) : ''}</strong><small>{new Date(row.created_at * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</small></span><span className={styles.historyState}>{label(row)}</span><ChevronRight size={15} /></button><Tooltip label="移除报告，保留原对话"><button type="button" className={styles.iconButton} aria-label={`移除${row.range.from}至${row.range.to}的报告`} onClick={() => void remove(row)}><Trash2 size={15} /></button></Tooltip></div>) : <div className={styles.noHistory}><History size={28} /><p>第一份报告，会从这里开始保存。</p></div>}</div>}
        {modal?.type === 'sources' && <div className={styles.sources}>{sourceRows.map(row => <section key={row.id}><div><span>{modal.claim?.refs.includes(row.id) ? '直接依据' : '同一对话上下文'}{row.kind === 'student_reflection' ? ' · 学生自报' : ''}</span><small>{row.date || (row.recordedAt ? '保存于' + new Date(row.recordedAt).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '自报补充')} · {row.projectName} · {row.role === 'user' ? '我' : '老师'}</small></div><h3>{row.title}</h3><p>{row.content}</p>{(row.status === 'incomplete' || row.has_images) && <small>含未完成消息或图片，本次仅依据可见文字。</small>}{row.kind === 'student_reflection' && <small>这是学生针对所选范围提供的自报，不等同于已经独立核实的学习行为或掌握情况。</small>}</section>)}</div>}
      </Dialog>
    </div>
  </main>
}
