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
}

export interface Metrics {
  gpu: { name: string; used_gb: number; total_gb: number } | null
  ram: { used_gb: number; total_gb: number }
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

export const api = {
  agents: () => call<AgentInfo[]>('/api/agents'),
  recordings: () => call<RecordingMeta[]>('/api/recordings'),
  metrics: () => call<Metrics>('/api/metrics'),
  projects: () => call<ProjectStatus[]>('/api/projects'),
  create: (body: { goal: string; mode: string; demo: boolean; recording?: string; speed?: number }) =>
    call<ProjectStatus>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
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
