// Client-side view of a project, derived only from the event stream (so live builds and replays look identical).

export interface QEvent {
  seq: number
  ts: number
  type: string
  agent?: string
  [k: string]: unknown
}

export interface AgentInfo {
  id: string
  name: string
  role: string
  desk: [number, number]
  sprite: { palette: string; accessory: string }
}

export interface AgentView extends AgentInfo {
  state: string
  model: string | null
  iteration: number
  maxIterations: number
  task: { id: string; title: string } | null
  thought: string
  files: string[]
  tests: { ok: boolean; failed: number; summary: string } | null
  log: string[]
}

export interface TaskView {
  id: string
  title: string
  owner: string
  depends_on: string[]
  status: string
}

export type Tone = 'info' | 'good' | 'bad' | 'warn'

/** Things the office should act out. They are derived from events but are not state. */
export type Visual =
  | { kind: 'message'; from: string; to: string; text: string; tone: Tone }
  | { kind: 'say'; agent: string; text: string; tone: Tone }
  | { kind: 'test'; agent: string; ok: boolean }
  | { kind: 'celebrate' }
  | { kind: 'reset' }
  | { kind: 'alert'; agent: string }
  | { kind: 'toast'; level: Tone; title: string; text: string }

export const MODES = ['assisted', 'supervised', 'autonomous'] as const

const str = (v: unknown, d = '') => (typeof v === 'string' ? v : d)
const num = (v: unknown, d = 0) => (typeof v === 'number' ? v : d)
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

export class OfficeModel {
  agents = new Map<string, AgentView>()
  order: string[] = []
  tasks: TaskView[] = []
  progress = { done: 0, total: 0, percent: 0 }
  slug = ''
  goal = ''
  preset = ''
  appUrl = ''
  finished: { ok: boolean; seconds: number } | null = null
  mode = 'supervised'
  ticker = ''
  eventCount = 0
  bugs: { id: number; owner: string; title: string; fixed: boolean }[] = []
  version = 0 // bumped on every change; React re-renders on it

  private owners = new Map<string, string>()
  private sinks = new Set<() => void>()
  private visualSinks = new Set<(v: Visual) => void>()
  private pending = false

  subscribe = (fn: () => void) => {
    this.sinks.add(fn)
    return () => {
      this.sinks.delete(fn)
    }
  }

  onVisual(fn: (v: Visual) => void) {
    this.visualSinks.add(fn)
    return () => {
      this.visualSinks.delete(fn)
    }
  }

  getVersion = () => this.version

  setRoster(list: AgentInfo[], keepState = true) {
    const old = this.agents
    this.agents = new Map()
    this.order = []
    for (const a of list) {
      const prev = keepState ? old.get(a.id) : undefined
      this.agents.set(a.id, prev ? { ...prev, ...a } : { ...a, state: 'idle', model: null, iteration: 0, maxIterations: 0, task: null, thought: '', files: [], tests: null, log: [] })
      this.order.push(a.id)
    }
    this.touch()
  }

  /** Forget the project but keep the team. */
  reset() {
    this.setRoster(this.order.map((id) => this.agents.get(id)!).map(({ id, name, role, desk, sprite }) => ({ id, name, role, desk, sprite })), false)
    this.tasks = []
    this.progress = { done: 0, total: 0, percent: 0 }
    this.slug = this.goal = this.preset = this.appUrl = this.ticker = ''
    this.finished = null
    this.bugs = []
    this.eventCount = 0
    this.owners.clear()
    this.show({ kind: 'reset' }, true)
    this.touch()
  }

  /** Local choices made before/while a project runs (the server confirms mode changes with an event). */
  setGoal(goal: string) {
    this.goal = goal
    this.touch()
  }

  setMode(mode: string) {
    this.mode = mode
    this.touch()
  }

  name(id: string): string {
    return this.agents.get(id)?.name ?? (id === 'human' ? 'You' : id)
  }

