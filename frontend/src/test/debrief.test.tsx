import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Dock } from '../components/Dock'
import { DebriefTab } from '../dock/DebriefTab'
import { OfficeModel, type AgentInfo, type QEvent, type Visual } from '../model'
import { deltaLabel, eventDetail, previousAttempt, rowsOf, scoreColor, type DebriefReport, type ReportRow } from '../scenario'

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['database', 'Karan'], ['qa', 'Ananya'], ['reviewer', 'Vikram']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))

let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

const row = (id: string, criterion: string, kind: 'strength' | 'gap', event: string, t: number, quote: string, note: string, advice = '', source = '#incident-opd'): ReportRow => ({
  id, criterion, rule: id, kind, event, events: [event], t, source, quote, note, advice, verified: true, worded_by: 'template',
})

const CRITERIA = [['communication', 'Communication', 'architect', 'Aarav', 3], ['diagnosis', 'Diagnosis', 'database', 'Karan', 4], ['fix_quality', 'Fix quality', 'reviewer', 'Vikram', 3],
  ['testing', 'Testing', 'qa', 'Ananya', 2], ['ownership', 'Ownership', 'architect', 'Aarav', 4]] as const

function report(over: Partial<DebriefReport> = {}): DebriefReport {
  return {
    version: 1, scenario: 'opd-bookings-down', title: 'Production incident: Bookings are down', project: 'opd-bookings-down-2', attempt: 2, total: 80, max: 100, elapsed: 1120, minutes: 25,
    rubric: { id: 'opd-bookings-down-v1', version: 1 },
    criteria: CRITERIA.map(([id, name, judge, judge_name, score]) => ({ id, name, judge, judge_name, score, max: 4, descriptor: `what ${score} means`, keep: 'Keep going.', rows: [] })),
    rows: [
      row('R01', 'communication', 'strength', 'E004', 100, 'Update: bookings fail since the deploy', 'First update at 01:40, inside the first 02:00.'),
      row('R02', 'communication', 'gap', 'E012', 410, "It's been 5 min since your last update", 'The lead had to nudge you 1 time.', 'Set a timer for each promised update.'),
      row('R03', 'diagnosis', 'strength', 'E006', 175, 'database/migrations/0007_rename_slot_time_to_slot_at.sql', 'You opened the migration before the first edit.', '', 'IDE · file opened'),
      row('R04', 'testing', 'gap', 'E021', 878, 'Submit for review', 'No new test covers the bug you fixed.', 'Add a regression test in tests/regression/ for the bug you fixed.', 'Submit'),
    ],
    events: {
      E004: { id: 'E004', t: 100, kind: 'message_posted', message: 'C002', text: 'Update: bookings fail since the deploy', to: [] },
      E012: { id: 'E012', t: 410, kind: 'team_message', message: 'C007', from: 'architect', text: "It's been 5 min since your last update", source: 'scripted', ref: 'lead-nudge' },
      E006: { id: 'E006', t: 175, kind: 'file_opened', role: 'backend', path: 'database/migrations/0007_rename_slot_time_to_slot_at.sql' },
      E021: { id: 'E021', t: 878, kind: 'submit', task: 'h1' },
    },
    fairness: { points: 9, quoted: 9, matched: 9, dropped: [{ finding: 'F05', text: 'You never ran the tests.', reason: 'event E999 is not in the session log' }], tests_rerun: { ok: true, passed: 97, total: 97 }, rubric: 'v1',
                wording: { source: 'model', reason: '', model_points: 9 } },
    focus: ['Add a regression test with every bug fix.', 'Search the whole codebase for a renamed name.', 'Send updates on the time you promised.'],
    attempts: [{ attempt: 1, total: 60, scores: {}, project: 'opd-bookings-down', finished_at: '2026-10-12T09:00:00', elapsed: 900 }, { attempt: 2, total: 80, scores: {}, project: 'opd-bookings-down-2', finished_at: '2026-10-12T10:00:00', elapsed: 1120 }],
    files: { md: '.q/reports/attempt-2.md', json: '.q/reports/attempt-2.json' },
    ...over,
  }
}

function model() {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  m.apply(ev('scenario_started', { scenario: 'opd-bookings-down', title: 'Production incident: Bookings are down', role: 'backend', minutes: 25, channel: { id: 'incident-opd', name: '#incident-opd' }, teammates: ['qa', 'architect', 'database', 'planner'], started_at: 1000, attempt: 2 }))
  return m
}

