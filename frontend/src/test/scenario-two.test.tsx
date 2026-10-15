import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RecordingMeta } from '../api'
import { ScenarioPicker } from '../components/ScenarioPicker'
import { card, demosFor, pickDefault } from '../demos'
import { OfficeModel, type AgentInfo, type QEvent } from '../model'
import type { ScenarioInfo } from '../scenario'

const ONE: ScenarioInfo = { id: 'opd-bookings-down', title: 'Production incident: Bookings are down', summary: 'The front desk of a hospital OPD cannot book appointments.', role: 'backend', minutes: 25, level: 'Intermediate', channel: '#incident-opd', tests: 3, teammates: ['qa', 'architect', 'database', 'planner'] }
const TWO: ScenarioInfo = { id: 'opd-double-bookings', title: 'Double bookings', summary: 'Two patients keep being booked with the same doctor at the same time.', role: 'database', minutes: 30, level: 'Advanced', channel: '#incident-duplicates', tests: 5, teammates: ['qa', 'architect', 'backend', 'planner'] }

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['database', 'Karan'], ['qa', 'Ananya']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))
let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}): QEvent => ({ seq: seq++, ts: 1000, type, ...rest })

const picker = (scenarios: ScenarioInfo[], busy = false) => renderToStaticMarkup(<ScenarioPicker scenarios={scenarios} busy={busy} onStart={() => {}} onWatch={() => {}} />)
const count = (html: string, text: string) => html.split(text).length - 1

describe('the scenario picker with two scenarios', () => {
  it('shows both cards with the role, the level and the time, and a Start, a Strong run and a Weak run on each', () => {
    const html = picker([ONE, TWO])
    expect(html).toContain('Production incident: Bookings are down'); expect(html).toContain('Double bookings')
    expect(html).toContain('You play: Backend engineer'); expect(html).toContain('You play: Database engineer')
    expect(html).toContain('about 25 min'); expect(html).toContain('about 30 min'); expect(html).toContain('Intermediate'); expect(html).toContain('Advanced')
    expect(html).toContain('#incident-opd'); expect(html).toContain('#incident-duplicates')
    expect(count(html, 'Start the incident')).toBe(2); expect(count(html, '>Strong run<')).toBe(2); expect(count(html, '>Weak run<')).toBe(2)
    expect(html.indexOf('Bookings are down')).toBeLessThan(html.indexOf('Double bookings'))
    expect(html).not.toContain('old name')  // the tooltips say nothing about one scenario's story
  })

  it('locks both cards while a run is starting', () => {
    const html = picker([ONE, TWO], true)
    expect(count(html, 'Starting…')).toBe(2)
    expect(html.match(/<button[^>]*disabled=""[^>]*>/g)?.length).toBe(6)
  })
})

describe('playing the database engineer', () => {
  it('puts the learner in Karan\'s seat: the desk reads You and Rohan is a teammate', () => {
    const m = new OfficeModel()
    m.setRoster(ROSTER)
    m.setHumanRoles(['database'])  // what starting the scenario does (useQ.startScenario)
    m.apply(ev('scenario_started', { scenario: TWO.id, title: TWO.title, role: 'database', minutes: 30, channel: { id: 'incident-duplicates', name: '#incident-duplicates' }, teammates: TWO.teammates, started_at: 1000, kind: 'learner', variant: '' }))
    expect(m.scenario?.role).toBe('database'); expect(m.scenario?.channelName).toBe('#incident-duplicates'); expect(m.scenario?.teammates).toEqual(['qa', 'architect', 'backend', 'planner'])
    expect(m.name('database')).toBe('You'); expect(m.name('backend')).toBe('Rohan')
  })
})

describe('the recordings of both scenarios in Demo mode', () => {
  const rec = (name: string, title: string): RecordingMeta => ({ name, goal: title, ok: true, seconds: 190, events: 3000, title, kind: 'scenario', variant: name.endsWith('weak') ? 'weak' : 'strong' })
  const SIMS = [rec('simulation-double-bookings-weak', 'Simulation: Double bookings (weak)'), rec('simulation-double-bookings-strong', 'Simulation: Double bookings (strong)'), rec('simulation-bookings-down-strong', 'Simulation: Bookings are down (strong)')]
  const build: RecordingMeta = { name: 'calculator-fault', goal: 'Build a calculator', ok: true, seconds: 100, events: 10 }

  it('lists the simulation recordings of both scenarios in a fixed order and leaves the builds alone', () => {
    expect(demosFor([...SIMS, build], 'simulation').map((r) => r.name)).toEqual(['simulation-bookings-down-strong', 'simulation-double-bookings-strong', 'simulation-double-bookings-weak'])
    expect(demosFor([...SIMS, build], 'supervised').map((r) => r.name)).toEqual(['calculator-fault'])
    expect(pickDefault([...SIMS, build], 'simulation')).toBe('simulation-bookings-down-strong')
    expect(demosFor([build, SIMS[1]], 'simulation').map((r) => card(r).simulation)).toEqual([true])
  })
})
