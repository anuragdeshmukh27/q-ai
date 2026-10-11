import { describe, expect, it } from 'vitest'
import type { IdeTree } from '../api'
import { acceptanceMark, ideRole, IdeController, otherFailures, type IdeClient } from '../ide'
import { parseMarkdown } from '../markdown'
import { IDE_MAX_LINES, OfficeModel, type AgentInfo, type IdeTestRun, type QEvent, type Visual } from '../model'

const TREE: IdeTree = {
  role: 'database', ready: true, task: 't1', running: false, editable: ['database/**'], names: { database: 'Karan', backend: 'Rohan' },
  files: [
    { path: 'database/calculations.py', size: 10, owner: 'database', writable: true },
    { path: 'database/connection.py', size: 10, owner: 'database', writable: false },
    { path: 'backend/api/calculator.py', size: 10, owner: 'backend', writable: false },
  ],
}

/** A fake server: files in a map, every call recorded in order. */
function fake(files: Record<string, string> = { 'database/calculations.py': 'old\n', 'database/connection.py': 'conn\n', 'backend/api/calculator.py': 'api\n' }) {
  const calls: string[] = []
  const errors: unknown[] = []
  let failWrite = false
  const client: IdeClient = {
    tree: async () => (calls.push('tree'), TREE),
    read: async (_r, p) => {
      calls.push(`read ${p}`)
      if (!(p in files)) throw new Error('file not found')
      return { path: p, content: files[p] }
    },
    write: async (_r, p, c) => {
      calls.push(`write ${p}`)
      if (failWrite) throw new Error('write denied')
      files[p] = c
      return { path: p }
    },
    runTests: async () => (calls.push('run'), { started: true }),
  }
  const ctl = new IdeController(client, (e) => errors.push(e))
  ctl.setRole('database')
  return { ctl, calls, errors, files, failWrites: (v: boolean) => (failWrite = v) }
}

async function ready(f = fake()) {
  await f.ctl.refresh()
  await f.ctl.openFile('database/calculations.py')
  return f
}

describe('the IDE: editing and saving', () => {
  it('opens a file, tracks the unsaved edit and clears it on save', async () => {
    const { ctl, files, calls } = await ready()
    expect(ctl.text).toBe('old\n')
    expect(ctl.dirty).toEqual([])
    ctl.edit('new\n')
    expect(ctl.text).toBe('new\n')
    expect(ctl.isDirty('database/calculations.py')).toBe(true)
    expect(ctl.dirty).toEqual(['database/calculations.py'])
    expect(await ctl.save()).toBe(true)
    expect(files['database/calculations.py']).toBe('new\n')
    expect(ctl.dirty).toEqual([])
    calls.length = 0
    expect(await ctl.save()).toBe(true) // nothing to save: no request
    expect(calls).toEqual([])
  })

  it('editing back to the saved text is not dirty', async () => {
    const { ctl } = await ready()
    ctl.edit('x')
    ctl.edit('old\n')
    expect(ctl.dirty).toEqual([])
  })

  it('a failed save keeps the edit, reports the error and says so', async () => {
    const { ctl, errors, failWrites } = await ready()
    ctl.edit('new\n')
    failWrites(true)
    expect(await ctl.save()).toBe(false)
    expect(ctl.isDirty('database/calculations.py')).toBe(true)
    expect(ctl.text).toBe('new\n')
    expect(errors).toHaveLength(1)
    failWrites(false)
    expect(await ctl.save()).toBe(true)
    expect(ctl.dirty).toEqual([])
  })

  it('a file that is not yours cannot be edited', async () => {
    const f = fake()
    await f.ctl.refresh()
    await f.ctl.openFile('database/connection.py')
    expect(f.ctl.writable('database/connection.py')).toBe(false)
    f.ctl.edit('hacked')
    expect(f.ctl.text).toBe('conn\n')
    expect(f.ctl.dirty).toEqual([])
  })

  it('keeps the edits of a file while another one is open', async () => {
    const f = await ready()
    f.ctl.edit('mine\n')
    await f.ctl.openFile('backend/api/calculator.py')
    expect(f.ctl.text).toBe('api\n')
    expect(f.ctl.dirty).toEqual(['database/calculations.py'])
    await f.ctl.openFile('database/calculations.py')
    expect(f.ctl.text).toBe('mine\n')
    expect(f.calls.filter((c) => c === 'read database/calculations.py')).toHaveLength(1) // not read again: the draft is the truth
  })

  it('a file that cannot be read closes the editor and reports it', async () => {
    const f = fake()
    await f.ctl.refresh()
    await f.ctl.openFile('database/missing.py')
    expect(f.ctl.open).toBe('')
    expect(f.errors).toHaveLength(1)
  })

  it('switching role forgets the files of the other role', async () => {
    const f = await ready()
    f.ctl.edit('mine\n')
    f.ctl.setRole('backend')
    expect(f.ctl.open).toBe('')
    expect(f.ctl.dirty).toEqual([])
    expect(f.ctl.tree).toBeNull()
  })
})

