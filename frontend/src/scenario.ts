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

/** The scenario of the current session (from the `scenario_started` event). */
export interface ScenarioSession {
  id: string
  title: string
  role: string
  minutes: number
  channelId: string
  channelName: string
  teammates: string[] // employee ids that can be asked in the channel
  startedAt: number // server clock, seconds since 1970
  endedAt: number | null // set when the session ends (fixed, stopped or failed): the timer stops
}

/** One message of the incident channel. `source`: who produced it (the learner, the script, the live model, or the scripted fallback when the model could not answer). */
export interface ChannelMsg {
  id: string
  from: string
  text: string
  source: 'learner' | 'scripted' | 'live' | 'fallback'
  t: number // seconds since the session started
  to: string[] // the teammates a post of the learner is for
  replyTo: string
  hint: boolean // a reply to a question, or a pointer: counted as a hint
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
export function sessionSeconds(s: Pick<ScenarioSession, 'startedAt' | 'endedAt'> | null, nowMs: number): number {
  if (!s) return 0
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
}
