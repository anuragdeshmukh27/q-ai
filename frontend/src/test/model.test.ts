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

  it('an approval toast is rewritten as resolved when the recording answers it (replay of an old decision)', () => {
    const { m, seen } = setup()
    m.apply(ev('approval_needed', { id: 'a1', agent: 'reviewer', kind: 'review_unresolved', summary: 'merge t4 with open review items', details: { items: 'x' } }))
    expect(m.approvals).toMatchObject([{ id: 'a1', state: 'pending' }])
    m.apply(ev('approval_resolved', { id: 'a1', agent: 'reviewer', kind: 'review_unresolved', approve: true, by: 'human' }))
    expect(m.approvals).toMatchObject([{ id: 'a1', state: 'approved', by: 'human' }])
    const toast = seen.find((v) => v.kind === 'toast') as Extract<Visual, { kind: 'toast' }>
    const update = seen.find((v) => v.kind === 'toast_update') as Extract<Visual, { kind: 'toast_update' }>
    expect(toast.key).toBe('approval:a1')
    expect(update).toMatchObject({ key: 'approval:a1', level: 'good' })
    expect(update.title).toContain('approved')
    expect(update.text).toContain('you')
  })

  it('keeps approvals, messages and terminal lines even when history is replayed as a catch-up burst', () => {
    const { m, seen } = setup()
    m.apply(ev('plan_created', { tasks: [{ id: 't1', title: 'router', owner: 'backend', depends_on: [], files: [] }] }), false)
    m.apply(ev('task_assigned', { agent: 'backend', task: 't1', title: 'router' }), false)
    m.apply(ev('tool_call', { agent: 'backend', tool: 'run_tests', args: {}, ok: false, output: '1 failed\nassert 1 == 2' }), false)
    m.apply(ev('tool_call', { agent: 'backend', tool: 'write_file', args: { path: 'a.py' }, ok: true, output: 'wrote' }), false)
    m.apply(ev('approval_needed', { id: 'z', agent: 'qa', kind: 'x', summary: 's', details: {} }), false)
    expect(seen).toEqual([])
    expect(m.messages.map((x) => [x.from, x.to])).toEqual([['planner', 'backend']])
    expect(m.terminal.map((l) => [l.kind, l.text])).toEqual([['cmd', '$ pytest'], ['bad', '1 failed'], ['bad', 'assert 1 == 2']])
    expect(m.approvals).toHaveLength(1)
  })

  it('derives the PM board from the plan, reviews, merges and QA', () => {
    const { m } = setup()
    const board = () => Object.fromEntries(m.board.map((a) => [a.name, `${a.done}/${a.total} ${a.state}`]))
    m.apply(ev('architecture_ready', { endpoints: 2, tables: 1 }))
    m.apply(ev('plan_created', { tasks: [
      { id: 't1', title: 'a', owner: 'backend', depends_on: [], files: [] },
      { id: 't2', title: 'b', owner: 'frontend', depends_on: [], files: [] },
    ] }))
    m.apply(ev('project_progress', { done: 1, total: 2, percent: 50, tasks: { t1: 'done', t2: 'running' } }))
    m.apply(ev('review_result', { agent: 'reviewer', task: 't1', verdict: 'PASS', summary: '', items: [] }))
    m.apply(ev('merge_result', { agent: 'integrator', branch: 'agent/backend', ok: true, summary: '3 passed' }))
    expect(board()).toMatchObject({ Architecture: '1/1 done', Backend: '1/1 done', Frontend: '0/1 working', Integration: '1/2 working', Review: '1/2 working', QA: '0/1 waiting' })
    m.apply(ev('bug_filed', { agent: 'qa', bug: 1, owner: 'backend', title: 'x' }))
    m.apply(ev('test_result', { agent: 'qa', passed: false, failed: ['t'], summary: '1 failed' }))
    expect(board().QA).toBe('0/1 problem')
    m.apply(ev('bug_fixed', { agent: 'backend', bug: 1, owner: 'backend' }))
    m.apply(ev('test_result', { agent: 'qa', passed: true, failed: [], summary: '25 passed' }))
    expect(board().QA).toBe('1/1 done')
  })

  it('records file diffs per path and bumps filesVersion so the explorer and git graph refetch', () => {
    const { m } = setup()
    const v = m.filesVersion
    m.apply(ev('file_changed', { agent: 'backend', path: 'a.py', diff: '--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+x', created: true }))
    m.apply(ev('merge_result', { agent: 'integrator', branch: 'agent/backend', ok: true, summary: '' }))
    expect(m.changes.get('a.py')).toHaveLength(1)
    expect(m.filesVersion).toBeGreaterThan(v + 1)
  })
  it('puts a finished project back in progress for an Ask-employee request and celebrates only the people who did the work', () => {
    const { m, seen } = setup()
    m.apply(ev('project_done', { ok: true, seconds: 120 }))
    expect(m.finished?.ok).toBe(true)
    expect([...m.agents.values()].every((a) => a.state === 'celebrating')).toBe(true)
    m.apply(ev('project_resumed', { agent: 'backend', task: 'r1', message: 'Rohan is working on a request' }))
    expect(m.finished).toBeNull() // "in progress" again
    expect([...m.agents.values()].every((a) => a.state === 'idle')).toBe(true) // nobody keeps celebrating
    m.apply(ev('agent_state', { agent: 'backend', state: 'typing' }))
    expect(m.activeCount).toBe(1)
    seen.length = 0
    m.apply(ev('project_done', { ok: true, seconds: 20, request: true, involved: ['backend'] }))
    expect(m.agents.get('backend')!.state).toBe('celebrating')
    expect(['frontend', 'qa', 'planner'].map((id) => m.agents.get(id)!.state)).toEqual(['idle', 'idle', 'idle'])
    expect(seen.some((v) => v.kind === 'toast' && v.title === 'Request complete')).toBe(true)
  })

  it('celebrates the whole office for a build but only the involved people (as a small burst) for an Ask-employee request', () => {
    const { m, seen } = setup()
    m.apply(ev('project_done', { ok: true, seconds: 100 }))
    expect(seen.find((v) => v.kind === 'celebrate')).toEqual({ kind: 'celebrate', agents: undefined })
    seen.length = 0
    m.apply(ev('project_done', { ok: true, seconds: 20, request: true, involved: ['backend'] }))
    expect(seen.find((v) => v.kind === 'celebrate')).toEqual({ kind: 'celebrate', agents: ['backend'] })
  })

  it("shows the expanded spec in the Architect's bubble and keeps it for the Contract tab", () => {
    const { m, seen } = setup()
    const text = ['# Todo app', '', 'Tasks.', '', '**todos**: title (string)'].join(String.fromCharCode(10))
    m.apply(ev('spec_ready', { agent: 'architect', title: 'Todo app', summary: 'Tasks with a priority and a due date.', features: ['Form', 'List'], text }))
    expect(m.spec?.title).toBe('Todo app')
    expect(m.spec?.features).toEqual(['Form', 'List'])
    expect(seen.some((v) => v.kind === 'say' && v.agent === 'architect' && v.text.startsWith('Spec: Tasks with a priority'))).toBe(true)
    m.reset()
    expect(m.spec).toBeNull()
  })

  it('says what the spec leaves out', () => {
    const { m, seen } = setup()
    m.apply(ev('spec_ready', { agent: 'architect', title: 'Reddit', summary: 'Posts and comments.', features: ['Form'], text: '# Reddit', not_included: ['login', 'subreddits'] }))
    expect(m.spec?.notIncluded).toEqual(['login', 'subreddits'])
    expect(seen.some((v) => v.kind === 'say' && v.text.includes('Not in this version: login, subreddits'))).toBe(true)
  })

  it('keeps the newest metrics event for the gauges and the loaded-model chip', () => {
    const { m } = setup()
    expect(m.metrics).toBeNull()
    m.apply(ev('metrics', { gpu: { name: 'RTX', used_gb: 6.1, total_gb: 8 }, ram: { used_gb: 12, total_gb: 32 }, loaded: [{ id: 'qwen25-coder-7b', name: 'qwen2.5-coder:7b', vram_gb: 4.7 }], budget_gb: 6.2, tokens_per_s: 71.4, swaps: 1 }))
    expect(m.metrics?.gpu?.used_gb).toBe(6.1)
    expect(m.metrics?.loaded?.[0].name).toBe('qwen2.5-coder:7b')
    expect(m.metrics?.tokens_per_s).toBe(71.4)
    m.reset()
    expect(m.metrics).toBeNull()
  })
  it('keeps the gap report of an imported project, the choice and the result', () => {
    const { m } = setup()
    m.apply(ev('gap_report', { framework: 'fastapi', entry: 'app.main:app', routes: [{}, {}], tables: ['events'], tests: { summary: '2 passed' }, gaps: [{ id: 'g1', kind: 'todo_body', title: 'POST /x is a placeholder', file: 'a.py' }, { id: 'g2', kind: 'missing_endpoint', title: 'GET /y', file: 'a.py' }] }))
    expect(m.finish?.gaps).toHaveLength(2)
    expect(m.finish?.routes).toBe(2)
    m.apply(ev('selection_needed', { count: 2 }))
    expect(m.finish?.selecting).toBe(true)
    m.apply(ev('gaps_selected', { ids: ['g2'], auto: false }))
    expect([m.finish?.selecting, m.finish?.selected]).toEqual([false, ['g2']])
    m.apply(ev('gap_status', { fixed: ['g2'], open: ['g1'], selected: ['g2'] }))
    m.apply(ev('finish_summary', { files: [{ path: 'a.py', added: 5, deleted: 1 }], insertions: 5, deletions: 1, diff: '+x', truncated: false, branch: 'q/finish', base: 'q/base' }))
    expect(m.finish?.fixed).toEqual(['g2'])
    expect(m.finish?.summary?.branch).toBe('q/finish')
    m.reset()
    expect(m.finish).toBeNull()
  })
})