describe('the IDE: saving before Run tests and Submit', () => {
  it('Run tests saves the unsaved files first, in order, then starts the run', async () => {
    const f = await ready()
    f.ctl.edit('new\n')
    f.calls.length = 0
    expect(await f.ctl.run()).toBe(true)
    expect(f.calls).toEqual(['write database/calculations.py', 'run'])
    expect(f.files['database/calculations.py']).toBe('new\n')
  })

  it('Run tests with nothing to save just runs', async () => {
    const f = await ready()
    f.calls.length = 0
    await f.ctl.run()
    expect(f.calls).toEqual(['run'])
  })

  it('does not run when the save failed', async () => {
    const f = await ready()
    f.ctl.edit('new\n')
    f.failWrites(true)
    f.calls.length = 0
    expect(await f.ctl.run()).toBe(false)
    expect(f.calls).toEqual(['write database/calculations.py'])
    expect(f.errors).toHaveLength(1)
  })

  it('Submit saves first, then submits the task, then reloads the tree', async () => {
    const f = await ready()
    f.ctl.edit('new\n')
    f.calls.length = 0
    const order: string[] = []
    expect(await f.ctl.submit('t1', async (t) => void order.push(`submit ${t} after ${f.calls.join('+')}`))).toBe(true)
    expect(order).toEqual(['submit t1 after write database/calculations.py'])
    expect(f.calls.at(-1)).toBe('tree')
  })

  it('Submit does not go on when a save fails', async () => {
    const f = await ready()
    f.ctl.edit('new\n')
    f.failWrites(true)
    let submitted = false
    expect(await f.ctl.submit('t1', async () => void (submitted = true))).toBe(false)
    expect(submitted).toBe(false)
  })

  it('a new file is written empty, shown in the tree and opened', async () => {
    const f = await ready()
    expect(await f.ctl.create('  tests\\test_db_more.py ')).toBe(true)
    expect(f.files['tests/test_db_more.py']).toBe('')
    expect(f.ctl.open).toBe('tests/test_db_more.py')
    expect(await f.ctl.create('   ')).toBe(false)
  })
})

