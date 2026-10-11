import { describe, expect, it } from 'vitest'
import { MODES, OfficeModel, type AgentInfo, type QEvent, type Visual } from '../model'

const ROSTER: AgentInfo[] = ['architect', 'planner', 'database', 'backend', 'frontend', 'integrator', 'qa', 'reviewer'].map((id, i) => ({
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

const toasts = (seen: Visual[]) => seen.filter((v) => v.kind === 'toast') as Extract<Visual, { kind: 'toast' }>[]
const PLAN = { tasks: [
  { id: 't1', title: 'DB functions', owner: 'database', depends_on: [], files: ['database/x.py'], assignee: 'human' },
  { id: 't2', title: 'API router', owner: 'backend', depends_on: ['t1'], files: ['backend/api/x.py'] },
] }
const ASSIGNED = { agent: 'database', task: 't1', title: 'DB functions', owner: 'database', files: ['database/x.py'], tests: [], worktree: 'C:/ws/app/.worktrees/database', doc: '.q/tasks/t1.md' }

describe('simulation mode in the office model', () => {
  it('has the simulation mode next to the other three', () => {
    expect([...MODES]).toEqual(['assisted', 'supervised', 'autonomous', 'simulation'])
  })

  it('labels the desks the person plays "You", and gives the real names back on reset', () => {
    const { m } = setup()
    m.apply(ev('simulation_started', { human_roles: ['database', 'backend'] }))
    expect([m.agents.get('database')!.name, m.agents.get('backend')!.name, m.agents.get('frontend')!.name]).toEqual(['You', 'You', 'FRONTEND'])
    expect(m.name('database')).toBe('You')
    m.reset()
    expect([m.agents.get('database')!.name, m.agents.get('backend')!.name]).toEqual(['DATABASE', 'BACKEND'])
    expect(m.humanRoles.size).toBe(0)
  })

  it('renames from the role picker before a build starts and survives a roster reload', () => {
    const { m } = setup()
    m.setHumanRoles(['backend'])
    expect(m.agents.get('backend')!.name).toBe('You')
    m.setRoster(ROSTER) // the roster is fetched again: the server still says "BACKEND"
    expect(m.agents.get('backend')!.name).toBe('You')
    m.setHumanRoles(['frontend'])
    expect([m.agents.get('backend')!.name, m.agents.get('frontend')!.name]).toEqual(['BACKEND', 'You'])
    m.setHumanRoles([])
    expect(m.agents.get('frontend')!.name).toBe('FRONTEND')
  })

  it('marks the human task, keeps where the person works through a re-plan, and tells them it is their turn', () => {
    const { m, seen } = setup()
    m.apply(ev('plan_created', PLAN))
    expect(m.tasks.map((t) => t.assignee)).toEqual(['human', undefined])
    m.apply(ev('human_task_assigned', ASSIGNED))
    expect(m.tasks[0]).toMatchObject({ assignee: 'human', worktree: ASSIGNED.worktree, doc: ASSIGNED.doc })
    const t = toasts(seen)[0]
    expect(t.level).toBe('info')
    expect(t.title).toContain('DB functions')
    expect(t.text).toContain('Submit')
    expect(m.ticker).toContain('t1 is yours')
    m.apply(ev('plan_created', { tasks: PLAN.tasks, replan: true }))
    expect(m.tasks[0]).toMatchObject({ worktree: ASSIGNED.worktree, doc: ASSIGNED.doc, assignee: 'human' })
  })

  it('labels the desk "You" from the task alone (a replay of a recording without the start event)', () => {
    const { m } = setup()
    m.apply(ev('plan_created', PLAN))
    m.apply(ev('human_task_assigned', ASSIGNED))
    expect(m.agents.get('database')!.name).toBe('You')
  })

  it('a red submit says which tests failed and that the task stays open; an accepted one says it is merged next', () => {
    const { m, seen } = setup()
    m.apply(ev('human_submit_result', { agent: 'database', task: 't1', ok: false, stage: 'tests', failed: ['tests/test_db.py::test_add', 'tests/test_db.py::test_list'], summary: '2 failed, 1 passed' }))
    const bad = toasts(seen)[0]
    expect(bad.level).toBe('bad')
    expect(bad.text).toContain('2 failed, 1 passed')
    expect(bad.text).toContain('test_add, test_list')
    expect(bad.text).toContain('stays open')
    m.apply(ev('human_submit_result', { agent: 'database', task: 't1', ok: true, stage: 'accepted', failed: [], summary: '3 passed' }))
    const good = toasts(seen)[1]
    expect(good).toMatchObject({ level: 'good', title: 't1 accepted' })
    expect(good.text).toContain('Integrator')
  })

  it('shows the Reviewer\'s items to the person', () => {
    const { m, seen } = setup()
    m.apply(ev('review_feedback', { agent: 'database', task: 't1', round: 1, summary: 's', items: [{ file: 'database/x.py', problem: 'list is oldest first' }, { file: 'a.py', problem: 'b' }, { file: 'c.py', problem: 'd' }] }))
    const t = toasts(seen)[0]
    expect(t.level).toBe('warn')
    expect(t.title).toContain('t1')
    expect(t.title).toContain('(1)')
    expect(t.text).toContain('database/x.py: list is oldest first')
    expect(t.text).not.toContain('c.py')
  })

  it('replays the same way: history that is only catching up changes the state but acts nothing out', () => {
    const { m, seen } = setup()
    m.apply(ev('simulation_started', { human_roles: ['database'] }), false)
    m.apply(ev('plan_created', PLAN), false)
    m.apply(ev('human_task_assigned', ASSIGNED), false)
    m.apply(ev('human_submit_result', { agent: 'database', task: 't1', ok: false, stage: 'tests', failed: [], summary: 'x' }), false)
    m.apply(ev('review_feedback', { agent: 'database', task: 't1', round: 1, summary: 's', items: [] }), false)
    expect(seen).toEqual([])
    expect(m.agents.get('database')!.name).toBe('You')
    expect(m.tasks[0].worktree).toBe(ASSIGNED.worktree)
  })

  it('old recordings are unaffected: no assignee, no renames', () => {
    const { m } = setup()
    m.apply(ev('plan_created', { tasks: [{ id: 't1', title: 'router', owner: 'backend', depends_on: [], files: [] }] }))
    m.apply(ev('task_assigned', { agent: 'backend', task: 't1', title: 'router' }))
    expect(m.tasks[0].assignee).toBeUndefined()
    expect([...m.agents.values()].some((a) => a.name === 'You')).toBe(false)
  })
})
