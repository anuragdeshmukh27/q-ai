// Demo picker helpers: which recording plays by default, how a recording card reads, and in which order the cards appear.
import type { RecordingMeta } from './api'

export const DEFAULT_DEMO = 'calculator-fault'
const ORDER = ['calculator-fault', 'todo-approvals', 'expense-ask', 'notes-search', 'contact-book', 'inventory']

export interface DemoCard {
  name: string
  title: string
  app: string
  feature: string
  duration: string
  goal: string
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
  }
}
