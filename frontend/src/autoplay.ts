// Autoplay ("Watch a run"): a script plays the scenario on the server and announces each action as an `autoplay_*` event that carries its data. This folds those events into a mirror of
// the script's IDE (tabs, the open file, the unsaved text, the search and its result) that the visible IDE shows, so the screen follows the script without asking the server for
// anything (a second read would be a second entry in the evidence). No React in here. The fold is idempotent: a reconnect or a replay that delivers the events again ends in the same state.
import type { IdeFile, IdeSearch, IdeTree } from './api'

export interface AutoplayFile {
  text: string // what the editor shows
  saved: string // what is on disk: the text differs until the save event arrives
  writable: boolean
}

/** What the visible IDE shows while a script plays. */
export interface AutoplayIde {
  tree: IdeTree | null
  tabs: string[]
  open: string
  files: Record<string, AutoplayFile>
  panel: 'files' | 'search'
  query: string
  found: IdeSearch | null
  reveal: { path: string; line: number; seq: number } | null
  rev: number // bumped on every change: the IDE re-applies the mirror when it moves
}

export interface AutoplayState {
  variant: string // "strong" | "weak"
  speed: number // 1 or 2
  rate: number // session seconds per real second
  step: number
  total: number
  label: string
  labels: string[]
  focus: 'ide' | 'chat' | 'debrief'
  doc: string // the task document (markdown), so a replay needs no server
  task: string
  active: boolean // false once the run has ended
  ended: '' | 'done' | 'stopped' | 'error'
  error: string
  ide: AutoplayIde
}

export const emptyIde = (): AutoplayIde => ({ tree: null, tabs: [], open: '', files: {}, panel: 'files', query: '', found: null, reveal: null, rev: 0 })

const str = (v: unknown, d = '') => (typeof v === 'string' ? v : d)
const num = (v: unknown, d = 0) => (typeof v === 'number' ? v : d)

export function startAutoplay(e: { [k: string]: unknown }): AutoplayState {
  const labels = Array.isArray(e.labels) ? e.labels.filter((x): x is string => typeof x === 'string') : []
  const tree = e.tree && typeof e.tree === 'object' ? (e.tree as IdeTree) : null
  return {
    variant: str(e.variant), speed: num(e.speed, 1), rate: num(e.rate, 1), step: 0, total: num(e.total, labels.length), label: '', labels, focus: 'ide', doc: str(e.doc), task: str(e.task),
    active: true, ended: '', error: '', ide: { ...emptyIde(), tree },
  }
}

/** The tree with a file added (a file the script created): the Explorer lists it. */
function withFile(tree: IdeTree | null, path: string, writable: boolean, owner: string): IdeTree | null {
  if (!tree || tree.files.some((f) => f.path === path)) return tree
  const file: IdeFile = { path, size: 0, owner, writable }
  return { ...tree, files: [...tree.files, file].sort((a, b) => a.path.localeCompare(b.path)) }
}

/** Fold one event into the autoplay state; any other event is not its business. */
export function autoplayReduce(s: AutoplayState | null, e: { type: string; [k: string]: unknown }): AutoplayState | null {
  if (e.type === 'autoplay_started') return startAutoplay(e)
  if (!s) return s
  const ide = s.ide
  switch (e.type) {
    case 'autoplay_step':
      return { ...s, step: num(e.n), total: num(e.total, s.total), label: str(e.label), focus: e.focus === 'chat' || e.focus === 'debrief' ? e.focus : 'ide' }
    case 'autoplay_speed':
      return { ...s, speed: num(e.speed, s.speed), rate: num(e.rate, s.rate) }
    case 'autoplay_open_file': {
      const path = str(e.path)
      if (!path) return s
      const content = str(e.content)
      const prior = ide.files[path]
      const line = num(e.line)
      return {
        ...s,
        ide: {
          ...ide,
          files: { ...ide.files, [path]: { text: prior ? prior.text : content, saved: prior ? prior.saved : content, writable: e.writable === true } },
          tabs: ide.tabs.includes(path) ? ide.tabs : [...ide.tabs, path],
          open: path,
          reveal: line ? { path, line, seq: (ide.reveal?.seq ?? 0) + 1 } : ide.reveal,
          rev: ide.rev + 1,
        },
      }
    }
    case 'autoplay_search': {
      const found = e.result && typeof e.result === 'object' ? (e.result as IdeSearch) : null
      return { ...s, ide: { ...ide, panel: 'search', query: str(e.q), found, rev: ide.rev + 1 } }
    }
    case 'autoplay_edit': {
      const path = str(e.path)
      if (!path) return s
      const prior = ide.files[path]
      const content = str(e.content)
      return {
        ...s,
        ide: {
          ...ide,
          files: { ...ide.files, [path]: { text: content, saved: prior ? prior.saved : '', writable: true } },
          tabs: ide.tabs.includes(path) ? ide.tabs : [...ide.tabs, path],
          open: path,
          panel: 'files',
          tree: withFile(ide.tree, path, true, ide.tree?.role ?? ''),
          rev: ide.rev + 1,
        },
      }
    }
    case 'session_event': {
      // the server's own record that the save happened: the unsaved dot goes
      if (e.kind !== 'file_saved') return s
      const path = str(e.path)
      const f = ide.files[path]
      if (!f || f.saved === f.text) return s
      return { ...s, ide: { ...ide, files: { ...ide.files, [path]: { ...f, saved: f.text } }, rev: ide.rev + 1 } }
    }
    case 'autoplay_ended': {
      const reason = e.reason === 'stopped' || e.reason === 'error' ? e.reason : 'done'
      return { ...s, active: false, ended: reason, error: str(e.error) }
    }
    default:
      return s
  }
}

/** Whether a file of the mirror has edits that are not saved yet. */
export const isUnsaved = (f: AutoplayFile | undefined): boolean => !!f && f.text !== f.saved

/** "Strong run" / "Weak run". */
export const variantLabel = (variant: string): string => (variant === 'weak' ? 'Weak run' : 'Strong run')

/** The banner's line: "Strong run · step 4 of 10 · Fix both routes". */
export function bannerLine(a: AutoplayState): string {
  return `${variantLabel(a.variant)} · step ${Math.min(a.step, a.total)} of ${a.total}${a.label ? ` · ${a.label}` : ''}`
}
