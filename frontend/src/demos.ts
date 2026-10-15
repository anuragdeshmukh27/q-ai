// Demo picker helpers: which recording plays by default, how a recording card reads, and in which order the cards appear.
import type { RecordingMeta } from './api'

export const DEFAULT_DEMO = 'calculator-fault'
const ORDER = ['calculator-fault', 'todo-approvals', 'ask-employee', 'notes-search', 'contact-book', 'inventory', 'reddit-replica', 'instagram', 'flagship', 'finish-it', 'simulation-bookings-down-strong', 'simulation-bookings-down-weak', 'simulation-double-bookings-strong', 'simulation-double-bookings-weak', 'simulation-form-says-saved-strong', 'simulation-form-says-saved-weak']

export interface DemoCard {
  name: string
  title: string
  app: string
  feature: string
  duration: string
  goal: string
  /** A recorded simulation run (an autoplay of a scenario), not a build: the card carries a Simulation tag. */
  simulation: boolean
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

/** A recorded autoplay run of a simulation scenario (the rest are recorded builds). */
export const isSimulation = (r: RecordingMeta) => r.kind === 'scenario'

/** Only the good recordings, the default first, then the shipped order, then anything else by name. */
export function orderDemos(recs: RecordingMeta[]): RecordingMeta[] {
  const rank = (n: string) => (ORDER.includes(n) ? ORDER.indexOf(n) : ORDER.length)
  return recs.filter((r) => r.ok).sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
}

/** What the autonomy switch shows in Demo mode: the simulation recordings for Simulation, the recorded builds for every other mode. */
export function demosFor(recs: RecordingMeta[], mode: string): RecordingMeta[] {
  return orderDemos(recs).filter((r) => isSimulation(r) === (mode === 'simulation'))
}

/** The recording a mode starts on: calculator-fault among the builds, else the first one listed. With no mode, the first of every good recording. */
export function pickDefault(recs: RecordingMeta[], mode?: string): string {
  const good = mode === undefined ? orderDemos(recs) : demosFor(recs, mode)
  return (good.find((r) => r.name === DEFAULT_DEMO) ?? good[0])?.name ?? ''
}

/** Why a mode button does nothing in Demo mode ('' when it does something): there is no recording for it to show. */
export function modeIdleReason(recs: RecordingMeta[], mode: string): string {
  if (demosFor(recs, mode).length) return ''
  return mode === 'simulation' ? 'Demo mode: there are no recorded simulations to show' : 'Demo mode: there are no recorded builds to show'
}

/** What a mode button says about itself in Demo mode. */
export function demoModeTip(recs: RecordingMeta[], mode: string): string {
  const idle = modeIdleReason(recs, mode)
  if (idle) return idle
  return mode === 'simulation' ? 'Demo mode: show the recorded simulations' : 'Demo mode: show the recorded builds'
}

export function card(r: RecordingMeta): DemoCard {
  const fallback = r.goal.replace(/^Build an? /i, '').split(':')[0]
  return {
    name: r.name,
    title: r.title || fallback.charAt(0).toUpperCase() + fallback.slice(1),
    app: r.app || '',
    feature: r.feature || '',
    duration: duration(r.seconds),
    simulation: isSimulation(r),
    goal: r.goal,
    stats: statsLine(r.stats),
  }
}
