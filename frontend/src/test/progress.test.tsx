import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ProgressView, ScoreLine } from '../components/ProgressPage'
import { ScenarioPicker } from '../components/ScenarioPicker'
import { DebriefTab } from '../dock/DebriefTab'
import { OfficeModel } from '../model'
import {
  EXPORT_URL, TREND, canClear, formatAverage, formatDate, linePath, linePoints, reportUrl, resetStep,
  type Progress, type ProgressScenario, type ResetState,
} from '../progress'
import type { DebriefReport, ScenarioInfo } from '../scenario'

const attempt = (n: number, total: number, scores: Record<string, number>, elapsed: number, date: string, project = `p-${n}`) => ({ attempt: n, total, max: 100, scores, date, elapsed, project })

const ONE: ProgressScenario = {
  id: 'opd-bookings-down', title: 'Production incident: Bookings are down', minutes: 25, max: 100, count: 3, best_score: 95, best_time: 192, last_total: 95,
  attempts: [
    attempt(1, 60, { communication: 2, diagnosis: 2, fix_quality: 3, testing: 1, ownership: 2 }, 1289.5, '2026-10-12T20:24:28'),
    attempt(2, 85, { communication: 3, diagnosis: 3, fix_quality: 4, testing: 3, ownership: 3 }, 437.6, '2026-10-12T21:38:15'),
    attempt(3, 95, { communication: 4, diagnosis: 3, fix_quality: 4, testing: 4, ownership: 4 }, 192, '2026-10-12T22:37:24'),
  ],
}
const TWO: ProgressScenario = {
  id: 'opd-double-bookings', title: 'Double bookings', minutes: 30, max: 100, count: 1, best_score: 55, best_time: 128, last_total: 55,
  attempts: [attempt(1, 55, { communication: 1, diagnosis: 3, fix_quality: 3, testing: 2, ownership: 2 }, 128, '2026-10-15T19:07:17')],
}
const THREE: ProgressScenario = { id: 'opd-form-says-saved', title: 'The form says it saved', minutes: 25, max: 100, count: 0, best_score: null, best_time: null, last_total: null, attempts: [] }

const QUOTE = 'Update: the API refuses correctly (409/400/404 with a message), but call() only throws when there is no JSON body'

const DATA: Progress = {
  version: 1, generated_at: '2026-10-16T16:00:00', empty: false, attempts_total: 4, scenarios: [ONE, TWO, THREE],
  skills: [
    { id: 'communication', name: 'Communication', max: 4, count: 4, latest: 1, average: 2.5, trend: 'down' },
    { id: 'diagnosis', name: 'Diagnosis', max: 4, count: 4, latest: 3, average: 2.75, trend: 'up' },
    { id: 'fix_quality', name: 'Fix quality', max: 4, count: 4, latest: 3, average: 3.5, trend: 'steady' },
    { id: 'testing', name: 'Testing', max: 4, count: 4, latest: 2, average: 2.5, trend: 'steady' },
    { id: 'ownership', name: 'Ownership', max: 4, count: 4, latest: 2, average: 2.75, trend: 'new' },
  ],
  weakest: {
    skill: 'communication', name: 'Communication', average: 2.5, latest: 1, max: 4, reason: '',
    gap: { scenario: 'opd-double-bookings', title: 'Double bookings', attempt: 1, row: 'R02', t: 315.9, clock: '05:15', source: '#incident-duplicates · You', quote: QUOTE, note: 'Your first update came at 05:15, later than the 2 minutes asked.', advice: 'Post a first update within two minutes.' },
  },
  next_step: { kind: 'retry', scenario: 'opd-double-bookings', title: 'Double bookings', skill: 'communication', reason: 'Retry Double bookings: your last attempt there scored 1/4 on Communication, the lowest of your latest attempts, and Communication is your weakest skill (average 2.5/4).' },
}
const EMPTY: Progress = { ...DATA, empty: true, attempts_total: 0, scenarios: [{ ...ONE, attempts: [], count: 0, best_score: null, best_time: null, last_total: null }, { ...TWO, attempts: [], count: 0, best_score: null, best_time: null, last_total: null }, THREE],
  skills: DATA.skills.map((k) => ({ ...k, latest: null, average: null, count: 0, trend: 'none' as const })), weakest: null, next_step: null }

const noop = () => {}
const view = (data: Progress, reset: ResetState = 'idle', busy = false) => renderToStaticMarkup(<ProgressView data={data} reset={reset} busy={busy} onReset={noop} onStart={noop} onOpenReport={noop} />)

