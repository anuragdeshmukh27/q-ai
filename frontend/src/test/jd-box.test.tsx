import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { JobBoxView, type JobViewProps } from '../components/JobBox'
import { LeftPanel } from '../components/LeftPanel'
import { ProgressView } from '../components/ProgressPage'
import { DebriefTab, RoleFit } from '../dock/DebriefTab'
import { MAX_JD_CHARS, clipJd, counter, jobRequest, readerLabel, readerNote, seniorityLabel, stressed, weightText, type JobAnalysis, type JobExtraction, type ReportJob } from '../jobs'
import { OfficeModel, type AgentInfo, type QEvent } from '../model'
import type { Progress } from '../progress'
import type { DebriefReport, ScenarioInfo } from '../scenario'

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['database', 'Karan'], ['qa', 'Ananya']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))
let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

const CARDS: ScenarioInfo[] = [
  { id: 'opd-bookings-down', title: 'Production incident: Bookings are down', summary: 'Bookings fail.', role: 'backend', minutes: 25, level: 'Intermediate', channel: '#incident-opd', tests: 3, teammates: ['qa'] },
  { id: 'opd-double-bookings', title: 'Double bookings', summary: 'Two patients, one slot.', role: 'database', minutes: 30, level: 'Advanced', channel: '#incident-duplicates', tests: 5, teammates: ['qa'] },
  { id: 'opd-form-says-saved', title: 'The form says it saved', summary: 'False success.', role: 'frontend', minutes: 25, level: 'Intermediate', channel: '#incident-frontdesk', tests: 6, teammates: ['qa'] },
]

const EXTRACTION: JobExtraction = {
  role: 'Backend Engineer', role_family: 'backend', seniority: 'senior', domain: 'fintech', skills: ['python', 'fastapi', 'postgresql', 'rest api'], soft_skills: ['communication', 'testing culture'],
  app_idea: 'A payments service: accounts, transfers and a ledger with a transaction history.', source: 'keywords', reason: 'the model is not installed or not running',
}
const ANALYSIS: JobAnalysis = {
  job: { source: 'sample', sample_id: 'backend-engineer', chars: 1382, clipped: false },
  extraction: EXTRACTION,
  ranking: [
    { scenario: 'opd-bookings-down', title: CARDS[0].title, kind: 'existing', score: 85, parts: { role: 50, skills: 35, domain: 0 }, shared_skills: ['python', 'fastapi'], reason: "The posting's role (Backend Engineer) matches the Backend engineer seat; shares python, fastapi (2 of the incident's 8 skills); domain fintech differs from healthcare.", rank: 1 },
    { scenario: 'opd-double-bookings', title: CARDS[1].title, kind: 'existing', score: 35, parts: { role: 0, skills: 35, domain: 0 }, shared_skills: ['python'], reason: 'The posting is for a backend engineer, this is the Database engineer seat.', rank: 2 },
    { scenario: 'opd-form-says-saved', title: CARDS[2].title, kind: 'existing', score: 9, parts: { role: 0, skills: 9, domain: 0 }, shared_skills: ['rest api'], reason: 'The posting is for a backend engineer, this is the Frontend engineer seat.', rank: 3 },
  ],
  recommended: 'opd-bookings-down',
}
const SAMPLES = [{ id: 'backend-engineer', title: 'Backend engineer', text: 'Backend Engineer\nPython' }, { id: 'database-engineer', title: 'Database / data engineer', text: 'x' }, { id: 'frontend-engineer', title: 'Frontend engineer', text: 'y' }]

const noop = () => {}
const view = (over: Partial<JobViewProps> = {}) =>
  renderToStaticMarkup(<JobBoxView samples={SAMPLES} text="" sampleId="" reading={false} error="" analysis={null} scenarios={CARDS} busy={false} onText={noop} onSample={noop} onRead={noop} onStart={noop} {...over} />)

