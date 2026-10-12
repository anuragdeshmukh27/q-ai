import { describe, expect, it } from 'vitest'
import { OfficeModel, type AgentInfo, type QEvent, type Visual } from '../model'
import { formatClock, recipients, sessionSeconds, unreadCount, type ChannelMsg } from '../scenario'

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['frontend', 'Meera'], ['database', 'Karan'], ['integrator', 'Ishaan'], ['qa', 'Ananya'], ['reviewer', 'Vikram']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))

let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

function setup() {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  const seen: Visual[] = []
  m.onVisual((v) => seen.push(v))
  return { m, seen }
}

const STARTED = { scenario: 'opd-bookings-down', title: 'Production incident: Bookings are down', role: 'backend', minutes: 25, channel: { id: 'incident-opd', name: '#incident-opd' }, teammates: ['qa', 'architect', 'database', 'planner'], started_at: 1000 }
const msg = (id: string, from: string, text: string, rest: Record<string, unknown> = {}) => ev('channel_message', { id, channel: 'incident-opd', from, text, source: from === 'human' ? 'learner' : 'scripted', t: 3, ...rest })
const toasts = (seen: Visual[]) => seen.filter((v) => v.kind === 'toast') as Extract<Visual, { kind: 'toast' }>[]

describe('the session of a scenario in the office model', () => {
  it('learns the scenario, its channel and its teammates from scenario_started', () => {
    const { m } = setup()
    expect(m.scenario).toBeNull()
    m.apply(ev('scenario_started', STARTED))
    expect(m.scenario).toEqual({ id: 'opd-bookings-down', title: 'Production incident: Bookings are down', role: 'backend', minutes: 25, channelId: 'incident-opd', channelName: '#incident-opd', teammates: ['qa', 'architect', 'database', 'planner'], startedAt: 1000, endedAt: null })
    expect(m.ticker).toContain('Production incident')
  })

  it('keeps the channel messages in order, once, and tells the learner about the ones from the team', () => {
    const { m, seen } = setup()
    m.apply(ev('scenario_started', STARTED))
    const report = msg('C001', 'qa', 'Booking is down: TypeError', { source: 'scripted', t: 3 })
    m.apply(report)
    m.apply(report) // a reconnect replays it
    m.apply(msg('C002', 'human', 'Karan, what changed?', { to: ['database'], t: 70 }))
    m.apply(msg('C003', 'database', 'Migration 0007 renamed it.', { source: 'live', reply_to: 'C002', hint: true, t: 75 }))
    expect(m.channel.map((c) => c.id)).toEqual(['C001', 'C002', 'C003'])
    expect(m.channel[1]).toMatchObject({ from: 'human', source: 'learner', to: ['database'], hint: false })
    expect(m.channel[2]).toMatchObject({ from: 'database', source: 'live', replyTo: 'C002', hint: true, t: 75 })
    const t = toasts(seen)
    expect(t.map((x) => x.title)).toEqual(['Ananya in #incident-opd', 'Karan in #incident-opd']) // nothing for your own post
    expect(seen.filter((v) => v.kind === 'say').map((v) => (v as { agent: string }).agent)).toEqual(['qa', 'database'])
  })

  it('shows the guide as the last guide_progress describes it', () => {
    const { m } = setup()
    const steps = [{ id: 'a', title: 'Reproduce it', text: 'Run the tests', state: 'done' }, { id: 'b', title: 'Open the route', text: 'Open the file', state: 'current' }, { id: 'c', title: 'Submit', text: 'Press it', state: 'todo' }]
    m.apply(ev('guide_progress', { task: 'h1', current: 'b', done: 1, steps }))
    expect(m.guide).toMatchObject({ task: 'h1', current: 'b', done: 1 })
    expect(m.guide!.steps.map((s) => s.state)).toEqual(['done', 'current', 'todo'])
    m.apply(ev('guide_progress', { task: 'h1', current: null, done: 3, steps: steps.map((s) => ({ ...s, state: 'done' })) }))
    expect(m.guide!.current).toBeNull()
  })

  it('counts the hints from the session log', () => {
    const { m } = setup()
    expect(m.hints).toBe(0)
    m.apply(ev('session_event', { id: 'E010', t: 70, kind: 'hint_given', n: 1 }))
    m.apply(ev('session_event', { id: 'E014', t: 99, kind: 'hint_given', n: 2 }))
    m.apply(ev('session_event', { id: 'E015', t: 100, kind: 'file_opened', path: 'x.py' }))
    expect(m.hints).toBe(2)
  })

  it('stops the timer when the session ends, however it ends', () => {
    const a = setup().m
    a.apply(ev('scenario_started', STARTED))
    a.apply(ev('session_event', { id: 'E090', t: 600, kind: 'session_finished', ok: true }, 1600))
    expect(a.scenario!.endedAt).toBe(1600)
    const b = setup().m
    b.apply(ev('scenario_started', STARTED))
    b.apply(ev('project_done', { ok: false, seconds: 300, problems: ['stopped by you'] }, 1300)) // stopped before it was fixed
    expect(b.scenario!.endedAt).toBe(1300)
    b.apply(ev('session_event', { id: 'E091', t: 301, kind: 'session_finished', ok: false }, 1301))
    expect(b.scenario!.endedAt).toBe(1301) // the log's own end is the one that counts
  })

  it('forgets the session on reset (the next build starts clean)', () => {
    const { m } = setup()
    m.apply(ev('scenario_started', STARTED))
    m.apply(msg('C001', 'qa', 'hi'))
    m.apply(ev('guide_progress', { task: 'h1', current: 'a', done: 0, steps: [] }))
    m.apply(ev('session_event', { id: 'E010', t: 70, kind: 'hint_given', n: 1 }))
    m.reset()
    expect([m.scenario, m.guide, m.channel.length, m.hints]).toEqual([null, null, 0, 0])
  })

  it('changes nothing for a build that is not a scenario', () => {
    const { m, seen } = setup()
    m.apply(ev('project_created', { slug: 'calc', goal: 'g', preset: 'fastapi-vanilla', path: '/x' }))
    m.apply(ev('project_done', { ok: true, seconds: 5, problems: [] }))
    expect([m.scenario, m.guide, m.channel.length, m.hints]).toEqual([null, null, 0, 0])
    expect(toasts(seen).every((t) => !t.title.includes('#'))).toBe(true)
  })
})

