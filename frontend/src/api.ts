// Thin client for the Q backend (see backend/app/main.py). Errors are plain-language messages, never stack traces.
import type { AgentInfo, QEvent } from './model'

export class ApiError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  } catch {
    throw new ApiError('Cannot reach the Q backend. Is it running on port 8000?')
  }
  if (!r.ok) {
    let msg = `Request failed (${r.status})`
    try {
      const body = await r.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(msg)
  }
  return r.json() as Promise<T>
}

export interface RecordingMeta {
  name: string
  goal: string
  ok: boolean
  seconds: number
  events: number
  /** Card text for the Demo picker (absent in old recordings). */
  title?: string
  app?: string
  feature?: string
  /** What the build is made of (modules, tables, endpoints, pages, functions, lines, the agents' share); absent in older recordings. */
  stats?: { modules: number; tables: number; endpoints: number; pages: number; functions?: number; lines?: number; agent_share_functions?: number; agent_share_lines?: number; functions_repair?: number; finish?: boolean; gaps?: number; fixed?: number; files?: number; insertions?: number; deletions?: number }
}

export interface LoadedModel {
  id: string
  name: string
  vram_gb: number
}

/** What a build cost: tokens, GPU electricity here (measured, or estimated for old recordings) and the same tokens at the cloud prices of config/pricing.yaml. */
export interface CostReport {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  seconds: number
  electricity: { kwh: number; inr: number; avg_watts: number; measured: boolean }
  cloud: { id: string; name: string; usd: number; inr: number }[]
  inr_per_usd: number
  inr_per_kwh: number
}
export interface CostRow extends CostReport {
  name: string
  title: string
}

/** GPU/RAM gauges. `loaded`, `budget_gb` and `tokens_per_s` come from the scheduler (absent in old recordings). */
/** Finish my project: one thing the analyst found in an imported project. */
export interface GapInfo {
  id: string
  kind: string
  title: string
  file: string
  owner: string
  detail: string
  method: string
  path: string
  function: string
  line: number
  test: string
}

export interface Metrics {
  gpu: { name: string; used_gb: number; total_gb: number } | null
  ram: { used_gb: number; total_gb: number }
  loaded?: LoadedModel[]
  budget_gb?: number | null
  tokens_per_s?: number
  swaps?: number
}

export interface ProjectStatus {
  id: string
  goal: string
  kind: string
  state: string
  mode: string
  speed: number
  app: { running: boolean; url?: string }
}

export interface ModelInfo {
  id: string
  name: string
  provider: string
  capabilities: string[]
  available: boolean
  local: boolean
  vram_gb: number
}

export interface ConfigInfo {
  q_mode: string
  presets: Record<string, string>
}

export interface TreeFile {
  path: string
  size: number
}

export interface Commit {
  hash: string
  parents: string[]
  refs: string[]
  subject: string
  author: string
}

export interface BenchCell {
  runs: number
  passed: number
  pass_rate: number
  avg_iterations: number
  avg_seconds: number
  avg_tokens: number
  peak_vram_gb: number
  source: 'live' | 'shipped'
  tasks: { task: string; passed: boolean; iterations: number; seconds: number }[]
}

export interface RouterRow {
  agent: string
  model: string
  model_name: string
  source: 'pin' | 'score' | 'default'
  reason: string
}

export interface Leaderboard {
  runs: number
  roles: string[]
  models: string[]
  matrix: Record<string, Record<string, BenchCell>>
  router: RouterRow[]
  margin: number
  min_runs: number
  safe_default: string
  note?: string
  generated?: string
  machine?: string
  notes?: string
}

export interface Authorship {
  app?: { functions: number; functions_agent: number; functions_generated: number; functions_repair: number; lines: number; lines_agent: number; lines_generated: number; lines_repair: number }
  tests?: { files: number; lines: number; lines_agent: number; lines_generated: number }
  spec_by?: string
  contract_by?: string
  plan_by?: string
  repairs?: string[]
}

export interface BaselineRun {
  goal_key: string
  goal: string
  mode: 'team' | 'solo'
  rep: number
  ok: boolean
  seconds: number
  tests: string
  tests_passed: number
  tests_failed: number
  qa_bugs: number
  review_requests: number
  contract_repairs: number
  escalations?: number
  problems: string[]
  authorship: Authorship
}