describe('job description helpers', () => {
  it('cuts a paste at 5,000 characters and counts what is in the box', () => {
    expect(MAX_JD_CHARS).toBe(5000)
    expect(clipJd('a'.repeat(6000))).toHaveLength(5000)
    expect(clipJd('short')).toBe('short')
    expect(counter('')).toBe('0 / 5,000')
    expect(counter('a'.repeat(1234))).toBe('1,234 / 5,000')
  })
  it('names the reader and says why the keywords were used', () => {
    expect(readerLabel(EXTRACTION)).toBe('Keyword reader')
    expect(readerNote(EXTRACTION)).toBe('The model was not used: the model is not installed or not running.')
    expect(readerLabel({ source: 'model', reason: '' })).toBe('AI reader (qwen2.5-coder:7b)')
    expect(readerNote({ source: 'model', reason: '' })).toContain('every skill it named is in your text')
    expect(readerNote({ source: 'keywords', reason: '' })).toContain('keyword reader')
  })
  it('sends a sample by its id and a pasted text as text, both with the reading that was shown', () => {
    expect(jobRequest(ANALYSIS, 'ignored')).toEqual({ sample_id: 'backend-engineer', extraction: EXTRACTION })
    expect(jobRequest({ ...ANALYSIS, job: { ...ANALYSIS.job, source: 'paste', sample_id: '' } }, 'my posting')).toEqual({ text: 'my posting', extraction: EXTRACTION })
  })
  it('lists the criteria a job stresses, heaviest first, and formats weights', () => {
    const names = { communication: 'Communication', diagnosis: 'Diagnosis', fix_quality: 'Fix quality', testing: 'Testing', ownership: 'Ownership' }
    expect(stressed({ communication: 0.9, diagnosis: 1.14, fix_quality: 0.68, testing: 1.3, ownership: 1.14 }, names)).toEqual(['Testing', 'Diagnosis', 'Ownership'])
    expect(stressed({ communication: 1, diagnosis: 1, fix_quality: 1, testing: 1, ownership: 1 }, names)).toEqual([])
    expect(weightText(1.5)).toBe('×1.50'); expect(seniorityLabel('senior')).toBe('Senior')
  })
})