describe('progress helpers', () => {
  it('formats the stored local timestamp and leaves anything else alone', () => {
    expect(formatDate('2026-10-12T20:24:28')).toBe('12 Oct 2026, 20:24')
    expect(formatDate('2026-01-05T07:03:00')).toBe('5 Jan 2026, 07:03')
    expect(formatDate('yesterday')).toBe('yesterday')
  })
  it('shows an average with one decimal at most', () => {
    expect([formatAverage(3.14), formatAverage(4), formatAverage(2.5), formatAverage(0), formatAverage(null)]).toEqual(['3.1', '4', '2.5', '0', '–'])
  })
  it('puts a single attempt in the middle and the first and last at the edges', () => {
    expect(linePoints([50], 100, 100, 50, 10)).toEqual([{ x: 50, y: 25 }])
    const p = linePoints([0, 100, 50], 100, 100, 50, 10)
    expect(p[0]).toEqual({ x: 10, y: 40 }) // 0 is the bottom
    expect(p[1]).toEqual({ x: 50, y: 10 }) // full marks the top
    expect(p[2]).toEqual({ x: 90, y: 25 })
    expect(linePoints([150, -5], 100, 100, 50, 10).map((q) => q.y)).toEqual([10, 40]) // clamped
  })
  it('draws the line as one path', () => {
    expect(linePath([{ x: 1, y: 2 }, { x: 3.04, y: 4 }])).toBe('M1.0 2.0 L3.0 4.0')
    expect(linePath([])).toBe('')
  })
  it('names every trend', () => {
    expect(Object.keys(TREND).sort()).toEqual(['down', 'new', 'none', 'steady', 'up'])
    expect(TREND.up.glyph).not.toBe(TREND.down.glyph)
  })
  it('only lets a reset through the confirmation', () => {
    expect(canClear('idle')).toBe(false)
    expect(resetStep('idle', 'confirm')).toBe('idle') // confirming without asking does nothing
    const asked = resetStep('idle', 'ask')
    expect(asked).toBe('confirm')
    expect(canClear(asked)).toBe(true)
    expect(resetStep(asked, 'cancel')).toBe('idle')
    const busy = resetStep(asked, 'confirm')
    expect(busy).toBe('busy')
    expect(canClear(busy)).toBe(false)
    expect(resetStep(busy, 'cancel')).toBe('busy') // not while the request is going
    expect(resetStep(busy, 'done')).toBe('idle')
  })
  it('has stable urls', () => {
    expect(EXPORT_URL('md')).toBe('/api/progress/export?format=md')
    expect(EXPORT_URL('json')).toBe('/api/progress/export?format=json')
    expect(reportUrl('opd-bookings-down', 3)).toBe('/api/progress/report/opd-bookings-down/3?format=json')
    expect(reportUrl('a b', 1, 'md')).toBe('/api/progress/report/a%20b/1?format=md')
  })
})

describe('the My progress page', () => {
  const html = view(DATA)
  it('shows the summary and a card for every scenario, with best score and best time', () => {
    expect(html).toContain('Real attempts')
    expect(html).toContain('2 of 3') // two scenarios have attempts
    expect(html).toContain('Production incident: Bookings are down')
    expect(html).toContain('Best score')
    expect(html).toContain('95/100')
    expect(html).toContain('03:12') // 192 s
    expect(html).toContain('Not attempted yet.')
  })
  it('lists each attempt with its score, date and time', () => {
    expect(html).toContain('12 Oct 2026, 20:24')
    expect(html).toContain('60/100')
    expect(html).toContain('21:29') // 1289.5 s
    expect(html).toContain('15 Oct 2026, 19:07')
  })
  it('draws the score line as an svg with one dot per attempt', () => {
    const svg = renderToStaticMarkup(<ScoreLine scenario={ONE} />)
    expect(svg).toContain('<svg')
    expect(svg).toContain('Score over attempts: 60, 85, 95')
    expect((svg.match(/<circle/g) ?? []).length).toBe(3)
    expect(svg).toContain('<path')
    expect(renderToStaticMarkup(<ScoreLine scenario={TWO} />)).not.toContain('<path') // one point has no line
  })
  it('shows the five skills with latest, average and trend, and marks the weakest', () => {
    for (const n of ['Communication', 'Diagnosis', 'Fix quality', 'Testing', 'Ownership']) expect(html).toContain(n)
    expect(html).toContain('Communication: latest 1, average 2.5, slipping')
    expect(html).toContain('Diagnosis: latest 3, average 2.8, improving')
    expect(html).toContain('weakest')
  })
  it('quotes the gap of the weakest skill as the report has it, with its timestamp, and opens that report', () => {
    expect(html).toContain('Weakest skill')
    expect(html).toContain('05:15')
    expect(html).toContain(QUOTE.replace(/&/g, '&amp;'))
    expect(html).toContain('Your first update came at 05:15, later than the 2 minutes asked.')
    expect(html).toContain('Open the report of Double bookings, attempt 1')
  })
  it('says why in one sentence and offers to start that scenario', () => {
    expect(html).toContain('Retry Double bookings: your last attempt there scored 1/4 on Communication')
    expect(html).toContain('Try it again')
    expect(view({ ...DATA, next_step: { ...DATA.next_step!, kind: 'new' } })).toContain('Start this scenario')
    expect(view(DATA, 'idle', true)).toContain('Starting…')
  })
  it('explains a weakest skill without a quote and a clean slate', () => {
    expect(view({ ...DATA, weakest: { ...DATA.weakest!, gap: null, reason: 'No saved report with a Communication gap was found.' } })).toContain('No saved report with a Communication gap was found.')
    expect(view({ ...DATA, weakest: null })).toContain('every attempt scored full marks')
  })
  it('offers the two downloads and a reset that asks first', () => {
    expect(html).toContain('Download my progress')
    expect(html).toContain('href="/api/progress/export?format=md"')
    expect(html).toContain('href="/api/progress/export?format=json"')
    expect(html).toContain('Reset progress')
    expect(html).not.toContain('Confirm reset')
    const asking = view(DATA, 'confirm')
    expect(asking).toContain('Confirm reset')
    expect(asking).toContain('Demo runs and recordings are not touched')
    expect(asking).toContain('Yes, clear it')
    expect(asking).not.toContain('>Reset progress<')
    expect(view(DATA, 'busy')).toContain('Clearing…')
  })
})

