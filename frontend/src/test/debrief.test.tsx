import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { COLS, MEETING_SPOTS, ROWS, buildBlocked } from '../office/layout'
import { Dock } from '../components/Dock'
import { DebriefTab } from '../dock/DebriefTab'
import { OfficeModel, type AgentInfo, type QEvent, type Visual } from '../model'
import { coachLabel, deltaLabel, eventDetail, previousAttempt, rowsOf, scoreColor, voiceLabel, wordingLabel, type DebriefReport, type ReportRow, type ScoringCriterion } from '../scenario'
import { ScoringPanel } from '../dock/IdeTab'

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['database', 'Karan'], ['qa', 'Ananya'], ['reviewer', 'Vikram']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))

let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

const row = (id: string, criterion: string, kind: 'strength' | 'gap', event: string, t: number, quote: string, note: string, advice = '', source = '#incident-opd'): ReportRow => ({
  id, criterion, rule: id, kind, event, events: [event], t, source, quote, note, advice, verified: true, worded_by: 'rule',
})

const CRITERIA = [['communication', 'Communication', 'architect', 'Aarav', 3], ['diagnosis', 'Diagnosis', 'database', 'Karan', 4], ['fix_quality', 'Fix quality', 'reviewer', 'Vikram', 3],
  ['testing', 'Testing', 'qa', 'Ananya', 2], ['ownership', 'Ownership', 'architect', 'Aarav', 4]] as const

function report(over: Partial<DebriefReport> = {}): DebriefReport {
  return {
    version: 1, scenario: 'opd-bookings-down', title: 'Production incident: Bookings are down', project: 'opd-bookings-down-2', attempt: 2, total: 80, max: 100, elapsed: 1120, minutes: 25,
    rubric: { id: 'opd-bookings-down-v1', version: 1 },
    criteria: CRITERIA.map(([id, name, judge, judge_name, score]) => ({ id, name, judge, judge_name, score, max: 4, descriptor: `what ${score} means`, summary: `Held: ${score} of 4 rules. Missed: ${4 - score}.`, keep: 'Keep going.', rows: [] })),
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
    fairness: { points: 9, quoted: 9, matched: 9, dropped: [{ finding: 'F05', text: 'You never ran the tests.', reason: 'event E999 is not in the session log' }], ai_rejected: [], tests_rerun: { ok: true, passed: 97, total: 97 }, rubric: 'v1',
                voices: { judges: 'mixed', coach: 'model', reason: '' } },
    coach: { text: 'You scored 80 out of 100. Your fix was small and tested; the next step is to post your first update sooner.', source: 'model' },
    judge_lines: {},
    focus: ['Add a regression test with every bug fix.', 'Search the whole codebase for a renamed name.', 'Send updates on the time you promised.'],
    attempts: [{ attempt: 1, total: 60, scores: {}, project: 'opd-bookings-down', finished_at: '2026-10-12T09:00:00', elapsed: 900 }, { attempt: 2, total: 80, scores: {}, project: 'opd-bookings-down-2', finished_at: '2026-10-12T10:00:00', elapsed: 1120 }],
    files: { md: '.q/reports/attempt-2.md', json: '.q/reports/attempt-2.json' },
    ...over,
  }
}