  private touch() {
    this.version++
    if (this.pending) return
    this.pending = true
    const run = () => {
      this.pending = false
      this.sinks.forEach((f) => f())
    }
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run)
    else queueMicrotask(run)
  }

  private show(v: Visual, on: boolean) {
    if (on) this.visualSinks.forEach((f) => f(v))
  }

  private say(text: string) {
    this.ticker = text
  }

  apply(e: QEvent, visuals = true) {
    this.eventCount++
    const a = e.agent ? this.agents.get(e.agent) : undefined
    switch (e.type) {
      case 'agent_state':
        if (a) a.state = str(e.state)
        break
      case 'iteration':
        if (a) {
          a.iteration = num(e.n)
          a.maxIterations = num(e.max)
        }
        break
      case 'agent_thought':
        if (a) {
          a.thought = str(e.text)
          a.model = str(e.model) || a.model
        }
        break
      case 'tool_call':
        if (a) {
          const args = (e.args ?? {}) as Record<string, unknown>
          const first = Object.values(args)[0]
          const line = `${str(e.tool)} ${first ? str(first as string).split('\n')[0].slice(0, 60) : ''}`.trim() + (e.ok === false ? ' (failed)' : '')
          a.log = [...a.log, line].slice(-12)
        }
        break
      case 'file_changed':
        if (a && !a.files.includes(str(e.path))) a.files = [...a.files, str(e.path)]
        break
      case 'test_result':
        if (a) {
          a.tests = { ok: e.passed === true, failed: Array.isArray(e.failed) ? e.failed.length : 0, summary: str(e.summary) }
          this.show({ kind: 'test', agent: a.id, ok: e.passed === true }, visuals)
          this.say(`${a.name}: tests ${e.passed ? 'pass' : 'fail'}, ${str(e.summary)}`)
        }
        break
      case 'project_created':
        this.slug = str(e.slug)
        this.preset = str(e.preset)
        this.goal = str(e.goal) || this.goal
        this.say(`Project ${this.slug} created (${this.preset})`)
        break
      case 'architecture_ready':
        this.show({ kind: 'message', from: 'architect', to: 'planner', text: `Contract ready: ${num(e.endpoints)} endpoints, ${num(e.tables)} table${num(e.tables) === 1 ? '' : 's'}`, tone: 'good' }, visuals)
        this.say(`${this.name('architect')} published the architecture and the API contract`)
        break
      case 'contract_updated':
        if (num(e.version) > 1) this.show({ kind: 'say', agent: 'architect', text: `Contract v${num(e.version)}`, tone: 'warn' }, visuals)
        break
      case 'plan_created': {
        const tasks = (e.tasks as TaskView[]) ?? []
        const old = new Map(this.tasks.map((t) => [t.id, t.status]))
        this.tasks = tasks.map((t) => ({ ...t, status: old.get(t.id) ?? 'pending' }))
        this.owners = new Map(tasks.map((t) => [t.id, t.owner]))
        this.show({ kind: 'say', agent: 'planner', text: `Plan: ${tasks.length} tasks`, tone: 'info' }, visuals)
        this.say(`${this.name('planner')} planned ${tasks.length} tasks`)
        break
      }
      case 'project_progress': {
        this.progress = { done: num(e.done), total: num(e.total), percent: num(e.percent) }
        const st = (e.tasks ?? {}) as Record<string, string>
        this.tasks = this.tasks.map((t) => ({ ...t, status: st[t.id] ?? t.status }))
        break
      }
      case 'task_assigned':
        if (a) {
          a.task = { id: str(e.task), title: str(e.title) }
          a.model = str(e.model) || a.model
          a.iteration = 0
          a.tests = null
          this.owners.set(str(e.task), a.id)
          if (a.id !== 'planner') this.show({ kind: 'message', from: 'planner', to: a.id, text: `${str(e.task)}: ${clip(str(e.title), 48)}`, tone: 'info' }, visuals)
          this.say(`${this.name('planner')} → ${a.name}: ${str(e.task)} ${str(e.title)}`)
        }
        break
      case 'review_result': {
        const owner = this.owners.get(str(e.task))
        const ok = e.verdict === 'PASS'
        const items = Array.isArray(e.items) ? (e.items as { problem?: string }[]) : []
        const text = ok ? `${str(e.task)} approved ✓` : `${str(e.task)}: ${clip(items[0]?.problem ?? str(e.summary), 52)}`
        if (owner) this.show({ kind: 'message', from: 'reviewer', to: owner, text, tone: ok ? 'good' : 'warn' }, visuals)
        this.say(`${this.name('reviewer')} reviewed ${str(e.task)}: ${ok ? 'PASS' : 'REQUEST CHANGES'}`)
        break
      }
      case 'merge_result': {
        const owner = str(e.branch).replace('agent/', '')
        const ok = e.ok === true
        if (this.agents.has(owner)) this.show({ kind: 'message', from: 'integrator', to: owner, text: ok ? `Merged ${str(e.branch)} ✓` : `Merge problem: ${clip(str(e.summary), 40)}`, tone: ok ? 'good' : 'bad' }, visuals)
        this.say(`${this.name('integrator')} merged ${str(e.branch)} ${ok ? '✓' : '✗'} ${str(e.summary)}`)
        break
      }
      case 'bug_filed': {
        const owner = str(e.owner)
        this.bugs = [...this.bugs, { id: num(e.bug), owner, title: str(e.title), fixed: false }]
        if (this.agents.has(owner)) this.show({ kind: 'message', from: 'qa', to: owner, text: `Bug #${num(e.bug)}: ${clip(str(e.title), 44)}`, tone: 'bad' }, visuals)
        this.say(`${this.name('qa')} filed bug #${num(e.bug)} for ${this.name(owner)}: ${str(e.title)}`)
        break
      }
      case 'bug_fixed': {
        const owner = str(e.owner)
        this.bugs = this.bugs.map((b) => (b.id === num(e.bug) ? { ...b, fixed: true } : b))
        if (this.agents.has(owner)) this.show({ kind: 'message', from: owner, to: 'qa', text: `Bug #${num(e.bug)} fixed`, tone: 'good' }, visuals)
        this.say(`${this.name(owner)} fixed bug #${num(e.bug)}`)
        break
      }
      case 'fault_injected':
        this.show({ kind: 'toast', level: 'info', title: 'Fault injected (demo)', text: str(e.description) }, visuals)
        this.say(`Demo fault injected into ${str(e.file)}`)
        break
      case 'message_sent': {
        const from = str(e.from)
        const to = str(e.to)
        if (this.agents.has(from) && this.agents.has(to)) this.show({ kind: 'message', from, to, text: clip(str(e.text), 70), tone: 'info' }, visuals)
        else if (this.agents.has(from)) this.show({ kind: 'say', agent: from, text: clip(str(e.text), 70), tone: 'info' }, visuals)
        else if (this.agents.has(to)) this.show({ kind: 'say', agent: to, text: `${this.name(from)}: ${clip(str(e.text), 60)}`, tone: 'info' }, visuals)
        this.say(`${this.name(from)} → ${this.name(to)}: ${clip(str(e.text), 80)}`)
        break
      }
      case 'escalation':
        if (a) this.show({ kind: 'alert', agent: a.id }, visuals)
        this.show({ kind: 'toast', level: 'warn', title: `${a ? a.name : 'Team'} needs a decision`, text: clip(str(e.detail) || str(e.reason), 140) }, visuals)
        this.say(`Escalation from ${a ? a.name : 'the team'}: ${clip(str(e.detail) || str(e.reason), 80)}`)
        break
      case 'approval_needed':
        this.show({ kind: 'toast', level: 'warn', title: 'Approval needed', text: clip(str(e.summary), 140) }, visuals)
        break
      case 'error':
        if (a) this.show({ kind: 'alert', agent: a.id }, visuals)
        this.show({ kind: 'toast', level: 'bad', title: 'Something went wrong', text: clip(str(e.message), 140) }, visuals)
        break
      case 'mode_changed':
        this.mode = str(e.mode) || this.mode
        break
      case 'app_running':
        this.appUrl = str(e.url)
        this.say(`The app is running at ${this.appUrl}`)
        break
      case 'project_done':
        this.finished = { ok: e.ok === true, seconds: num(e.seconds) }
        this.appUrl = str(e.app_url) || this.appUrl
        if (e.ok === true) {
          for (const v of this.agents.values()) v.state = 'celebrating'
          this.show({ kind: 'celebrate' }, visuals)
          this.show({ kind: 'toast', level: 'good', title: 'Build complete', text: `Finished in ${num(e.seconds)} s` }, visuals)
        } else {
          this.show({ kind: 'toast', level: 'bad', title: 'Build stopped', text: clip(Array.isArray(e.problems) ? (e.problems as string[]).join('; ') : '', 140) || 'See the log for details' }, visuals)
        }
        this.say(e.ok ? `Done in ${num(e.seconds)} s` : 'The build stopped')
        break
    }
    this.touch()
  }

  get activeCount(): number {
    let n = 0
    for (const a of this.agents.values()) if (!['idle', 'sleeping', 'celebrating'].includes(a.state)) n++
    return n
  }
}