describe('the helpers of the scenario UI', () => {
  it('formats the session clock', () => {
    expect([0, 3, 63, 599, 3600, 3725, -5, 59.9].map(formatClock)).toEqual(['00:00', '00:03', '01:03', '09:59', '1:00:00', '1:02:05', '00:00', '00:59'])
  })

  it('runs the timer from the start to now, and freezes it at the end', () => {
    const running = { startedAt: 1000, endedAt: null }
    expect(sessionSeconds(running, 1252_000)).toBe(252)
    expect(sessionSeconds({ startedAt: 1000, endedAt: 1600 }, 9_999_000)).toBe(600)
    expect(sessionSeconds({ startedAt: 1000, endedAt: null }, 500_000)).toBe(0) // a clock that is behind never shows a negative time
    expect(sessionSeconds(null, 1)).toBe(0)
  })

  it('counts the team messages you have not seen, never your own', () => {
    const mk = (id: string, source: ChannelMsg['source']): ChannelMsg => ({ id, from: 'qa', text: '', source, t: 0, to: [], replyTo: '', hint: false })
    const channel = [mk('1', 'scripted'), mk('2', 'learner'), mk('3', 'live'), mk('4', 'fallback')]
    expect([unreadCount(channel, 0), unreadCount(channel, 2), unreadCount(channel, 4), unreadCount(channel, 99)]).toEqual([3, 2, 0, 0])
  })

  it('lists the teammates in the scenario order, by their names', () => {
    const { m } = setup()
    expect(recipients(['database', 'qa'], (id) => m.name(id))).toEqual([{ id: 'database', name: 'Karan' }, { id: 'qa', name: 'Ananya' }])
    expect(recipients([], (id) => id)).toEqual([])
  })
})
