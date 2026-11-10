import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import LearningReports from '@/components/student/LearningReports'
import { beijingDate, presetPeriod, learningOnly, reportMarkdown, reportSubjectNames, type LearningReport } from '@/lib/student-reports'

const api = vi.hoisted(() => ({ get: vi.fn(), generate: vi.fn(), detail: vi.fn(), reflection: vi.fn(), history: vi.fn(), materials: vi.fn() }))
vi.mock('@/lib/student-reports', async original => ({ ...await original<typeof import('@/lib/student-reports')>(), getReports: api.get, generateReport: api.generate, getReport: api.detail, saveReflection: api.reflection, getReportHistory: api.history }))

vi.mock('@/lib/reading-api', () => ({ listMaterials: api.materials }))

const claim = { text: '学生请求解释通分，老师展示了一个例子。', title: '异分母分数加法', subject: '数学', refs: ['u1'], contextRefs: ['u1', 'a1'] }
const report: LearningReport = {
  id: 'own-report', range: { from: '2024-02-28', to: '2024-02-29' }, created_at: 1709180000, state: 'ready', stage: null, message: '已核对', stale: false,
  metrics: { message_count: 2, conversation_count: 1, active_days: 1, minutes: null, exercise_count: null, accuracy: null },
  summary: { overview: claim, records: [claim], observations: [], nextSteps: [] },
  evidence: [{ id: 'u1', role: 'user', content: '请解释为什么要通分。', date: '2024-02-28', projectName: '数学', title: '原对话', status: 'complete', has_images: false }, { id: 'a1', role: 'assistant', content: '老师讲解，不代表学生已经独立作答。', date: '2024-02-28', projectName: '数学', title: '原对话', status: 'complete', has_images: false }],
  coverage: { factDates: ['2024-02-28'], missingDates: ['2024-02-29'], partialDates: [] },
}

beforeEach(() => {
  api.get.mockResolvedValue({ range: report.range, metrics: report.metrics, report, history: [report], coverage: report.coverage })
  api.detail.mockResolvedValue(report)
  api.history.mockResolvedValue([])
  api.materials.mockResolvedValue([])
  api.reflection.mockResolvedValue({ revision: 1, answers: { goal: '理解分数', state: '', process: '', adjustment: '' }, saved_at: 1709180000 })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('uses Beijing dates at UTC boundaries and includes leap days', () => {
  expect(beijingDate(new Date('2024-02-28T16:00:00Z'))).toBe('2024-02-29')
  expect(presetPeriod(2, new Date('2024-02-29T15:59:59Z'))).toEqual({ from_date: '2024-02-28', to_date: '2024-02-29' })
  expect(presetPeriod(1, new Date('2024-03-01T02:00:00Z'), true)).toEqual({ from_date: '2024-02-29', to_date: '2024-02-29' })
})

it('changes the reading perspective without new model or data requests', async () => {
  render(<LearningReports />)
  fireEvent.click(screen.getByRole('button', { name: /数学复盘/ }))
  await screen.findByRole('heading', { name: '我的学习回顾' })
  const reads = api.get.mock.calls.length
  fireEvent.click(screen.getByRole('button', { name: '家长' }))
  expect(screen.getByRole('heading', { name: '孩子的学习近况' })).toBeTruthy()
  expect(api.get).toHaveBeenCalledTimes(reads)
  expect(api.generate).not.toHaveBeenCalled()
  expect(reportMarkdown(report, false)).toContain(claim.text)
  expect(reportMarkdown(report, true)).toContain(claim.text)
  expect(reportMarkdown(report, true)).toContain('未记录')
})

it('shows original direct evidence separately from conversation context', async () => {
  render(<LearningReports />)
  fireEvent.click(screen.getByRole('button', { name: /数学复盘/ }))
  await screen.findByRole('heading', { name: '我的学习回顾' })
  fireEvent.click(screen.getAllByRole('button', { name: '查看依据' })[0])
  const dialog = await screen.findByRole('dialog', { name: '回到真实的记录' })
  expect(dialog.textContent).toContain('直接依据')
  expect(dialog.textContent).toContain('同一对话上下文')
  expect(dialog.textContent).toContain('请解释为什么要通分。')
  expect(dialog.textContent).toContain('老师讲解，不代表学生已经独立作答。')
  expect(api.generate).not.toHaveBeenCalled()
})

it('hides a previously read report when its evidence cannot be checked on return', async () => {
  render(<LearningReports />)
  fireEvent.click(screen.getByRole('button', { name: /数学复盘/ }))
  await screen.findByRole('heading', { name: '我的学习回顾' })
  api.get.mockRejectedValueOnce(new Error('原始记录已更改，请重新读取。'))
  fireEvent(window, new Event('focus'))
  await screen.findByRole('alert')
  expect(screen.queryByRole('heading', { name: '我的学习回顾' })).toBeNull()
  expect(screen.getByRole('alert').textContent).toContain('原始记录已更改')
  expect(api.generate).not.toHaveBeenCalled()
})

it('does not create a report or invent zero learning time for an empty range', async () => {
  api.get.mockResolvedValue({ range: report.range, metrics: { ...report.metrics, message_count: 0, conversation_count: 0, active_days: 0 }, report: null, history: [], coverage: report.coverage })
  render(<LearningReports />)
  fireEvent.click(screen.getByRole('button', { name: /数学复盘/ }))
  const button = await screen.findByRole('button', { name: '生成这段时间的报告' })
  expect(button.hasAttribute('disabled')).toBe(false)
  expect(screen.getByText('未记录')).toBeTruthy()
  expect(api.generate).not.toHaveBeenCalled()
})

it('keeps date validation visible inside its dialog', async () => {
  render(<LearningReports />)
  fireEvent.click(screen.getByRole('button', { name: /数学复盘/ }))
  await screen.findByRole('heading', { name: '我的学习回顾' })
  fireEvent.click(screen.getByRole('button', { name: /\d{4}\.\d{2}\.\d{2}/ }))
  fireEvent.change(screen.getByLabelText('从哪一天'), { target: { value: '2024-01-01' } })
  fireEvent.change(screen.getByLabelText('到哪一天'), { target: { value: '2024-02-29' } })
  fireEvent.submit(screen.getByRole('button', { name: '查看这段时间' }).closest('form')!)
  expect(screen.getByRole('dialog').textContent).toContain('请选择截至今天的连续1至28天')
  expect(api.generate).not.toHaveBeenCalled()
})

it('keeps four reflections collapsed, preserves unsaved input and saves without generation', async () => {
  render(<LearningReports />)
  fireEvent.click(screen.getByRole('button', { name: /数学复盘/ }))
  await screen.findByRole('heading', { name: '我的学习回顾' })
  const toggle = screen.getByText('补充四问复盘').closest('details')!
  expect(toggle.hasAttribute('open')).toBe(false)
  fireEvent.click(toggle.querySelector('summary')!)
  fireEvent.change(screen.getByLabelText('目标管理'), { target: { value: '理解分数' } })
  fireEvent.click(screen.getByRole('button', { name: '今天' }))
  expect((screen.getByLabelText('目标管理') as HTMLTextAreaElement).value).toBe('理解分数')
  expect(api.generate).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '保存补充' }))
  await waitFor(() => expect(api.reflection).toHaveBeenCalledTimes(1))
  expect(api.generate).not.toHaveBeenCalled()
})

