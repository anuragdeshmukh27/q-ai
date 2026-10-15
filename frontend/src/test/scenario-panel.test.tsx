import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { LeftPanel } from '../components/LeftPanel'
import { OfficeModel, type AgentInfo, type QEvent } from '../model'
import { scenarioRunEnded, scenarioRunKey, showsScenarioPanel } from '../scenario'

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['database', 'Karan'], ['qa', 'Ananya']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))
let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

const STEPS = [
  { id: 'run-tests', title: 'Reproduce it', text: 'Press Run tests.', state: 'done' },
  { id: 'read-data', title: 'Read the data', text: 'Open the snapshot.', state: 'current' },
  { id: 'fix', title: 'Fix it', text: 'Write the migration.', state: 'todo' },
  { id: 'submit', title: 'Submit', text: 'Press Submit.', state: 'todo' },
]

/** A Double bookings run as the events of the server build it: the scenario, the task handed to the learner, Priya's guide on its second step. */
function run(over: { kind?: 'learner' | 'demo'; hints?: number; autoplay?: boolean; ended?: boolean } = {}) {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  m.setHumanRoles(['database'])
  m.apply(ev('scenario_started', { scenario: 'opd-double-bookings', title: 'Double bookings', role: 'database', minutes: 30, channel: { id: 'incident-duplicates', name: '#incident-duplicates' }, teammates: ['qa', 'architect', 'backend', 'planner'], started_at: 1000, attempt: 2, ...(over.kind === 'demo' ? { kind: 'demo', variant: 'weak' } : {}) }))
  m.apply(ev('plan_created', { tasks: [{ id: 'h1', title: 'Fix: stop double bookings in the database', owner: 'database', depends_on: [], files: ['database/migrations/0008_one_booking_per_slot.sql'] }] }))
  m.apply(ev('human_task_assigned', { agent: 'database', task: 'h1', title: 'Fix: stop double bookings in the database', owner: 'database', worktree: 'C:\\w\\.worktrees\\database', doc: '.q/tasks/h1.md', tests: [] }))
  m.apply(ev('project_progress', { done: 0, total: 1, percent: 0, tasks: { h1: 'running' } }))
  m.apply(ev('guide_progress', { task: 'h1', current: 'read-data', done: 1, steps: STEPS }))
  for (let n = 1; n <= (over.hints ?? 0); n++) m.apply(ev('session_event', { id: `E0${n}`, t: 60 * n, kind: 'hint_given', n }), false)
  if (over.autoplay) m.apply(ev('autoplay_started', { variant: 'weak', speed: 1, rate: 1, t: 4, total: 3, labels: ['a', 'b', 'c'], task: 'h1', doc: '# Task' }), false)
  if (over.ended) m.apply(ev('session_event', { id: 'E99', t: 190, kind: 'session_finished', ok: true }, 1190), false)
  return m
}

const left = (model: OfficeModel, over: Record<string, unknown> = {}) =>
  renderToStaticMarkup(
    <LeftPanel model={model} busy={false} demo={false} hasProject recordings={[]} recording="" onRecording={() => {}} config={null} preset="fastapi-vanilla" onPreset={() => {}} fast onFast={() => {}} onStart={() => {}} onImport={() => {}} mode="simulation" replay={false} projectId="p1" humanRoles={['database']} onHumanRoles={() => {}} onSubmit={async () => {}} onCopyPath={() => {}} scenarios={[]} onScenario={() => {}} {...over} />,
  )

const LIVE_BUILD = ['GOAL', 'STACK PRESET', 'CHOOSE A RECORDED BUILD', 'Build it', 'FINISH MY PROJECT', 'PM BOARD', 'TRY A FAMOUS APP', 'YOU PLAY']

