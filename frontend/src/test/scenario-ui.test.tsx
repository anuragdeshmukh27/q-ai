import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { SessionTimer } from '../components/TopBar'
import { ScenarioPicker } from '../components/ScenarioPicker'
import { AgentChat, Channel } from '../dock/AgentChat'
import { GuidePanel } from '../dock/GuidePanel'
import { OfficeModel, type AgentInfo, type QEvent } from '../model'
import type { GuideView, ScenarioInfo } from '../scenario'

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['database', 'Karan'], ['qa', 'Ananya']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))

let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

const CARD: ScenarioInfo = { id: 'opd-bookings-down', title: 'Production incident: Bookings are down', summary: 'The front desk of a hospital OPD cannot book appointments.', role: 'backend', minutes: 25, level: 'Intermediate', channel: '#incident-opd', tests: 3, teammates: ['qa', 'architect', 'database', 'planner'] }

function session() {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  m.apply(ev('scenario_started', { scenario: CARD.id, title: CARD.title, role: 'backend', minutes: 25, channel: { id: 'incident-opd', name: '#incident-opd' }, teammates: CARD.teammates, started_at: 1000 }))
  return m
}
const say = (m: OfficeModel, id: string, from: string, text: string, rest: Record<string, unknown> = {}) =>
  m.apply(ev('channel_message', { id, channel: 'incident-opd', from, text, source: from === 'human' ? 'learner' : 'scripted', t: 5, ...rest }))

describe('the scenario picker', () => {
  it('shows one card with what the learner needs to choose', () => {
    const html = renderToStaticMarkup(<ScenarioPicker scenarios={[CARD]} busy={false} onStart={() => {}} />)
    expect(html).toContain('SCENARIOS'); expect(html).toContain('Production incident: Bookings are down')
    expect(html).toContain('The front desk of a hospital OPD cannot book appointments.'); expect(html).toContain('You play: Backend engineer')
    expect(html).toContain('about 25 min'); expect(html).toContain('#incident-opd'); expect(html).toContain('Start the incident')
    expect(html).not.toContain('disabled=""')
  })

  it('disables the start button while a build is starting, and shows nothing without scenarios', () => {
    expect(renderToStaticMarkup(<ScenarioPicker scenarios={[CARD]} busy onStart={() => {}} />)).toMatch(/<button[^>]*disabled[^>]*>Starting…/)
    expect(renderToStaticMarkup(<ScenarioPicker scenarios={[]} busy={false} onStart={() => {}} />)).toBe('')
  })
})

describe('the incident channel in Agent Chat', () => {
  it('shows who said what, when, and marks hints', () => {
    const m = session()
    say(m, 'C001', 'qa', "Booking is down. The server log says: TypeError: add_appointment() got an unexpected keyword argument 'slot_time'.", { t: 3 })
    say(m, 'C002', 'human', 'Karan, what changed on Monday?', { to: ['database'], t: 65 })
    say(m, 'C003', 'database', 'Migration 0007 renamed slot_time to slot_at.', { source: 'live', reply_to: 'C002', hint: true, t: 69 })
    say(m, 'C004', 'database', 'That was my migration.', { source: 'fallback', reply_to: 'C002', hint: true, t: 70 })
    const html = renderToStaticMarkup(<AgentChat model={m} onPost={async () => {}} />)
    expect(html).toContain('#incident-opd'); expect(html).toContain('All traffic'); expect(html).toContain('Hints used:')
    expect(html).toContain('Ananya'); expect(html).toContain('TypeError: add_appointment() got an unexpected keyword argument'); expect(html).toContain('00:03')
    expect(html).toContain('You'); expect(html).toContain('@Karan'); expect(html).toContain('01:05')
    expect(html.match(/>hint</g)?.length).toBe(2); expect(html).toContain('AI reply'); expect(html).toContain('scripted reply')
  })

  it('has a message box with the teammates you can ask', () => {
    const html = renderToStaticMarkup(<Channel model={session()} onPost={async () => {}} replay={false} />)
    expect(html).toContain('is quiet')
    for (const name of ['Everyone', 'Ananya', 'Aarav', 'Karan', 'Priya']) expect(html).toContain(`>${name}</option>`)
    expect(html).not.toContain('>Rohan</option>') // you are Rohan
    expect(html).toContain('aria-label="Message"'); expect(html).toContain('Post an update, or ask Ananya, Aarav, Karan, Priya'); expect(html).toMatch(/<button[^>]*disabled[^>]*>Send/)
  })

  it('shows the count of hints from the log', () => {
    const m = session()
    m.apply(ev('session_event', { id: 'E010', t: 70, kind: 'hint_given', n: 3 }))
    expect(renderToStaticMarkup(<AgentChat model={m} onPost={async () => {}} />)).toMatch(/Hints used: <span[^>]*>3</)
  })

  it('is the old traffic view when the build is not a scenario', () => {
    const m = new OfficeModel()
    m.setRoster(ROSTER)
    const html = renderToStaticMarkup(<AgentChat model={m} />)
    expect(html).toContain('Messages between employees'); expect(html).not.toContain('Hints used')
  })
})

describe("Priya's guide in the IDE panel", () => {
  const guide = (current: string | null, done: number): GuideView => ({
    task: 'h1', current, done,
    steps: [
      { id: 'a', title: 'Reproduce it', text: 'Press Run tests.', state: done > 0 ? 'done' : 'current' },
      { id: 'b', title: 'Open the failing route', text: 'Open backend/api/appointments.py.', state: done > 1 ? 'done' : done === 1 ? 'current' : 'todo' },
      { id: 'c', title: 'Submit for review', text: 'Press Submit.', state: done > 2 ? 'done' : done === 2 ? 'current' : 'todo' },
    ],
  })

  it('opens the current step and leaves the others as titles', () => {
    const html = renderToStaticMarkup(<GuidePanel guide={guide('b', 1)} />)
    expect(html).toContain("Priya&#x27;s guide"); expect(html).toContain('step 2 of 3')
    expect(html).toContain('1. Reproduce it'); expect(html).toContain('2. Open the failing route'); expect(html).toContain('Open backend/api/appointments.py.')
    expect(html).not.toContain('Press Run tests.'); expect(html).not.toContain('Press Submit.')
    expect(html).toContain('aria-current="step"'); expect(html.match(/aria-current/g)?.length).toBe(1)
    expect(html).toContain('aria-label="done"'); expect(html).toContain('aria-label="current step"'); expect(html).toContain('aria-label="not yet"')
  })

  it('says so when every step is done', () => {
    const html = renderToStaticMarkup(<GuidePanel guide={guide(null, 3)} />)
    expect(html).toContain('all steps done'); expect(html).not.toContain('aria-current')
  })
})

describe('the session timer in the top bar', () => {
  it('shows minutes and seconds since the incident started', () => {
    const m = session()
    const html = renderToStaticMarkup(<SessionTimer session={m.scenario!} nowMs={1_252_000} />)
    expect(html).toContain('SESSION'); expect(html).toContain('04:12'); expect(html).not.toContain('ended')
  })

  it('stops at the end of the session', () => {
    const m = session()
    m.apply(ev('session_event', { id: 'E050', t: 600, kind: 'session_finished', ok: true }, 1600))
    const html = renderToStaticMarkup(<SessionTimer session={m.scenario!} nowMs={9_000_000} />)
    expect(html).toContain('10:00'); expect(html).toContain('ended')
  })
})
