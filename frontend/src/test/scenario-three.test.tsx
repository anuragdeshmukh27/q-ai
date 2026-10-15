import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RecordingMeta } from '../api'
import { LeftPanel } from '../components/LeftPanel'
import { ScenarioPicker } from '../components/ScenarioPicker'
import { demosFor, pickDefault } from '../demos'
import { languageFor } from '../diff'
import { ideRole } from '../ide'
import { OfficeModel, type AgentInfo, type QEvent } from '../model'
import { scenarioRunKey, type ScenarioInfo } from '../scenario'

const ONE: ScenarioInfo = { id: 'opd-bookings-down', title: 'Production incident: Bookings are down', summary: 'The front desk of a hospital OPD cannot book appointments.', role: 'backend', minutes: 25, level: 'Intermediate', channel: '#incident-opd', tests: 3, teammates: ['qa', 'architect', 'database', 'planner'] }
const TWO: ScenarioInfo = { id: 'opd-double-bookings', title: 'Double bookings', summary: 'Two patients keep being booked with the same doctor at the same time.', role: 'database', minutes: 30, level: 'Advanced', channel: '#incident-duplicates', tests: 5, teammates: ['qa', 'architect', 'backend', 'planner'] }
const THREE: ScenarioInfo = { id: 'opd-form-says-saved', title: 'The form says it saved', summary: 'The front desk is told Appointment added for bookings that were never saved.', role: 'frontend', minutes: 25, level: 'Intermediate', channel: '#incident-frontdesk', tests: 6, teammates: ['qa', 'architect', 'backend', 'planner'] }

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['frontend', 'Meera'], ['database', 'Karan'], ['qa', 'Ananya']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))
let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

const picker = (scenarios: ScenarioInfo[], busy = false) => renderToStaticMarkup(<ScenarioPicker scenarios={scenarios} busy={busy} onStart={() => {}} onWatch={() => {}} />)
const count = (html: string, text: string) => html.split(text).length - 1

describe('the scenario picker with three scenarios', () => {
  it('shows three cards with the role, the level and the time, and a Start, a Strong run and a Weak run on each', () => {
    const html = picker([ONE, TWO, THREE])
    for (const t of ['Production incident: Bookings are down', 'Double bookings', 'The form says it saved']) expect(html).toContain(t)
    expect(html).toContain('You play: Backend engineer'); expect(html).toContain('You play: Database engineer'); expect(html).toContain('You play: Frontend engineer')
    expect(count(html, 'about 25 min')).toBe(2); expect(html).toContain('about 30 min'); expect(count(html, 'Intermediate')).toBe(2); expect(html).toContain('Advanced')
    expect(html).toContain('#incident-opd'); expect(html).toContain('#incident-duplicates'); expect(html).toContain('#incident-frontdesk')
    expect(count(html, 'Start the incident')).toBe(3); expect(count(html, '>Strong run<')).toBe(3); expect(count(html, '>Weak run<')).toBe(3)
    expect(html.indexOf('Bookings are down')).toBeLessThan(html.indexOf('Double bookings')); expect(html.indexOf('Double bookings')).toBeLessThan(html.indexOf('The form says it saved'))
  })

  it('locks all three cards while a run is starting', () => {
    const html = picker([ONE, TWO, THREE], true)
    expect(count(html, 'Starting…')).toBe(3)
    expect(html.match(/<button[^>]*disabled=""[^>]*>/g)?.length).toBe(9)
  })
})

function frontendRun(over: { hints?: number } = {}) {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  m.setHumanRoles(['frontend'])  // what starting the scenario does (useQ.startScenario)
  m.apply(ev('scenario_started', { scenario: THREE.id, title: THREE.title, role: 'frontend', minutes: 25, channel: { id: 'incident-frontdesk', name: '#incident-frontdesk' }, teammates: THREE.teammates, started_at: 1000, attempt: 1, kind: 'learner', variant: '' }))
  m.apply(ev('plan_created', { tasks: [{ id: 'h1', title: 'Fix: the pages report a refused request as a success', owner: 'frontend', depends_on: [], files: ['static/shell.js'] }] }))
  m.apply(ev('human_task_assigned', { agent: 'frontend', task: 'h1', title: 'Fix: the pages report a refused request as a success', owner: 'frontend', worktree: 'C:\\w\\.worktrees\\frontend', doc: '.q/tasks/h1.md', tests: [] }))
  m.apply(ev('project_progress', { done: 0, total: 1, percent: 0, tasks: { h1: 'running' } }))
  m.apply(ev('guide_progress', { task: 'h1', current: 'find-the-code', done: 2, steps: ['run-tests', 'read-the-answer', 'find-the-code', 'tell-channel', 'regression-test', 'fix', 'tests-green', 'submit'].map((id, i) => ({ id, title: id, text: id, state: i < 2 ? 'done' : i === 2 ? 'current' : 'todo' })) }))
  for (let n = 1; n <= (over.hints ?? 0); n++) m.apply(ev('session_event', { id: `E0${n}`, t: 60 * n, kind: 'hint_given', n }), false)
  return m
}