function model() {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  m.setHumanRoles(['backend'])
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

  it('says what each score is made of, labels every point as the rule\'s and the paragraph as the AI coach', () => {
    const r = report()
    const html = render(withReport(r))
    expect(html).toContain('Aarav: Held: 3 of 4 rules. Missed: 1.'); expect(html).toContain('title="what 3 means"') // the summary is built from the rules; the level text is its tooltip
    expect(html.match(/>rule</g)?.length).toBe(4); expect(html).not.toContain('AI wording'); expect(html).not.toContain('Sentences in the 7b')
    expect(html).toContain('aria-label="Coach"'); expect(html).toContain('>AI coach<'); expect(html).toContain('You scored 80 out of 100. Your fix was small and tested')
    expect(wordingLabel(r.rows[0])).toBe('rule'); expect(coachLabel(r.coach)).toBe('AI coach'); expect(coachLabel({ source: 'template' })).toBe('Summary')
  })

  it('shows a template paragraph as a summary and says why the 7b was not used', () => {
    const r = report({ coach: { text: 'You scored 80 out of 100. Every criterion scored 4 out of 4.', source: 'template' } })
    r.fairness.voices = { judges: 'template', coach: 'template', reason: 'error' }
    const html = render(withReport(r))
    expect(html).toContain('>Summary<'); expect(html).not.toContain('>AI coach<'); expect(html).toContain('The 7b was not used for the judges and the coach: error.')
  })

  it('shows employee names, not role ids, in the detail of an entry', () => {
    const m = withReport()
    const detail = eventDetail(m.debrief!.report!, 'E012', (id) => m.name(id))
    expect(detail).toContainEqual(['from', 'Aarav']); expect(detail.map((x) => x[1])).not.toContain('architect')
    expect(eventDetail(m.debrief!.report!, 'E006', (id) => m.name(id))).toContainEqual(['role', 'You']) // the role you play reads You
    expect(render(m, { initiallyOpen: 'R02' })).toContain('Aarav')
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

describe('the meeting room in the office', () => {
  it('has a free, distinct place to stand for every employee of the roster', () => {
    const seats = [[3, 2], [6, 2], [9, 2], [12, 2], [3, 6], [6, 6], [9, 6], [12, 6]].map(([x, y]) => ({ x, y }))
    const blocked = buildBlocked(seats)
    expect(MEETING_SPOTS.length).toBeGreaterThanOrEqual(8)
    expect(new Set(MEETING_SPOTS.map((t) => `${t.x},${t.y}`)).size).toBe(MEETING_SPOTS.length)
    for (const t of MEETING_SPOTS) {
      expect(t.x >= 0 && t.x < COLS && t.y >= 0 && t.y < ROWS).toBe(true)
      expect(blocked[t.y][t.x]).toBe(false)
    }
  })
})

describe('the judges\' lines in the channel', () => {
  it('marks the lines the 7b wrote and uses the short text for the bubble', () => {
    const m = model()
    const visuals: Visual[] = []
    m.onVisual((v) => visuals.push(v))
    m.apply(ev('channel_message', { id: 'C020', channel: 'incident-opd', from: 'qa', text: 'I give you 2/4: at 14:38 you submitted without a test of your own, so add one.', source: 'debrief', t: 900, bubble: 'I give you 2/4: add a test.', debrief: true, voice: 'model' }))
    m.apply(ev('channel_message', { id: 'C021', channel: 'incident-opd', from: 'architect', text: 'Communication 3/4. At 01:40: “Update” First update at 01:40. Tip: post sooner.', source: 'debrief', t: 901, bubble: 'Communication 3/4. Post sooner.', debrief: true, voice: 'template' }))
    expect(m.channel.map((c) => c.voice)).toEqual(['model', 'template']); expect(voiceLabel(m.channel[0])).toBe('AI line'); expect(voiceLabel(m.channel[1])).toBe('')
    expect(visuals.filter((v) => v.kind === 'say').map((v) => (v as { text: string }).text)).toEqual(['I give you 2/4: add a test.', 'Communication 3/4. Post sooner.'])
  })
})

describe('How you are scored', () => {
  const SCORING: ScoringCriterion[] = [
    { id: 'communication', name: 'Communication', judge: 'architect', rules: [{ id: 'first_update', plain: 'Post a first update in #incident-opd within 2 minutes of the start.' }, { id: 'answered_requests', plain: 'When Aarav asks for an update, answer within a minute.' }] },
    { id: 'diagnosis', name: 'Diagnosis', judge: 'database', rules: [{ id: 'reproduced_first', plain: 'Run the tests before you save any file, and read why they fail.' }] },
  ]

  it('lists the rules by criterion with the judge, in plain words', () => {
    const html = renderToStaticMarkup(<ScoringPanel scoring={SCORING} name={(id) => ({ architect: 'Aarav', database: 'Karan' })[id] ?? id} />)
    expect(html).toContain('aria-label="How you are scored"'); expect(html).toContain('How you are scored'); expect(html).toContain('3 rules, 2 judges, 100 marks')
    expect(html).toContain('Communication'); expect(html).toContain('judge Aarav'); expect(html).toContain('judge Karan'); expect(html).toContain('Post a first update in #incident-opd within 2 minutes of the start.')
    expect(html).toContain('Run the tests before you save any file'); expect(html).toContain('<details open'); expect(html).not.toContain('architect')
  })

  it('comes with the start of the incident and is empty for a scenario without a rubric', () => {
    const m = model()
    m.apply(ev('scenario_started', { scenario: 'x', title: 'X', role: 'backend', minutes: 25, channel: { id: 'c', name: '#c' }, teammates: [], started_at: 1000, attempt: 1, scoring: SCORING }))
    expect(m.scenario?.scoring).toEqual(SCORING)
    m.apply(ev('scenario_started', { scenario: 'x', title: 'X', role: 'backend', minutes: 25, channel: { id: 'c', name: '#c' }, teammates: [], started_at: 1000, attempt: 1 }))
    expect(m.scenario?.scoring).toEqual([])
  })
})

describe('the IDE stays in the dock while another tab shows', () => {
  const dock = (m: OfficeModel) => renderToStaticMarkup(<Dock model={m} projectId="p1" replay={false} onDecide={() => {}} ticker="" onSubmit={async () => {}} onError={() => {}} onPost={async () => {}} onTryAgain={async () => {}} busy={false} />)

  it('renders the IDE hidden behind the Explorer when you play a role, and not at all when you do not', () => {
    const m = model() // plays backend
    expect(dock(m)).toMatch(/class="hidden" data-testid="ide-host"/)
    const other = new OfficeModel()
    other.setRoster(ROSTER)
    expect(dock(other)).not.toContain('ide-host')
  })
})

describe('unbacked claims and AI lines not used are separate', () => {
  const clean = () => {
    const r = report()
    r.fairness.dropped = []
    return r
  }
  const withReport = (r: DebriefReport) => {
    const m = model()
    m.apply(ev('debrief_started', { attempt: r.attempt, judges: [] }))
    m.apply(ev('debrief_report', { report: r }))
    return m
  }
  const render = (m: OfficeModel) => renderToStaticMarkup(<DebriefTab model={m} projectId="p1" onTryAgain={() => {}} />)

  it('shows 0 unbacked claims for a clean run, whatever the 7b wrote', () => {
    const r = clean()
    r.fairness.ai_rejected = [{ finding: 'communication', text: 'Update: bookings fail (00:43) Keep posting.', reason: 'the time 09:09 is not the time of any point' }, { finding: 'coach', text: 'You did a great job.', reason: 'it uses generic praise (“great job”)' }]
    const html = render(withReport(r))
    expect(html).toMatch(/Unbacked claims dropped<\/span><span[^>]*>0</); expect(html).not.toContain('Dropped:')
    expect(html).toContain('aria-label="AI lines not used"'); expect(html).toContain('AI lines not used (2)')
    expect(html).toContain('<b class="text-[var(--text)]">Communication:</b>'); expect(html).toContain('<b class="text-[var(--text)]">Coach:</b>'); expect(html).toContain('it uses generic praise')
  })

  it('keeps the rejected AI lines collapsed, and shows nothing when none were rejected', () => {
    const r = clean()
    r.fairness.ai_rejected = [{ finding: 'testing', text: 'x', reason: 'y' }]
    const html = render(withReport(r))
    expect(html).toMatch(/<details class="[^"]*" aria-label="AI lines not used"><summary/); expect(html).not.toMatch(/<details[^>]* open/)
    expect(render(withReport(clean()))).not.toContain('AI lines not used')
  })

  it('lists the evidence points that were dropped as unbacked claims, apart from the AI lines', () => {
    const r = report()
    r.fairness.ai_rejected = [{ finding: 'diagnosis', text: 'z', reason: 'q' }]
    const html = render(withReport(r))
    expect(html).toMatch(/Unbacked claim dropped<\/span><span[^>]*>1</); expect(html).toContain('Dropped:'); expect(html).toContain('AI lines not used (1)')
  })
})
