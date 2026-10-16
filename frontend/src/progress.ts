// My progress: the learner's real attempts across the scenarios, as GET /api/progress answers them (demo runs never count).
// Everything here is pure so the page can be tested without a browser.

export interface ProgressAttempt {
  attempt: number
  total: number
  max: number
  scores: Record<string, number>
  date: string // 2026-10-12T20:24:28 (local time of the server)
  elapsed: number // session seconds
  project: string
}

export interface ProgressScenario {
  id: string
  title: string
  minutes: number
  max: number
  attempts: ProgressAttempt[]
  count: number
  best_score: number | null
  best_time: number | null
  last_total: number | null
}

export type Trend = 'up' | 'down' | 'steady' | 'new' | 'none'

export interface ProgressSkill {
  id: string
  name: string
  max: number
  count: number
  latest: number | null
  average: number | null
  trend: Trend
}

/** A gap of the weakest skill, quoted as the saved report has it. */
export interface ProgressGap {
  scenario: string
  title: string
  attempt: number
  row: string
  t: number
  clock: string
  source: string
  quote: string
  note: string
  advice: string
}

export interface ProgressWeakest {
  skill: string
  name: string
  average: number
  latest: number
  max: number
  gap: ProgressGap | null
  reason: string // why there is no quote (the report is gone)
}

export interface ProgressNextStep {
  kind: 'retry' | 'new' | 'beat'
  scenario: string
  title: string
  skill: string
  reason: string
}

export interface Progress {
  version: number
  generated_at: string
  empty: boolean
  attempts_total: number
  scenarios: ProgressScenario[]
  skills: ProgressSkill[]
  weakest: ProgressWeakest | null
  next_step: ProgressNextStep | null
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "12 Oct 2026, 20:24" from the stored local timestamp; the text as it is when it has another shape. */
export function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}, ${m[4]}:${m[5]}` : iso
}

/** "3.1" for 3.14, "4" for 4: scores are 0 to 4, one decimal is enough. */
export function formatAverage(v: number | null): string {
  if (v === null) return '–'
  const r = Math.round(v * 10) / 10
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}

export const TREND: Record<Trend, { glyph: string; label: string; color: string }> = {
  up: { glyph: '▲', label: 'improving', color: 'var(--good)' },
  down: { glyph: '▼', label: 'slipping', color: 'var(--bad)' },
  steady: { glyph: '▬', label: 'steady', color: 'var(--muted)' },
  new: { glyph: '●', label: 'one attempt so far', color: 'var(--muted)' },
  none: { glyph: '–', label: 'no attempts', color: 'var(--muted)' },
}

/** The points of a score-over-attempts line inside a w x h box with `pad` around it; a single attempt sits in the middle. Values are 0..max, up is better. */
export function linePoints(values: number[], max: number, w: number, h: number, pad = 8): { x: number; y: number }[] {
  const inner = { w: w - pad * 2, h: h - pad * 2 }
  return values.map((v, i) => ({
    x: pad + (values.length === 1 ? inner.w / 2 : (inner.w * i) / (values.length - 1)),
    y: pad + inner.h * (1 - (max ? Math.min(Math.max(v, 0), max) / max : 0)),
  }))
}

export const linePath = (points: { x: number; y: number }[]): string => points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')

/** The confirmation before "Reset progress": nothing is cleared from `idle`; `confirm` is the only state the request can be sent from. */
export type ResetState = 'idle' | 'confirm' | 'busy'
export function resetStep(state: ResetState, action: 'ask' | 'cancel' | 'confirm' | 'done'): ResetState {
  if (action === 'ask') return state === 'idle' ? 'confirm' : state
  if (action === 'cancel') return state === 'confirm' ? 'idle' : state
  if (action === 'confirm') return state === 'confirm' ? 'busy' : state
  return 'idle'
}
export const canClear = (state: ResetState): boolean => state === 'confirm'

export const EXPORT_URL = (format: 'md' | 'json'): string => `/api/progress/export?format=${format}`
export const reportUrl = (scenario: string, attempt: number, format: 'json' | 'md' = 'json'): string =>
  `/api/progress/report/${encodeURIComponent(scenario)}/${attempt}?format=${format}`