export interface BaselineArm {
  runs: number
  passed: number
  pass_rate: number
  avg_seconds: number
  avg_seconds_passed: number
  tests_passed: number
  tests_failed: number
  test_pass_rate: number
  qa_bugs: number
  review_requests: number
  contract_repairs: number
  builds_with_repair: number
  functions: number
  functions_agent: number
  lines: number
  lines_agent: number
  agent_share_functions: number
  agent_share_lines: number
}

export interface BaselineReport {
  runs: BaselineRun[]
  goals: { key: string; goal: string; team: BaselineArm; solo: BaselineArm }[]
  overall: { team?: BaselineArm; solo?: BaselineArm }
  generated?: string
  machine?: string
  model?: string
  method?: string
  notes?: string
}

const post = (path: string, body: unknown) => call<Record<string, unknown>>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  config: () => call<ConfigInfo>('/api/config'),
  models: () => call<ModelInfo[]>('/api/models'),
  leaderboard: () => call<Leaderboard>('/api/leaderboard'),
  baseline: () => call<BaselineReport>('/api/baseline'),
  costs: () => call<{ rows: CostRow[] }>('/api/costs'),
  files: (id: string) => call<TreeFile[]>(`/api/projects/${id}/files`),
  file: (id: string, path: string) => call<{ path: string; content: string }>(`/api/projects/${id}/file?path=${encodeURIComponent(path)}`),
  commits: (id: string) => call<Commit[]>(`/api/projects/${id}/commits`),
  commit: (id: string, sha: string) => call<{ sha: string; merge: boolean; diff: string; truncated: boolean }>(`/api/projects/${id}/commits/${sha}`),
  decide: (id: string, aid: string, approve: boolean) => post(`/api/projects/${id}/approvals/${aid}`, { approve }),
  escalate: (id: string, action: 'retry' | 'replan' | 'stop', agent: string) => post(`/api/projects/${id}/escalation`, { action, agent }),
  override: (id: string, agent: string, model: string | null) => post(`/api/projects/${id}/agents/${agent}/model`, { model }),
  ask: (id: string, agent: string, text: string, asTask: boolean) => post(`/api/projects/${id}/agents/${agent}/ask`, { text, as_task: asTask }),
  startApp: (id: string) => post(`/api/projects/${id}/app`, {}),
  agents: () => call<AgentInfo[]>('/api/agents'),
  recordings: () => call<RecordingMeta[]>('/api/recordings'),
  metrics: () => call<Metrics>('/api/metrics'),
  projects: () => call<ProjectStatus[]>('/api/projects'),
  create: (body: { goal: string; mode: string; demo: boolean; recording?: string; speed?: number; preset?: string; fast_live?: boolean; import_from?: string; auto_fix?: boolean }) =>
    call<ProjectStatus>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  finishPick: (id: string, gaps: string[]) => call<{ selected: string[] }>(`/api/projects/${id}/finish`, { method: 'POST', body: JSON.stringify({ gaps }) }),
  setMode: (id: string, mode: string) => call<unknown>(`/api/projects/${id}/mode`, { method: 'POST', body: JSON.stringify({ mode }) }),
  setSpeed: (id: string, speed: number) => call<unknown>(`/api/projects/${id}/speed`, { method: 'POST', body: JSON.stringify({ speed }) }),
}

/** Event stream for one project. Reconnects with `after` so nothing is shown twice. */
export function openStream(id: string, onEvents: (events: QEvent[], catchUp: boolean) => void, onState: (open: boolean) => void): () => void {
  let ws: WebSocket | null = null
  let last = -1
  let closed = false
  let buffer: QEvent[] = []
  let timer: number | undefined

  const flush = () => {
    timer = undefined
    const batch = buffer
    buffer = []
    if (batch.length) onEvents(batch, batch.length > 40) // a big burst is history catching up: no walking animations for it
  }

  const connect = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws/${id}${last >= 0 ? `?after=${last}` : ''}`)
    ws.onopen = () => onState(true)
    ws.onmessage = (m) => {
      const e = JSON.parse(m.data) as QEvent
      if (e.seq <= last) return
      last = e.seq
      buffer.push(e)
      if (timer === undefined) timer = window.setTimeout(flush, 40)
    }
    ws.onclose = () => {
      onState(false)
      if (!closed) window.setTimeout(connect, 1000)
    }
  }
  connect()
  return () => {
    closed = true
    if (timer !== undefined) clearTimeout(timer)
    ws?.close()
  }
}