describe('the Start from a job description box', () => {
  it('shows the box, the three samples, the counter and a Read button that waits for text', () => {
    const html = view()
    expect(html).toContain('aria-label="Start from a job description"'); expect(html).toContain('START FROM A JOB DESCRIPTION')
    for (const s of SAMPLES) expect(html).toContain(s.title)
    expect(html).toContain('maxLength="5000"'); expect(html).toContain('0 / 5,000'); expect(html).toContain('up to 5,000 characters')
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Read this job description/)
    expect(html).not.toContain('SCENARIOS RANKED FOR THIS JOB')
  })
  it('enables Read once there is text, shows the counter, and marks the sample that fills the box', () => {
    const html = view({ text: 'Backend Engineer\nPython', sampleId: 'backend-engineer' })
    expect(html).toMatch(/<button[^>]*>Read this job description/); expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Read this job description/)
    expect(html).toContain('23 / 5,000'); expect(html).toMatch(/aria-pressed="true"[^>]*>Backend engineer/); expect(html).toMatch(/aria-pressed="false"[^>]*>Frontend engineer/)
    expect(view({ text: 'x', reading: true })).toMatch(/<button[^>]*disabled=""[^>]*>Reading…/)
  })
  it('shows an error in words', () => {
    expect(view({ error: 'Paste a job description (or pick a sample).' })).toMatch(/role="alert"[^>]*>Paste a job description/)
  })
  it('shows how Q read the posting and which reader was used', () => {
    const html = view({ text: 'x', analysis: ANALYSIS })
    expect(html).toContain('Read by: Keyword reader'); expect(html).toContain('The model was not used: the model is not installed or not running.')
    expect(html).toContain('Backend Engineer'); expect(html).toContain('Senior'); expect(html).toContain('domain: fintech')
    for (const s of ['python', 'fastapi', 'postgresql', 'rest api']) expect(html).toContain(`>${s}</span>`)
    expect(html).toContain('communication, testing culture'); expect(html).toContain('A payments service')
    const model = view({ text: 'x', analysis: { ...ANALYSIS, extraction: { ...EXTRACTION, source: 'model', reason: '' } } })
    expect(model).toContain('Read by: AI reader (qwen2.5-coder:7b)'); expect(model).toContain('Read by the local model')
    expect(view({ text: 'x', analysis: { ...ANALYSIS, job: { ...ANALYSIS.job, clipped: true } } })).toContain('cut at 5,000 characters')
  })
  it('ranks the scenarios in order with a score, a reason built from the data and a card to pick', () => {
    const html = view({ text: 'x', analysis: ANALYSIS })
    expect(html).toContain('SCENARIOS RANKED FOR THIS JOB')
    const order = CARDS.map((c) => html.indexOf(`aria-label="${ANALYSIS.ranking.find((m) => m.scenario === c.id)!.rank}. ${c.title}`))
    expect(order.every((i) => i > 0) && order[0] < order[1] && order[1] < order[2]).toBe(true)
    for (const m of ANALYSIS.ranking) { expect(html).toContain(`${m.score}/100`); expect(html).toContain(m.reason.replace(/'/g, '&#x27;')) }
    expect(html).toContain('role 50 · skills 35 · domain 0')
    expect(html.match(/best fit/g)).toHaveLength(1)
    expect(html).toContain('You play: Backend engineer'); expect(html).toContain('You play: Frontend engineer')
    expect(html).toContain('Start this scenario for this job'); expect(html.match(/Pick this one instead/g)).toHaveLength(2) // the learner can pick another card
  })
  it('locks every Start while a run is starting', () => {
    const html = view({ text: 'x', analysis: ANALYSIS, busy: true })
    expect(html.match(/<button[^>]*disabled=""[^>]*>Starting…/g)).toHaveLength(3)
  })
  it('sits above the scenario cards in the left panel in Simulation mode, and not in Demo mode or without scenarios', () => {
    const panel = (over: Record<string, unknown> = {}) => renderToStaticMarkup(
      <LeftPanel model={new OfficeModel()} busy={false} demo={false} hasProject={false} recordings={[]} recording="" onRecording={noop} config={null} preset="fastapi-vanilla" onPreset={noop} fast onFast={noop} onStart={noop} onImport={noop} mode="simulation" replay={false} projectId={null} humanRoles={['backend']} onHumanRoles={noop} onSubmit={async () => {}} onCopyPath={noop} scenarios={CARDS} onScenario={noop} {...over} />,
    )
    const html = panel()
    expect(html).toContain('START FROM A JOB DESCRIPTION'); expect(html.indexOf('START FROM A JOB DESCRIPTION')).toBeLessThan(html.indexOf('aria-label="Scenarios"'))
    expect(panel({ demo: true })).not.toContain('START FROM A JOB DESCRIPTION')
    expect(panel({ mode: 'supervised' })).not.toContain('START FROM A JOB DESCRIPTION')
    expect(panel({ scenarios: [] })).not.toContain('START FROM A JOB DESCRIPTION')
  })
})

// -- the task panel -------------------------------------------------------------------------------------------------------

const JOB_EVENT = {
  source: 'sample', sample_id: 'backend-engineer', role: 'Backend Engineer', seniority: 'senior', domain: 'fintech', reader: 'keywords', key_skills: ['rest api', 'python', 'fastapi'],
  match: { score: 85, rank: 1, of: 3, reason: 'The posting matches the Backend engineer seat.' }, weights: { communication: 0.91, diagnosis: 1.14, fix_quality: 0.68, testing: 1.14, ownership: 1.14 },
  briefing: { text: 'This incident fits the Backend Engineer job: it puts you in the Backend engineer seat for 25 minutes.', source: 'template', reason: '' },
}

function run(job: Record<string, unknown> | null = JOB_EVENT) {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  m.setHumanRoles(['backend'])
  m.apply(ev('scenario_started', { scenario: 'opd-bookings-down', title: CARDS[0].title, role: 'backend', minutes: 25, channel: { id: 'incident-opd', name: '#incident-opd' }, teammates: ['qa'], started_at: 1000, attempt: 1, ...(job ? { job } : {}) }))
  m.apply(ev('plan_created', { tasks: [{ id: 'h1', title: 'Fix: booking returns 500', owner: 'backend', depends_on: [], files: ['backend/api/appointments.py'] }] }))
  m.apply(ev('human_task_assigned', { agent: 'backend', task: 'h1', title: 'Fix: booking returns 500', owner: 'backend', worktree: 'C:\\w', doc: '.q/tasks/h1.md', tests: [] }))
  m.apply(ev('project_progress', { done: 0, total: 1, percent: 0, tasks: { h1: 'running' } }))
  return m
}
const panel = (m: OfficeModel) =>
  renderToStaticMarkup(
    <LeftPanel model={m} busy={false} demo={false} hasProject recordings={[]} recording="" onRecording={noop} config={null} preset="fastapi-vanilla" onPreset={noop} fast onFast={noop} onStart={noop} onImport={noop} mode="simulation" replay={false} projectId="p1" humanRoles={['backend']} onHumanRoles={noop} onSubmit={async () => {}} onCopyPath={noop} scenarios={CARDS} onScenario={noop} />,
  )

describe('the job in the scenario panel', () => {
  it('keeps the job from the scenario_started event', () => {
    const m = run()
    expect(m.scenario?.job).toMatchObject({ role: 'Backend Engineer', domain: 'fintech', reader: 'keywords', keySkills: ['rest api', 'python', 'fastapi'], sampleId: 'backend-engineer', match: { rank: 1, of: 3, score: 85 } })
    expect(m.scenario?.job?.weights.diagnosis).toBe(1.14)
    expect(run(null).scenario?.job).toBeUndefined()
  })
  it('shows why this scenario fits the job, the key skills and what the extra score is, in the task panel', () => {
    const html = panel(run())
    expect(html).toContain('WHY THIS SCENARIO FITS THIS JOB'); expect(html).toContain('This incident fits the Backend Engineer job'); expect(html).toContain('Template wording')
    expect(html).toContain('KEY SKILLS OF THE JOB'); for (const k of ['rest api', 'python', 'fastapi']) expect(html).toContain(`>${k}</span>`)
    expect(html).toContain('Your score stays the standard 0 to 100'); expect(html).toContain('Role fit')
    expect(html.indexOf('YOUR TASK')).toBeLessThan(html.indexOf('WHY THIS SCENARIO FITS THIS JOB')); expect(html.indexOf('WHY THIS SCENARIO FITS THIS JOB')).toBeLessThan(html.indexOf("PRIYA&#x27;S GUIDE"))
  })
  it('swaps in the model wording when the job_briefing event brings it, and keeps the template with the reason when it does not', () => {
    const m = run()
    m.apply(ev('job_briefing', { text: 'You are the Backend engineer for 25 minutes; the posting asks for Python.', source: 'model', reason: '' }))
    expect(m.scenario?.job?.briefing).toEqual({ text: 'You are the Backend engineer for 25 minutes; the posting asks for Python.', source: 'model', reason: '' })
    expect(panel(m)).toContain('Wording by the local model, checked against the job description'); expect(panel(m)).not.toContain('This incident fits the Backend Engineer job')
    const t = run()
    t.apply(ev('job_briefing', { text: JOB_EVENT.briefing.text, source: 'template', reason: 'the model took more than 25 s' }))
    expect(t.scenario?.job?.briefing.reason).toBe('the model took more than 25 s'); expect(panel(t)).toContain('Template wording')
    expect(panel(t)).toContain('title="the model took more than 25 s"')
  })
  it('shows nothing about a job for a scenario that was not started from one', () => {
    const html = panel(run(null))
    expect(html).not.toContain('WHY THIS SCENARIO FITS THIS JOB'); expect(html).not.toContain('KEY SKILLS OF THE JOB')
    const m = run(null)
    m.apply(ev('job_briefing', { text: 'x', source: 'model' }))
    expect(m.scenario?.job).toBeUndefined()
  })
})

// -- the debrief -------------------------------------------------------------------------------------------------------------

const JOB_REPORT: ReportJob = {
  source: 'sample', sample_id: 'backend-engineer', clipped: false, extraction: EXTRACTION, match: ANALYSIS.ranking[0], weights: JOB_EVENT.weights,
  weight_reasons: { communication: ['communicat'], diagnosis: ['debug', 'root cause'], fix_quality: ['maintainab'], testing: ['pytest'], ownership: [] },
  key_skills: ['rest api', 'python'], briefing: { text: 'b', source: 'template', reason: '' }, role_fit: 78, standard_total: 80,
  criteria: [['communication', 'Communication', 3, 0.91], ['diagnosis', 'Diagnosis', 4, 1.14], ['fix_quality', 'Fix quality', 3, 0.68], ['testing', 'Testing', 2, 1.14], ['ownership', 'Ownership', 4, 1.14]].map(([id, name, score, weight]) => ({ id: id as string, name: name as string, score: score as number, max: 4, weight: weight as number })),
}
function report(job?: ReportJob): DebriefReport {
  return {
    version: 1, scenario: 'opd-bookings-down', title: CARDS[0].title, project: 'p', attempt: 1, total: 80, max: 100, elapsed: 600, minutes: 25, rubric: { id: 'r', version: 1 },
    criteria: JOB_REPORT.criteria.map((c) => ({ id: c.id, name: c.name, judge: 'architect', judge_name: 'Aarav', score: c.score, max: 4, descriptor: 'd', summary: 's', keep: 'k', rows: [] })),
    rows: [], events: {}, fairness: { points: 0, quoted: 0, matched: 0, dropped: [], ai_rejected: [], tests_rerun: null, rubric: 'v1', voices: { judges: 'template', coach: 'template', reason: '' } },
    focus: ['Add a regression test.'], coach: { text: 'You scored 80 out of 100.', source: 'template' }, judge_lines: {}, attempts: [{ attempt: 1, total: 80, scores: {}, project: 'p', finished_at: '2026-10-16T10:00:00', elapsed: 600, ...(job ? { role_fit: job.role_fit, job_role: 'Backend Engineer' } : {}) }],
    files: { md: 'a.md', json: 'a.json' }, ...(job ? { job } : {}),
  }
}
const debrief = (r: DebriefReport) => {
  const m = run()
  m.apply(ev('debrief_started', { attempt: 1, judges: [] }))
  m.apply(ev('debrief_report', { report: r }))
  return renderToStaticMarkup(<DebriefTab model={m} projectId="p1" onTryAgain={noop} />)
}

describe('Role fit in the debrief', () => {
  it('shows the role-fit score labelled as extra, next to the standard score, with the weights listed', () => {
    const html = debrief(report(JOB_REPORT))
    expect(html).toContain('aria-label="Total 80 out of 100"') // the standard score is still the headline
    expect(html).toContain('Role fit for this job (extra)'); expect(html).toContain('aria-label="Role fit 78 out of 100"')
    expect(html).toContain('standard score 80/100 above is the one that counts')
    expect(html).toContain('weighted by what the job description asks for: Diagnosis, Testing, Ownership count more')
    for (const w of ['×0.91', '×1.14', '×0.68']) expect(html).toContain(w)
    expect(html).toContain('aria-label="Role fit weights"'); expect(html.match(/weight <b/g)).toHaveLength(5)
    expect(html).toContain('Asked for: debug, root cause'); expect(html).toContain('Not stressed in the job description')
    expect(html).toContain('Read by keyword reader'); expect(html).toContain('sample “backend-engineer”')
    expect(html.indexOf('Total 80 out of 100')).toBeLessThan(html.indexOf('Role fit for this job (extra)')); expect(html.indexOf('Role fit for this job (extra)')).toBeLessThan(html.indexOf('Rubric (0 to 4 each)'))
  })
  it('says role fit equals the standard score when the job stresses nothing', () => {
    const flat = { ...JOB_REPORT, weights: { communication: 1, diagnosis: 1, fix_quality: 1, testing: 1, ownership: 1 }, criteria: JOB_REPORT.criteria.map((c) => ({ ...c, weight: 1 })), role_fit: 80 }
    expect(renderToStaticMarkup(<RoleFit report={report(flat)} />)).toContain('it stresses nothing in particular, so role fit equals the standard score')
  })
  it('has no Role fit card for an attempt that did not start from a job description', () => {
    const html = debrief(report())
    expect(html).not.toContain('Role fit'); expect(html).toContain('aria-label="Total 80 out of 100"')
    expect(renderToStaticMarkup(<RoleFit report={report()} />)).toBe('')
  })
})

// -- my progress ------------------------------------------------------------------------------------------------------------

describe('Role fit in My progress', () => {
  const attempt = (n: number, total: number, extra: object = {}) => ({ attempt: n, total, max: 100, scores: { communication: 2 }, date: '2026-10-12T20:24:28', elapsed: 300, project: `p-${n}`, ...extra })
  const data = (attempts: ReturnType<typeof attempt>[]): Progress => ({
    version: 1, generated_at: '2026-10-16T16:00:00', empty: false, attempts_total: attempts.length, weakest: null, next_step: null, skills: [],
    scenarios: [{ id: 'opd-bookings-down', title: CARDS[0].title, minutes: 25, max: 100, count: attempts.length, best_score: Math.max(...attempts.map((a) => a.total)), best_time: 300, last_total: attempts[attempts.length - 1].total, attempts }],
  })
  const html = (p: Progress) => renderToStaticMarkup(<ProgressView data={p} reset="idle" busy={false} onReset={noop} onStart={noop} onOpenReport={noop} />)
  it('shows role fit as small extra text under the score, which stays the number that counts', () => {
    const h = html(data([attempt(1, 60), attempt(2, 85, { role_fit: 90, job_role: 'Backend Engineer' })]))
    expect(h).toContain('role fit 90'); expect(h).toContain('Role fit for Backend Engineer: an extra number, the score is 85')
    expect(h.match(/role fit \d+/g)).toHaveLength(1) // only the attempt that had a job
    expect(h).toContain('Best score <b'); expect(h).toContain('85/100')
  })
  it('shows nothing extra without a job', () => {
    expect(html(data([attempt(1, 60)]))).not.toContain('role fit')
  })
})
