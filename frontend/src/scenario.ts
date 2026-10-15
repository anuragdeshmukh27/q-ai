// Scenarios (Simulation mode, step 4): the types the incident channel, the guide and the session timer share, and the small pure helpers around them.
// No React in here, so the tests can drive it.

/** A card of the scenario picker (GET /api/scenarios). The script, the facts and the guide stay on the server. */
export interface ScenarioInfo {
  id: string
  title: string
  summary: string
  role: string // the engineer the person plays
  minutes: number
  level: string
  channel: string // "#incident-opd"
  tests: number
  teammates: string[] // employee ids that can be asked in the channel
}

/** One criterion of the rubric with its judge and its rules in plain words ("How you are scored"). */
export interface ScoringCriterion {
  id: string
  name: string
  judge: string // employee id
  rules: { id: string; plain: string }[]
}

/** The scenario of the current session (from the `scenario_started` event). */
export interface ScenarioSession {
  id: string
  title: string
  role: string
  minutes: number
  channelId: string
  channelName: string
  teammates: string[] // employee ids that can be asked in the channel
  scoring: ScoringCriterion[] // the rules the debrief scores, in plain words: shown before the incident starts
  attempt: number // 1 for the first try, 2 for the next, ...
  startedAt: number // server clock, seconds since 1970
  endedAt: number | null // set when the session ends (fixed, stopped or failed): the timer stops
  kind?: 'learner' | 'demo' // a demo is an autoplay run: marked in its report, never part of the learner's attempts
  variant?: string // an autoplay run: "strong" or "weak"
  clock?: ClockAnchor | null // an autoplay run keeps its own (faster) session clock: the timer follows it instead of the wall clock
  finishedT?: number | null // the session time at which the session ended (fixes the timer of an autoplay run)
}

/** The session clock of an autoplay run at one moment: `t` session seconds when the browser's clock read `atMs`, running `rate` session seconds per real second. */
export interface ClockAnchor {
  t: number
  atMs: number
  rate: number
}

/** One message of the incident channel. `source`: who produced it (the learner, the script, the live model, or the scripted fallback when the model could not answer). */
export interface ChannelMsg {
  id: string
  from: string
  text: string
  source: 'learner' | 'scripted' | 'live' | 'fallback' | 'debrief'
  t: number // seconds since the session started
  to: string[] // the teammates a post of the learner is for
  replyTo: string
  hint: boolean // a reply to a question, or a pointer: counted as a hint
  bubble: string // a debrief post: the short version for the speech bubble
  voice: 'model' | 'template' | '' // a judge's line in the debrief: written by the 7b (and checked), or the template's
}

export interface GuideStepView {
  id: string
  title: string
  text: string
  state: 'done' | 'current' | 'todo'
}
/** Priya's guide as the last `guide_progress` event described it. */
export interface GuideView {
  task: string
  current: string | null
  done: number
  steps: GuideStepView[]
}

/** One run of a scenario: what the left panel remembers when the learner leaves the scenario view for the picker. Null when no scenario is loaded. */
export function scenarioRunKey(s: Pick<ScenarioSession, 'id' | 'attempt' | 'startedAt' | 'kind' | 'variant'> | null): string | null {
  return s ? [s.id, s.attempt, s.startedAt, s.kind ?? 'learner', s.variant ?? ''].join(':') : null
}

/** The left panel shows the scenario (not the live-build column) from the start of a scenario until the learner presses "Back to the scenarios" at its end. */
export function showsScenarioPanel(s: Parameters<typeof scenarioRunKey>[0], left: string | null): boolean {
  const key = scenarioRunKey(s)
  return key !== null && key !== left
}

/** A scenario run is over once its session has ended (or the build finished) and no script is still playing it. */
export function scenarioRunEnded(s: Pick<ScenarioSession, 'endedAt'>, finished: boolean, scriptActive: boolean): boolean {
  return (s.endedAt !== null || finished) && !scriptActive
}