describe('the debrief in the model', () => {
  it('starts the meeting, keeps the report and ends the meeting', () => {
    const m = model()
    const visuals: Visual[] = []
    m.onVisual((v) => visuals.push(v))
    expect(m.scenario?.attempt).toBe(2)
    m.apply(ev('debrief_started', { attempt: 2, rubric: { id: 'opd-bookings-down-v1', version: 1 }, judges: [{ id: 'architect', name: 'Aarav', criterion: 'communication' }] }))
    expect(m.debrief).toMatchObject({ phase: 'meeting', attempt: 2, report: null }); expect(m.debrief?.judges).toHaveLength(1)
    expect(visuals).toContainEqual({ kind: 'meeting', on: true }); expect(m.ticker).toContain('meeting room')
    m.apply(ev('debrief_report', { report: report() }))
    expect(m.debrief?.phase).toBe('done'); expect(m.debrief?.report?.total).toBe(80); expect(m.ticker).toContain('Report ready: 80/100'); expect(m.ticker).toContain('.q/reports/attempt-2.md')
    expect(visuals.some((v) => v.kind === 'toast' && v.title === 'Debrief report ready' && v.text.includes('80/100'))).toBe(true)
    m.apply(ev('debrief_ended', { ok: true }))
    expect(visuals.filter((v) => v.kind === 'meeting')).toEqual([{ kind: 'meeting', on: true }, { kind: 'meeting', on: false }])
    expect(m.debrief?.phase).toBe('done')
  })

  it('marks a debrief that ended without a report as failed, and forgets everything on reset', () => {
    const m = model()
    m.apply(ev('debrief_started', { attempt: 1, judges: [] }))
    m.apply(ev('debrief_failed', { reason: 'RuntimeError: x' }))
    m.apply(ev('debrief_ended', { ok: false }))
    expect(m.debrief?.phase).toBe('failed')
    m.reset()
    expect(m.debrief).toBeNull()
  })

  it('a debrief post is a speech bubble with its short text, not a toast', () => {
    const m = model()
    const visuals: Visual[] = []
    m.onVisual((v) => visuals.push(v))
    m.apply(ev('channel_message', { id: 'C020', channel: 'incident-opd', from: 'qa', text: 'Testing 2/4. At 14:38: “Submit for review” No new test covers the bug you fixed. Tip: Add a regression test.', source: 'debrief', t: 900, bubble: 'Testing 2/4. Add a regression test.', debrief: true }))
    expect(m.channel[0]).toMatchObject({ source: 'debrief', bubble: 'Testing 2/4. Add a regression test.' })
    expect(visuals).toEqual([{ kind: 'say', agent: 'qa', text: 'Testing 2/4. Add a regression test.', tone: 'good' }])
  })
})

describe('the numbers of a report', () => {
  it('says how much better or worse than the attempt before', () => {
    expect(deltaLabel(report())).toBe('+20 vs attempt 1')
    expect(deltaLabel(report({ total: 55 }))).toBe('−5 vs attempt 1')
    expect(deltaLabel(report({ total: 60 }))).toBe('±0 vs attempt 1')
    expect(deltaLabel(report({ attempt: 1, attempts: [report().attempts[0]] }))).toBe('')
    expect(previousAttempt(report())?.attempt).toBe(1)
  })

  it('colours a bar by how much of the score it is', () => {
    expect(scoreColor(4, 4)).toBe('var(--good)')
    expect(scoreColor(2, 4)).toBe('var(--warn)')
    expect(scoreColor(0, 4)).toBe('var(--bad)')
    expect(scoreColor(1, 4)).not.toBe(scoreColor(3, 4))
  })

  it('lists the rows of a criterion and the detail of a quoted entry', () => {
    const r = report()
    expect(rowsOf(r, 'communication').map((x) => x.id)).toEqual(['R01', 'R02'])
    expect(eventDetail(r, 'E012')).toEqual([['Entry', 'E012'], ['Time', '06:50'], ['Kind', 'team message'], ['message', 'C007'], ['from', 'architect'], ['text', "It's been 5 min since your last update"], ['source', 'scripted'], ['ref', 'lead-nudge']])
    expect(eventDetail(r, 'E021')).toEqual([['Entry', 'E021'], ['Time', '14:38'], ['Kind', 'submit'], ['task', 'h1']])
    expect(eventDetail(r, 'E999')).toEqual([])
  })
})