describe('the left panel while a scenario runs', () => {
  it('shows the scenario, the task with Submit, the guide progress and the hints, and none of the live-build column', () => {
    const html = left(run({ hints: 1 }))
    expect(html).toContain('aria-label="Scenario"')
    expect(html).toContain('Double bookings'); expect(html).toContain('You play: Database engineer'); expect(html).toContain('time box 30 min'); expect(html).toContain('#incident-duplicates')
    expect(html).toContain('Fix: stop double bookings in the database'); expect(html).toContain('YOUR TURN'); expect(html).toMatch(/<button[^>]*>Submit<\/button>/)
    expect(html).toContain('Task document'); expect(html).toContain('/api/projects/p1/tasks/h1/doc')
    expect(html).toContain('Step 2 of 4'); expect(html).toContain('1 of 4 done'); expect(html).toContain('Read the data')
    expect(html).toMatch(/Hints used: <span[^>]*>1<\/span>/)
    for (const live of LIVE_BUILD) expect(html).not.toContain(live)
    expect(html).not.toContain('Back to the scenarios') // the way back appears when the run ends
  })

  it('counts no hints before the first one, and says so while the guide has not started', () => {
    expect(left(run())).toMatch(/Hints used: <span[^>]*>0<\/span>/)
    const m = new OfficeModel()
    m.apply(ev('scenario_started', { scenario: 'opd-double-bookings', title: 'Double bookings', role: 'database', minutes: 30, channel: { id: 'c', name: '#incident-duplicates' }, teammates: [], started_at: 1000 }))
    const html = left(m)
    expect(html).toContain('Your task appears when the incident starts.'); expect(html).toContain('The guide starts with the incident.')
  })

  it('shows the same panel for a script that plays the run, without a Submit of its own, and marks it as a demo', () => {
    const html = left(run({ kind: 'demo', autoplay: true }))
    expect(html).toContain('aria-label="Scenario"'); expect(html).toContain('demo · weak'); expect(html).toContain('A script plays this run')
    expect(html).not.toMatch(/<button[^>]*>Submit<\/button>/); expect(html).not.toContain('attempt 2')
    for (const live of LIVE_BUILD) expect(html).not.toContain(live)
  })

  it('offers the way back to the scenario picker when the run ends, and not before', () => {
    const over = left(run({ ended: true }))
    expect(over).toContain('Back to the scenarios'); expect(over).toContain('The incident is over')
    expect(over).not.toMatch(/<button[^>]*>Submit<\/button>/) // nothing left to submit
    expect(left(run({ kind: 'demo', autoplay: true, ended: true }))).not.toContain('Back to the scenarios') // the script is still playing: its debrief goes on
  })

  it('keeps the live-build column for a normal build', () => {
    const html = left(new OfficeModel(), { hasProject: false })
    expect(html).not.toContain('aria-label="Scenario"')
    for (const live of ['GOAL', 'STACK PRESET', 'Build it', 'PM BOARD', 'YOU PLAY']) expect(html).toContain(live)
  })
})

describe('leaving the scenario view', () => {
  it('shows the panel for a scenario, stops showing it once the learner has gone back from that run, and shows the next run again', () => {
    const a = run().scenario!
    const key = scenarioRunKey(a)
    expect(key).toBe('opd-double-bookings:2:1000:learner:')
    expect(showsScenarioPanel(a, null)).toBe(true); expect(showsScenarioPanel(a, key)).toBe(false)
    expect(showsScenarioPanel({ ...a, startedAt: 2000 }, key)).toBe(true) // another attempt
    expect(showsScenarioPanel({ ...a, id: 'opd-bookings-down' }, key)).toBe(true) // another scenario
    expect(showsScenarioPanel(null, null)).toBe(false); expect(scenarioRunKey(null)).toBeNull()
  })

  it('treats a run as over when its session ended or the build finished, unless a script is still playing it', () => {
    expect(scenarioRunEnded({ endedAt: null }, false, false)).toBe(false)
    expect(scenarioRunEnded({ endedAt: 1190 }, false, false)).toBe(true)
    expect(scenarioRunEnded({ endedAt: null }, true, false)).toBe(true)
    expect(scenarioRunEnded({ endedAt: 1190 }, true, true)).toBe(false)
  })

  it('goes back to the picker: a run the learner has left renders the picker with the scenarios and no scenario panel, even when the build never finished', () => {
    const m = run({ ended: true })
    const info = [{ id: 'opd-double-bookings', title: 'Double bookings', summary: 's', role: 'database', minutes: 30, level: 'Advanced', channel: '#incident-duplicates', tests: 5, teammates: [] }]
    const before = left(m, { scenarios: info })
    expect(before).toContain('aria-label="Scenario"'); expect(before).not.toContain('Start the incident')
    const html = left(m, { scenarios: info, leftRun: scenarioRunKey(m.scenario) })
    expect(html).toContain('Start the incident'); expect(html).toContain('SCENARIOS'); expect(html).toContain('GOAL'); expect(html).not.toContain('aria-label="Scenario"')
    expect(left(run({ ended: true, hints: 1 }), { scenarios: info, leftRun: 'opd-double-bookings:1:5:learner:' })).toContain('aria-label="Scenario"') // an older run's key does not hide this one
  })
})