/** 63 -> "01:03", 3725 -> "1:02:05". */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const two = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${two(m)}:${two(sec)}` : `${two(m)}:${two(sec)}`
}

/** Seconds on the session timer: it runs from the start to the end of the session, or to now while the session is going. */
export function sessionSeconds(s: Pick<ScenarioSession, 'startedAt' | 'endedAt' | 'clock' | 'finishedT'> | null, nowMs: number): number {
  if (!s) return 0
  if (s.clock) {
    if (s.endedAt !== null && s.finishedT != null) return s.finishedT
    return s.clock.t + (Math.max(0, nowMs - s.clock.atMs) / 1000) * s.clock.rate
  }
  return Math.max(0, (s.endedAt ?? nowMs / 1000) - s.startedAt)
}

/** Team messages that arrived after the last time the channel was looked at. */
export function unreadCount(channel: ChannelMsg[], seen: number): number {
  return channel.slice(Math.max(0, seen)).filter((m) => m.source !== 'learner').length
}

/** The teammates the message box can address, in the order the scenario lists them. */
export function recipients(teammates: string[], name: (id: string) => string): { id: string; name: string }[] {
  return teammates.map((id) => ({ id, name: name(id) }))
}

export const SOURCE_LABEL: Record<ChannelMsg['source'], string> = {
  learner: '',
  scripted: '',
  live: 'AI reply',
  fallback: 'scripted reply',
  debrief: 'debrief',
}

/** The small label of a debrief post in the channel: only the lines the 7b wrote carry one. */
export const voiceLabel = (m: Pick<ChannelMsg, 'voice'>): string => (m.voice === 'model' ? 'AI line' : '')

// -- the debrief (step 5): the report of an attempt, as GET /api/projects/{id}/report answers it ------------------------------------------------

export interface ReportRow {
  id: string
  criterion: string
  rule: string
  kind: 'strength' | 'gap'
  event: string // the session log entry the quote is from (E012)
  events: string[]
  t: number // session seconds of that entry
  source: string // "#incident-opd", "IDE · tests", ...
  quote: string
  note: string
  advice: string // a gap's tip for the next attempt
  verified: boolean
  worded_by: 'rule' // every sentence of a point is its rule's
}
export interface ReportCriterion {
  id: string
  name: string
  judge: string // employee id
  judge_name: string
  score: number
  max: number
  descriptor: string // what this score means in general
  summary: string // what this score is made of here: the rules that held and the ones that did not
  keep: string
  rows: string[]
}
export interface AttemptRecord {
  kind?: 'demo' // a demo run's record (the report of a demo lists only demos)
  variant?: string
  attempt: number
  total: number
  scores: Record<string, number>
  project: string
  finished_at: string
  elapsed: number
}
export interface SessionEntry {
  id: string
  t: number
  kind: string
  [field: string]: unknown
}
export interface DebriefReport {
  version: number
  scenario: string
  title: string
  project: string
  attempt: number
  kind?: 'learner' | 'demo' // an autoplay run is a demo: its report says so and it is no attempt of the learner's
  variant?: string
  total: number
  max: number
  elapsed: number
  minutes: number
  rubric: { id: string; version: number }
  criteria: ReportCriterion[]
  rows: ReportRow[]
  events: Record<string, SessionEntry>
  fairness: {
    points: number
    quoted: number
    matched: number
    dropped: { finding: string; text: string; reason: string }[] // unbacked claims: evidence points that failed the check (a clean run has none)
    ai_rejected: { finding: string; text: string; reason: string }[] // judge lines and coach paragraphs of the 7b that were not used, with why (finding: the criterion, or "coach")
    tests_rerun: { ok: boolean; passed: number; total: number } | null
    rubric: string
    voices: { judges: 'model' | 'mixed' | 'template'; coach: 'model' | 'template'; reason: string } // who wrote the judges' lines and the coach paragraph, and why not the 7b
  }
  focus: string[]
  coach: { text: string; source: 'model' | 'template' } // the overall paragraph: the 7b's when it passed the check, else a summary built from the points
  judge_lines: Record<string, { text: string; bubble: string; source: 'model' | 'template' }>
  attempts: AttemptRecord[]
  files: { md: string; json: string }
}
/** The debrief of this session: the meeting (judges, walking to the meeting room), then the report. */
export interface DebriefState {
  phase: 'meeting' | 'done' | 'failed'
  attempt: number
  judges: { id: string; name: string; criterion: string }[]
  report: DebriefReport | null
}

/** The attempt before this one in the history, if there is one. */
export function previousAttempt(report: DebriefReport): AttemptRecord | null {
  if (report.kind === 'demo') return null // a demo is compared with nothing: it is not an attempt of the learner's
  const before = report.attempts.filter((a) => a.attempt < report.attempt && a.kind !== 'demo')
  return before.length ? before[before.length - 1] : null
}

/** "+20 vs attempt 1" or "-5 vs attempt 1"; empty on the first attempt. */
export function deltaLabel(report: DebriefReport): string {
  const prev = previousAttempt(report)
  if (!prev) return ''
  const d = report.total - prev.total
  return `${d > 0 ? '+' : d < 0 ? '−' : '±'}${Math.abs(d)} vs attempt ${prev.attempt}`
}

/** The colour of a score bar: full marks good, half or more accent, below that warm, nothing red. */
export function scoreColor(score: number, max: number): string {
  const r = max ? score / max : 0
  return r >= 1 ? 'var(--good)' : r >= 0.75 ? '#7bd88f' : r >= 0.5 ? 'var(--warn)' : r > 0 ? '#fb923c' : 'var(--bad)'
}

/** The rows of one criterion, in the order the rules ran. */
export function rowsOf(report: DebriefReport, criterion: string): ReportRow[] {
  return report.rows.filter((r) => r.criterion === criterion)
}

/** What the log entry that a point quotes consists of, for the detail that opens when you click its timestamp: [label, value] pairs, the kind and time first. */
export function eventDetail(report: DebriefReport, id: string, name: (employee: string) => string = (x) => x): [string, string][] {
  const e = report.events[id]
  if (!e) return []
  const { id: _id, t, kind, ...rest } = e
  const out: [string, string][] = [['Entry', id], ['Time', formatClock(t)], ['Kind', kind.replace(/_/g, ' ')]]
  const who = new Set(['from', 'role', 'to']) // employee ids: shown as the names a learner knows
  for (const [k, v] of Object.entries(rest)) {
    if (v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)) continue
    const show = (x: unknown) => (who.has(k) && typeof x === 'string' ? name(x) : String(x))
    out.push([k.replace(/_/g, ' '), Array.isArray(v) ? v.map(show).join(', ') : typeof v === 'object' ? JSON.stringify(v) : show(v)])
  }
  return out
}

/** The label of a point's sentence: it is always its rule's. */
export const wordingLabel = (_r: Pick<ReportRow, 'worded_by'>): string => 'rule'

/** The label of the overall paragraph: "AI coach" when the 7b wrote it (and it passed the check), else "Summary". */
export const coachLabel = (c: { source: 'model' | 'template' }): string => (c.source === 'model' ? 'AI coach' : 'Summary')
