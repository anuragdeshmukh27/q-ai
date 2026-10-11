// State of the in-app IDE (simulation mode): which file is open, what has been edited and not saved, and the saving that Run tests and Submit do first.
// No React in here: the dock tab reads it through useSyncExternalStore, and the tests drive it with a fake client.
import type { IdeFile, IdeTree } from './api'
import type { IdeTestRun } from './model'

export interface IdeClient {
  tree(role: string): Promise<IdeTree>
  read(role: string, path: string): Promise<{ path: string; content: string }>
  write(role: string, path: string, content: string): Promise<{ path: string }>
  runTests(role: string): Promise<{ started: boolean }>
}

interface Draft {
  saved: string // what is on disk
  text: string // what the editor shows
}

export class IdeController {
  role = ''
  tree: IdeTree | null = null
  open = '' // the path in the editor
  loading = false
  saving = false
  private drafts = new Map<string, Draft>()
  private version = 0
  private sinks = new Set<() => void>()
  private gen = 0 // bumped when the role changes, so an answer for the old role is dropped

  private client: IdeClient
  private onError: (e: unknown) => void

  constructor(client: IdeClient, onError: (e: unknown) => void) {
    this.client = client
    this.onError = onError
  }

  subscribe = (fn: () => void) => {
    this.sinks.add(fn)
    return () => {
      this.sinks.delete(fn)
    }
  }
  getVersion = () => this.version
  private touch() {
    this.version++
    this.sinks.forEach((f) => f())
  }

  setRole(role: string) {
    if (role === this.role) return
    this.role = role
    this.gen++
    this.tree = null
    this.open = ''
    this.drafts = new Map()
    this.touch()
  }

  file(path: string): IdeFile | undefined {
    return this.tree?.files.find((f) => f.path === path)
  }
  writable(path: string): boolean {
    return !!this.file(path)?.writable
  }
  get text(): string {
    return this.drafts.get(this.open)?.text ?? ''
  }
  get loaded(): boolean {
    return this.drafts.has(this.open)
  }
  isDirty(path: string): boolean {
    const d = this.drafts.get(path)
    return !!d && d.text !== d.saved
  }
  /** Every file with edits that are not on disk. */
  get dirty(): string[] {
    return [...this.drafts.keys()].filter((p) => this.isDirty(p))
  }

  async refresh(): Promise<void> {
    const gen = this.gen
    if (!this.role) return
    try {
      const tree = await this.client.tree(this.role)
      if (gen !== this.gen) return
      this.tree = tree
    } catch (e) {
      if (gen === this.gen) this.onError(e)
    }
    this.touch()
  }

  /** Show a file. Edits to the one before stay in their draft (the dot in the tree and the header), so nothing is lost by looking at another file. */
  async openFile(path: string): Promise<void> {
    this.open = path
    if (!this.drafts.has(path)) {
      const gen = this.gen
      this.loading = true
      this.touch()
      try {
        const f = await this.client.read(this.role, path)
        if (gen !== this.gen) return
        this.drafts.set(path, { saved: f.content, text: f.content })
      } catch (e) {
        if (gen === this.gen) {
          this.open = ''
          this.onError(e)
        }
      } finally {
        if (gen === this.gen) this.loading = false
      }
    }
    this.touch()
  }

  /** The editor changed the open file. A file that may not be edited ignores it. */
  edit(text: string): void {
    const d = this.drafts.get(this.open)
    if (!d || !this.writable(this.open) || d.text === text) return
    d.text = text
    this.touch()
  }

  /** Save one file. False when it failed (the error is reported and the edits stay). */
  async save(path = this.open): Promise<boolean> {
    const d = this.drafts.get(path)
    if (!d || d.text === d.saved) return true
    const text = d.text
    this.saving = true
    this.touch()
    try {
      await this.client.write(this.role, path, text)
      d.saved = text // edits made while the save was going stay dirty
      return true
    } catch (e) {
      this.onError(e)
      return false
    } finally {
      this.saving = false
      this.touch()
    }
  }

  /** Save every edited file, one after the other; stops at the first that fails. */
  async saveAll(): Promise<boolean> {
    for (const p of this.dirty) if (!(await this.save(p))) return false
    return true
  }

  /** Run tests: unsaved edits are saved first, so the run sees what is on screen. */
  async run(): Promise<boolean> {
    if (!(await this.saveAll())) return false
    try {
      await this.client.runTests(this.role)
      return true
    } catch (e) {
      this.onError(e)
      return false
    }
  }

  /** Submit for review: unsaved edits are saved first; `submit` is the existing Submit of the task. */
  async submit(task: string, submit: (task: string) => Promise<void>): Promise<boolean> {
    if (!(await this.saveAll())) return false
    await submit(task)
    await this.refresh()
    return true
  }

  /** A new, empty file inside the person's folders. */
  async create(path: string): Promise<boolean> {
    const clean = path.trim().replace(/\\/g, '/').replace(/^\/+/, '')
    if (!clean) return false
    try {
      await this.client.write(this.role, clean, '')
    } catch (e) {
      this.onError(e)
      return false
    }
    await this.refresh()
    await this.openFile(clean)
    return true
  }
}

export type Mark = 'pass' | 'fail' | 'todo'

/** The tick or cross of one acceptance test (a test file or a test id) in the last run. A test that did not run, or a run that is older than the task, shows neither. */
export function acceptanceMark(entry: string, run: IdeTestRun | null): Mark {
  if (!run) return 'todo'
  const mine = run.tests.filter((t) => t.id === entry || t.id.startsWith(`${entry}::`))
  if (!mine.length) return 'todo'
  return mine.some((t) => t.outcome === 'failed') ? 'fail' : mine.every((t) => t.outcome === 'passed' || t.outcome === 'skipped') ? 'pass' : 'todo'
}

/** The tests of the last run that are not acceptance tests but failed (they break "the whole suite has to pass"). */
export function otherFailures(entries: string[], run: IdeTestRun | null): string[] {
  if (!run) return []
  return run.tests.filter((t) => t.outcome === 'failed' && !entries.some((e) => t.id === e || t.id.startsWith(`${e}::`))).map((t) => t.id)
}

/** The nearest role to show: the owner of the person's open task, else the first of the roles they play. */
export function ideRole(tasks: { owner: string; assignee?: string; status: string; worktree?: string }[], humanRoles: Iterable<string>): string {
  const open = tasks.find((t) => t.assignee === 'human' && t.worktree && t.status === 'running')
  return open?.owner ?? [...humanRoles][0] ?? ''
}