describe('the Debrief tab', () => {
  const withReport = (r = report()) => {
    const m = model()
    m.apply(ev('debrief_started', { attempt: r.attempt, judges: [] }))
    m.apply(ev('debrief_report', { report: r }))
    return m
  }
  const render = (m: OfficeModel, extra: Partial<Parameters<typeof DebriefTab>[0]> = {}) => renderToStaticMarkup(<DebriefTab model={m} projectId="p1" onTryAgain={() => {}} {...extra} />)

  it('shows the total, the delta, the attempt and a bar and judge for every criterion', () => {
    const html = render(withReport())
    expect(html).toContain('aria-label="Total 80 out of 100"'); expect(html).toContain('/100'); expect(html).toContain('+20 vs attempt 1'); expect(html).toContain('attempt 2 · 18 min 40 s on the clock')
    for (const [, name, , judge, score] of CRITERIA) {
      expect(html).toContain(`aria-label="${name} ${score} of 4"`)
      expect(html).toContain(judge)
    }
    expect(html.match(/h-\[6px\] flex-1 rounded-full/g)?.length).toBe(20)
    expect(html).toContain('Rubric (0 to 4 each)')
  })

  it('shows the attempt history with the scores of every attempt', () => {
    const html = render(withReport())
    expect(html).toContain('aria-label="Attempt history"'); expect(html).toContain('#1 · 60'); expect(html).toContain('#2 · 80'); expect(html).toContain('Same rubric every attempt')
  })

  it('lists the evidence: strength or gap, timestamp, source, quote, note, tip and verified', () => {
    const html = render(withReport())
    expect(html).toContain('Debrief: Production incident: Bookings are down'); expect(html).toContain('every point quotes a timestamped moment from your session'); expect(html).toContain('.q/reports/attempt-2.md')
    expect(html).toContain('>strength<'); expect(html).toContain('>gap<'); expect(html).toContain('▸ 01:40'); expect(html).toContain('▸ 06:50'); expect(html).toContain('#incident-opd'); expect(html).toContain('IDE · file opened')
    expect(html).toContain('“Update: bookings fail since the deploy”'); expect(html).toContain('First update at 01:40, inside the first 02:00.')
    expect(html).toContain('Next attempt: Set a timer for each promised update.'); expect(html).toContain('Next attempt: Add a regression test in tests/regression/ for the bug you fixed.')
    expect(html.match(/✓ verified/g)?.length).toBe(4)
    expect(html).not.toContain('aria-label="Log entry') // an entry is open only after a click on its timestamp
  })

  it('opens the entry that a timestamp points at', () => {
    const html = render(withReport(), { initiallyOpen: 'R02' })
    expect(html).toContain('aria-label="Log entry E012"'); expect(html).toContain('team message'); expect(html).toContain('lead-nudge'); expect(html).toContain('aria-expanded="true"')
    expect(html.match(/aria-label="Log entry/g)?.length).toBe(1)
  })

  it('shows the fairness checks, what was dropped and the focus for the next attempt', () => {
    const html = render(withReport())
    expect(html).toContain('Fairness checks'); expect(html).toContain('Every point quotes a moment'); expect(html).toContain('Quotes matched to the event log'); expect(html).toContain('9/9'); expect(html).toContain('Unbacked claim dropped')
    expect(html).toContain('Tests re-run, not guessed'); expect(html).toContain('97/97'); expect(html).toContain('Same rubric for every attempt'); expect(html).toContain('v1')
    expect(html).toContain('Dropped:'); expect(html).toContain('You never ran the tests.'); expect(html).toContain('event E999 is not in the session log')
    expect(html).toContain('Focus for your next attempt'); expect(html).toContain('Add a regression test with every bug fix.'); expect(html).toContain('Send updates on the time you promised.')
  })

  it('has a Try again button for the next attempt and a link to the report file', () => {
    const html = render(withReport())
    expect(html).toMatch(/<button[^>]*>↻ Try again \(attempt 3\)</)
    expect(html).toContain('href="/api/projects/p1/report?format=md"'); expect(html).toContain('Open report file')
    expect(render(withReport(), { busy: true })).toMatch(/<button[^>]*disabled[^>]*>↻ Try again/)
  })

  it('says what is going on before there is a report', () => {
    const m = model()
    expect(render(m)).toContain('The debrief starts when your fix has been accepted.')
    m.apply(ev('debrief_started', { attempt: 2, judges: [] }))
    expect(render(m)).toContain('re-running the whole suite')
    m.apply(ev('debrief_ended', { ok: false }))
    expect(render(m)).toContain('could not be completed')
  })
})

describe('the Debrief tab in the dock', () => {
  const dock = (m: OfficeModel) => renderToStaticMarkup(<Dock model={m} projectId="p1" replay={false} onDecide={() => {}} ticker="" onSubmit={async () => {}} onError={() => {}} onPost={async () => {}} onTryAgain={async () => {}} busy={false} />)

  it('appears with the meeting and carries a badge until you have seen the report', () => {
    const m = model()
    expect(dock(m)).not.toContain('>Debrief')
    m.apply(ev('debrief_started', { attempt: 2, judges: [] }))
    expect(dock(m)).toContain('>Debrief')
    m.apply(ev('debrief_report', { report: report() }))
    expect(dock(m)).toMatch(/>Debrief<span[^>]*>1</)
  })
})
