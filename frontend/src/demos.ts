// Demo picker helpers: which recording plays by default, how a recording card reads, and in which order the cards appear.
import type { RecordingMeta } from './api'

export const DEFAULT_DEMO = 'calculator-fault'
const ORDER = ['calculator-fault', 'todo-approvals', 'ask-employee', 'notes-search', 'contact-book', 'inventory', 'reddit-replica', 'instagram', 'flagship', 'finish-it']

export interface DemoCard {
  name: string
  title: string
  app: string
  feature: string
  duration: string
  goal: string
  /** "4 modules, 4 tables, 41 endpoints, 10 pages, 62 functions (71% written by agents), 1,240 lines", or '' for an older recording. */
  stats: string
}

/** What the build is made of, as one line. */
export function statsLine(s: RecordingMeta['stats']): string {
  if (!s) return ''
  if (s.finish) return `${s.gaps ?? 0} gaps found, ${s.fixed ?? 0} closed in ${s.files ?? 0} file${s.files === 1 ? '' : 's'}, +${s.insertions ?? 0} −${s.deletions ?? 0} on its own branch`
  const parts = [s.modules > 1 ? `${s.modules} modules` : '1 module', `${s.tables} tables`, `${s.endpoints} endpoints`, `${s.pages} pages`]
  if (s.functions !== undefined) parts.push(`${s.functions} functions (${Math.round(100 * (s.agent_share_functions ?? 0))}% written by agents${s.functions_repair ? `, ${s.functions_repair} repaired from the contract` : ''})`, `${(s.lines ?? 0).toLocaleString('en-US')} lines`)
  return parts.join(', ')
}

/** "3 min 05 s", "45 s". */
export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`
}

/** Only the good recordings, the default first, then the shipped order, then anything else by name. */
export function orderDemos(recs: RecordingMeta[]): RecordingMeta[] {
  const rank = (n: string) => (ORDER.includes(n) ? ORDER.indexOf(n) : ORDER.length)
  return recs.filter((r) => r.ok).sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
}

export function pickDefault(recs: RecordingMeta[]): string {
  const good = orderDemos(recs)
  return (good.find((r) => r.name === DEFAULT_DEMO) ?? good[0])?.name ?? ''
}

export function card(r: RecordingMeta): DemoCard {
  const fallback = r.goal.replace(/^Build an? /i, '').split(':')[0]
  return {
    name: r.name,
    title: r.title || fallback.charAt(0).toUpperCase() + fallback.slice(1),
    app: r.app || '',
    feature: r.feature || '',
    duration: duration(r.seconds),
    goal: r.goal,
    stats: statsLine(r.stats),
  }
}