const ROSTER: AgentInfo[] = ['database', 'backend'].map((id, i) => ({ id, name: id.toUpperCase(), role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' } }))
let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}): QEvent => ({ seq: seq++, ts: 0, type, ...rest })
function office() {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  const seen: Visual[] = []
  m.onVisual((v) => seen.push(v))
  return { m, seen }
}
const RESULT = { agent: 'database', task: 't1', ok: false, passed: 1, failed: 1, summary: '1 failed, 1 passed in 0.2s', tests: [
  { id: 'tests/test_db_calculations.py::test_add', outcome: 'passed' },
  { id: 'tests/test_db_calculations.py::test_list', outcome: 'failed' },
  { id: 'tests/test_other.py::test_x', outcome: 'failed' },
] }

describe('the IDE: test output and results in the model', () => {
  it('collects the output of a run and the verdict', () => {
    const { m } = office()
    m.apply(ev('human_test_started', { agent: 'database', task: 't1' }))
    expect(m.ide).toMatchObject({ running: true, lines: [], task: 't1' })
    m.apply(ev('human_test_output', { agent: 'database', task: 't1', line: 'collected 2 items' }))
    m.apply(ev('human_test_output', { agent: 'database', task: 't1', line: 'FAILED test_list' }))
    expect(m.ide.lines).toEqual(['collected 2 items', 'FAILED test_list'])
    m.apply(ev('human_test_result', RESULT))
    expect(m.ide.running).toBe(false)
    expect(m.ide.result).toMatchObject({ task: 't1', ok: false, passed: 1, failed: 1, summary: RESULT.summary })
    expect(m.ide.result!.tests).toHaveLength(3)
    expect(m.ide.lines).toHaveLength(2) // the output stays under the verdict
  })

  it('a new run clears the output but keeps the last verdict until the new one arrives', () => {
    const { m } = office()
    m.apply(ev('human_test_result', RESULT))
    m.apply(ev('human_test_started', { agent: 'database', task: 't1' }))
    expect(m.ide.lines).toEqual([])
    expect(m.ide.result?.ok).toBe(false)
    m.apply(ev('human_test_result', { ...RESULT, ok: true, failed: 0, tests: [] }))
    expect(m.ide.result?.ok).toBe(true)
  })

  it('keeps the newest lines when a run is longer than the panel holds', () => {
    const { m } = office()
    for (let i = 0; i < IDE_MAX_LINES + 5; i++) m.apply(ev('human_test_output', { task: 't1', line: `l${i}` }))
    expect(m.ide.lines).toHaveLength(IDE_MAX_LINES)
    expect(m.ide.lines.at(-1)).toBe(`l${IDE_MAX_LINES + 4}`)
    expect(m.ide.cut).toBe(true)
  })

  it('a new build starts with an empty panel', () => {
    const { m } = office()
    m.apply(ev('human_test_output', { task: 't1', line: 'x' }))
    m.apply(ev('human_test_result', RESULT))
    m.reset()
    expect(m.ide).toEqual({ task: '', running: false, lines: [], cut: false, result: null })
  })

  it('remembers the acceptance tests of the task and keeps them through a re-plan', () => {
    const { m } = office()
    const plan = { tasks: [{ id: 't1', title: 'DB', owner: 'database', depends_on: [], files: ['database/x.py'], assignee: 'human' }] }
    m.apply(ev('plan_created', plan))
    m.apply(ev('human_task_assigned', { agent: 'database', task: 't1', title: 'DB', owner: 'database', files: [], tests: ['tests/test_db_calculations.py'], worktree: 'C:/w', doc: '.q/tasks/t1.md' }))
    expect(m.tasks[0].tests).toEqual(['tests/test_db_calculations.py'])
    m.apply(ev('plan_created', { ...plan, replan: true }))
    expect(m.tasks[0].tests).toEqual(['tests/test_db_calculations.py'])
  })

  it('a submit that is refused for files outside the role says which, as a toast', () => {
    const { m, seen } = office()
    m.apply(ev('human_submit_result', { agent: 'database', task: 't1', ok: false, stage: 'scope', failed: [], files: ['backend/api/x.py', 'static/app.js'], summary: 's' }))
    const t = seen.find((v) => v.kind === 'toast') as Extract<Visual, { kind: 'toast' }>
    expect(t.level).toBe('bad')
    expect(t.title).toContain('outside your role')
    expect(t.text).toContain('backend/api/x.py, static/app.js')
    expect(t.title).not.toContain('tests failed')
  })
})

describe('the IDE: acceptance marks', () => {
  const run = RESULT as unknown as IdeTestRun
  it('marks a test file by what ran in it', () => {
    expect(acceptanceMark('tests/test_db_calculations.py', run)).toBe('fail') // one of its tests failed
    expect(acceptanceMark('tests/test_db_calculations.py::test_add', run)).toBe('pass')
    expect(acceptanceMark('tests/test_db_calculations.py::test_list', run)).toBe('fail')
    expect(acceptanceMark('tests/test_missing.py', run)).toBe('todo')
    expect(acceptanceMark('tests/test_db_calculations.py', null)).toBe('todo')
  })
  it('a file with only passing tests is a tick', () => {
    const green = { ...run, ok: true, tests: [{ id: 'tests/a.py::t1', outcome: 'passed' }, { id: 'tests/a.py::t2', outcome: 'passed' }] }
    expect(acceptanceMark('tests/a.py', green)).toBe('pass')
    expect(acceptanceMark('tests/a', green)).toBe('todo') // a prefix of the name is not the file
  })
  it('lists the failures that are not acceptance tests', () => {
    expect(otherFailures(['tests/test_db_calculations.py'], run)).toEqual(['tests/test_other.py::test_x'])
    expect(otherFailures([], null)).toEqual([])
  })
  it('shows the role of the open task, else the first role you play', () => {
    const tasks = [{ owner: 'backend', assignee: 'human', status: 'pending', worktree: undefined }, { owner: 'database', assignee: 'human', status: 'running', worktree: 'C:/w' }]
    expect(ideRole(tasks, ['backend', 'database'])).toBe('database')
    expect(ideRole([], ['backend', 'database'])).toBe('backend')
    expect(ideRole([], [])).toBe('')
  })
})

describe('the task document as markdown', () => {
  it('reads headings, bullet lists, paragraphs, code and bold', () => {
    const blocks = parseMarkdown('# t1: DB\n\nThis task is **yours**,\nread it.\n\n## Files\n- `a.py`\n- b\n\n## Next\ntext\n')
    expect(blocks.map((b) => b.kind)).toEqual(['h', 'p', 'h', 'ul', 'h', 'p'])
    expect(blocks[0]).toMatchObject({ kind: 'h', level: 1 })
    const p = blocks[1] as { spans: { text: string; bold?: boolean }[] }
    expect(p.spans.map((s) => s.text).join('')).toBe('This task is yours, read it.')
    expect(p.spans[1]).toEqual({ text: 'yours', bold: true })
    const ul = blocks[3] as { items: { text: string; code?: boolean }[][] }
    expect(ul.items).toHaveLength(2)
    expect(ul.items[0][0]).toEqual({ text: 'a.py', code: true })
  })
  it('never makes html out of text', () => {
    const [p] = parseMarkdown('<script>alert(1)</script>') as { spans: { text: string }[] }[]
    expect(p.spans[0].text).toBe('<script>alert(1)</script>')
  })
})