const left = (model: OfficeModel) =>
  renderToStaticMarkup(
    <LeftPanel model={model} busy={false} demo={false} hasProject recordings={[]} recording="" onRecording={() => {}} config={null} preset="fastapi-vanilla" onPreset={() => {}} fast onFast={() => {}} onStart={() => {}} onImport={() => {}} mode="simulation" replay={false} projectId="p1" humanRoles={['frontend']} onHumanRoles={() => {}} onSubmit={async () => {}} onCopyPath={() => {}} scenarios={[]} onScenario={() => {}} />,
  )

describe('playing the frontend engineer', () => {
  it('puts the learner in Meera\'s seat: the desk reads You, Rohan is a teammate and Karan is not on the incident', () => {
    const m = frontendRun()
    expect(m.scenario?.role).toBe('frontend'); expect(m.scenario?.channelName).toBe('#incident-frontdesk'); expect(m.scenario?.teammates).toEqual(['qa', 'architect', 'backend', 'planner'])
    expect(m.name('frontend')).toBe('You'); expect(m.name('backend')).toBe('Rohan'); expect(m.name('database')).toBe('Karan')
    expect(scenarioRunKey(m.scenario)).toBe('opd-form-says-saved:1:1000:learner:')
  })

  it('shows the scenario in the left panel during the run: title, role, time box, the task with Submit, the guide and the hints', () => {
    const html = left(frontendRun({ hints: 1 }))
    expect(html).toContain('aria-label="Scenario"')
    expect(html).toContain('The form says it saved'); expect(html).toContain('You play: Frontend engineer'); expect(html).toContain('time box 25 min'); expect(html).toContain('#incident-frontdesk')
    expect(html).toContain('Fix: the pages report a refused request as a success'); expect(html).toContain('YOUR TURN'); expect(html).toMatch(/<button[^>]*>Submit<\/button>/)
    expect(html).toContain('/api/projects/p1/tasks/h1/doc')
    expect(html).toContain('Step 3 of 8'); expect(html).toContain('2 of 8 done')
    expect(html).toMatch(/Hints used: <span[^>]*>1<\/span>/)
    for (const live of ['GOAL', 'STACK PRESET', 'CHOOSE A RECORDED BUILD', 'Build it', 'FINISH MY PROJECT', 'PM BOARD', 'TRY A FAMOUS APP', 'YOU PLAY']) expect(html).not.toContain(live)
  })

  it('opens the IDE of the frontend role and highlights the files of a page', () => {
    expect(ideRole(frontendRun().tasks, ['frontend'])).toBe('frontend')
    expect(languageFor('static/shell.js')).toBe('javascript'); expect(languageFor('tests/ui/refusals.mjs')).toBe('javascript')
    expect(languageFor('static/style.css')).toBe('css'); expect(languageFor('static/index.html')).toBe('html'); expect(languageFor('tests/regression/test_regression_refusals.py')).toBe('python')
  })
})

describe('the recordings of the three scenarios in Demo mode', () => {
  const rec = (name: string, title: string): RecordingMeta => ({ name, goal: title, ok: true, seconds: 190, events: 3000, title, kind: 'scenario', variant: name.endsWith('weak') ? 'weak' : 'strong' })
  const SIMS = [rec('simulation-form-says-saved-weak', 'Simulation: The form says it saved (weak)'), rec('simulation-double-bookings-strong', 'Simulation: Double bookings (strong)'), rec('simulation-form-says-saved-strong', 'Simulation: The form says it saved (strong)'), rec('simulation-bookings-down-strong', 'Simulation: Bookings are down (strong)')]

  it('lists them in the scenarios\' order, the first scenario staying the default', () => {
    expect(demosFor(SIMS, 'simulation').map((r) => r.name)).toEqual(['simulation-bookings-down-strong', 'simulation-double-bookings-strong', 'simulation-form-says-saved-strong', 'simulation-form-says-saved-weak'])
    expect(pickDefault(SIMS, 'simulation')).toBe('simulation-bookings-down-strong')
  })
})