describe('the empty state', () => {
  const html = view(EMPTY)
  it('says no real attempts exist yet and what counts', () => {
    expect(html).toContain('No attempts yet')
    expect(html).toContain('never count here')
  })
  it('lists the scenarios to try and offers no export or reset', () => {
    expect(html).toContain('Double bookings')
    expect(html).toContain('The form says it saved')
    expect(html).not.toContain('Download my progress')
    expect(html).not.toContain('Reset progress')
    expect(html).not.toContain('Skills across all scenarios')
  })
})

const CARD: ScenarioInfo = { id: 'opd-bookings-down', title: 'Production incident', summary: 's', role: 'backend', level: 'Intermediate', minutes: 25, channel: '#incident-opd' } as ScenarioInfo

describe('the entry point', () => {
  it('puts My progress next to the scenario picker', () => {
    const h = renderToStaticMarkup(<ScenarioPicker scenarios={[CARD]} busy={false} onStart={noop} onProgress={noop} />)
    expect(h).toContain('My progress')
    expect(renderToStaticMarkup(<ScenarioPicker scenarios={[CARD]} busy={false} onStart={noop} />)).not.toContain('My progress')
  })
})

describe('a saved report opened from the page', () => {
  const report = {
    version: 1, scenario: 'opd-double-bookings', title: 'Double bookings', project: 'p', attempt: 1, kind: 'learner', total: 55, max: 100, elapsed: 128, minutes: 30, rubric: { id: 'r', version: 1 },
    criteria: [{ id: 'communication', name: 'Communication', judge: 'architect', judge_name: 'Aarav', score: 1, max: 4, descriptor: 'd', summary: 's', keep: 'k', rows: [] }], rows: [], events: {},
    fairness: { points: 0, quoted: 0, matched: 0, dropped: [], ai_rejected: [], tests_rerun: null, rubric: 'v1', voices: { judges: 'template', coach: 'template', reason: '' } }, focus: ['Post sooner.'],
    coach: { text: 'You scored 55.', source: 'template' }, judge_lines: {}, attempts: [{ attempt: 1, total: 55, scores: {}, project: 'p', finished_at: '2026-10-15T19:07:17', elapsed: 128 }], files: { md: 'a.md', json: 'a.json' },
  } as unknown as DebriefReport
  const model = () => {
    const m = new OfficeModel()
    m.debrief = { phase: 'done', attempt: 1, judges: [], report }
    return m
  }
  it('has no Try again, and links the saved report file', () => {
    const h = renderToStaticMarkup(<DebriefTab model={model()} projectId={null} onTryAgain={noop} readOnly reportLink={reportUrl('opd-double-bookings', 1, 'md')} />)
    expect(h).toContain('Debrief: Double bookings')
    expect(h).not.toContain('Try again')
    expect(h).toContain('href="/api/progress/report/opd-double-bookings/1?format=md"')
  })
  it('keeps Try again in the live Debrief tab', () => {
    expect(renderToStaticMarkup(<DebriefTab model={model()} projectId="abc" onTryAgain={noop} />)).toContain('Try again')
  })
})
