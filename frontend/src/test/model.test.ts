import { describe, expect, it } from 'vitest'
import { OfficeModel, type AgentInfo, type QEvent, type Visual } from '../model'

const ROSTER: AgentInfo[] = ['architect', 'planner', 'backend', 'frontend', 'integrator', 'qa', 'reviewer'].map((id, i) => ({
  id, name: id.toUpperCase(), role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))

let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}): QEvent => ({ seq: seq++, ts: 0, type, ...rest })

function setup() {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  const seen: Visual[] = []
  m.onVisual((v) => seen.push(v))
  return { m, seen }
}

describe('office model', () => {
  it('tracks agent state, iteration, thoughts and files from events', () => {
    const { m } = setup()
    m.apply(ev('agent_state', { agent: 'backend', state: 'typing' }))
    m.apply(ev('iteration', { agent: 'backend', n: 2, max: 8 }))
    m.apply(ev('agent_thought', { agent: 'backend', text: 'writing the router', model: 'qwen2.5-coder:7b' }))
    m.apply(ev('file_changed', { agent: 'backend', path: 'backend/api/calc.py' }))
    m.apply(ev('file_changed', { agent: 'backend', path: 'backend/api/calc.py' }))
    const a = m.agents.get('backend')!
    expect([a.state, a.iteration, a.maxIterations, a.thought, a.model, a.files]).toEqual(['typing', 2, 8, 'writing the router', 'qwen2.5-coder:7b', ['backend/api/calc.py']])
    expect(m.activeCount).toBe(1)
  })

  it('turns hand-offs into walks: planner assigns, reviewer answers the owner, QA files bugs to the owner', () => {
    const { m, seen } = setup()
    m.apply(ev('plan_created', { tasks: [{ id: 't1', title: 'router', owner: 'backend', depends_on: [], files: [] }] }))
    m.apply(ev('task_assigned', { agent: 'backend', task: 't1', title: 'router' }))
    m.apply(ev('review_result', { agent: 'reviewer', task: 't1', verdict: 'REQUEST_CHANGES', summary: 'x', items: [{ problem: 'innerHTML is risky' }] }))
    m.apply(ev('bug_filed', { agent: 'qa', bug: 1, owner: 'backend', title: 'wrong sum' }))
    const walks = seen.filter((v) => v.kind === 'message') as Extract<Visual, { kind: 'message' }>[]
    expect(walks.map((w) => [w.from, w.to])).toEqual([['planner', 'backend'], ['reviewer', 'backend'], ['qa', 'backend']])
    expect(walks[1].tone).toBe('warn')
    expect(walks[2].tone).toBe('bad')
  })

  it('does not act out history that is only catching up', () => {
    const { m, seen } = setup()
    m.apply(ev('task_assigned', { agent: 'backend', task: 't1', title: 'router' }), false)
    expect(seen).toEqual([])
    expect(m.agents.get('backend')!.task?.id).toBe('t1')
  })

  it('celebrates when the build succeeds and reports a stop plainly when it fails', () => {
    const a = setup()
    a.m.apply(ev('project_done', { ok: true, seconds: 185, app_url: 'http://127.0.0.1:9100' }))
    expect(a.m.finished).toEqual({ ok: true, seconds: 185 })
    expect(a.m.appUrl).toBe('http://127.0.0.1:9100')
    expect(a.m.agents.get('qa')!.state).toBe('celebrating')
    expect(a.seen.some((v) => v.kind === 'celebrate')).toBe(true)
    const b = setup()
    b.m.apply(ev('project_done', { ok: false, seconds: 9, problems: ['tests failed'] }))
    expect(b.seen.some((v) => v.kind === 'celebrate')).toBe(false)
    expect(b.seen.find((v) => v.kind === 'toast')).toMatchObject({ level: 'bad' })
  })

  it('shows escalations and errors as toasts with no stack traces', () => {
    const { m, seen } = setup()
    m.apply(ev('escalation', { agent: 'reviewer', reason: 'review_unresolved', detail: 'static/app.js: innerHTML' }))
    m.apply(ev('error', { agent: 'backend', message: 'model returned invalid output' }))
    const toasts = seen.filter((v) => v.kind === 'toast') as Extract<Visual, { kind: 'toast' }>[]
    expect(toasts.map((t) => t.level)).toEqual(['warn', 'bad'])
    expect(seen.filter((v) => v.kind === 'alert').length).toBe(2)
  })

  it('reset keeps the team but forgets the project', () => {
    const { m } = setup()
    m.apply(ev('project_created', { slug: 'calc', goal: 'g', preset: 'fastapi-vanilla' }))
    m.apply(ev('agent_state', { agent: 'qa', state: 'testing' }))
    m.reset()
    expect(m.order.length).toBe(ROSTER.length)
    expect(m.agents.get('qa')!.state).toBe('idle')
    expect(m.slug).toBe('')
  })
})