it('offers nine subjects and keeps PDF scope and evidence behind page two', async () => {
  const history: LearningReport = {
    ...report, subject: 'history', summary: null,
    textbook_scope: [{ title: '本机历史教材', matched: true, pages: [14], outline: [{title: '辛亥革命', page: 12}] }],
    subject_review: {
      title: '历史学习复盘',
      cover: '资料范围：历史教材第 12 页。',
      learningSummary: ['按时间线梳理辛亥革命。', '背景、经过、影响分开记。', '做一道材料题。'],
      sections: Array.from({length: 7}, (_, i) => ({ ...claim, title: i === 1 ? '记忆大纲' : '章节 '+i, text: '学习重点 [m1]（M2）' })),
      exercises: [{ id: 1, question: '怎样说明材料和结论的关系？', answer: '引用材料中的细节。', explanation: '先引用，再解释。', options: [] }],
    },
  }
  api.get.mockResolvedValue({range: history.range, metrics: history.metrics, report: history, history: [], coverage: history.coverage})
  api.materials.mockResolvedValue([{material_id: 'aabbccddeeff1122', title: '本机历史教材', render_mode: 'pdf'}])
  render(<LearningReports />)
  for (const subject of Object.values(reportSubjectNames)) expect(screen.getByRole('button', {name: new RegExp(subject+'复盘')})).toBeTruthy()
  fireEvent.click(screen.getByRole('button', {name: /历史复盘/}))
  await screen.findByRole('heading', {name: '记忆大纲'})
  expect(screen.getByText('按时间线梳理辛亥革命。')).toBeTruthy()
  expect(screen.queryByText(/资料范围：历史教材/)).toBeNull()
  expect(screen.queryByText(/\[m1\]|（M2）/)).toBeNull()
  fireEvent.click(screen.getByRole('button', {name: '2. 教材与记录依据'}))
  expect(screen.getByText('辛亥革命 · PDF 第 12 页')).toBeTruthy()
  expect(screen.getByText('请解释为什么要通分。')).toBeTruthy()
  expect(screen.queryByRole('heading', {name: '记忆大纲'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name: '选择教材 PDF'}))
  await screen.findByRole('option', {name: '本机历史教材'})
  fireEvent.change(screen.getByRole('combobox', {name: '教材范围'}), {target: {value:'aabbccddeeff1122'}})
  fireEvent.click(screen.getByRole('button', {name: '使用此范围'}))
  await waitFor(() => expect(api.get.mock.lastCall?.[0].textbook_id).toBe('aabbccddeeff1122'))
  expect(learningOnly('式子 $m1+n$，说明 [m1]。')).toBe('式子 $m1+n$，说明 。')
})
