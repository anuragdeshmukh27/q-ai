import { MODES } from '../model'
import type { Metrics } from '../api'

interface Props {
  title: string
  build: number
  percent: number
  hasProject: boolean
  active: number
  total: number
  mode: string
  onMode: (m: string) => void
  demo: boolean
  onDemo: (v: boolean) => void
  speed: number
  onSpeed: (s: number) => void
  metrics: Metrics | null
  appUrl: string
  connected: boolean
  done: boolean | null
}

function Gauge({ label, used, total }: { label: string; used?: number; total?: number }) {
  const pct = used !== undefined && total ? Math.min(100, (used / total) * 100) : 0
  const hot = pct > 85
  return (
    <div className="w-[128px]" title={used === undefined ? `${label} not available` : `${label}: ${used} of ${total} GB in use`}>
      <div className="flex justify-between text-[11px] font-semibold tracking-wide text-[var(--muted)]">
        <span>{label}</span>
        <span className="tabular-nums text-[var(--text)]">{used === undefined ? '—' : `${used.toFixed(1)} / ${total?.toFixed(0)} GB`}</span>
      </div>
      <div className="mt-1 h-[6px] overflow-hidden rounded-full bg-[#1a2033]">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: hot ? 'var(--bad)' : 'linear-gradient(90deg,#4f7dff,#7cc4ff)' }} />
      </div>
    </div>
  )
}

/** Which models the scheduler has in VRAM right now (and how fast they generate). Empty = every model is unloaded. */
function LoadedModels({ metrics }: { metrics: Metrics | null }) {
  if (!metrics?.loaded) return null
  const names = metrics.loaded.map((m) => m.name)
  const tps = metrics.tokens_per_s ?? 0
  return (
    <div className="w-[150px]" title={names.length ? `Loaded in VRAM: ${names.join(', ')}` : 'No model is loaded (the team is asleep)'}>
      <div className="text-[11px] font-semibold tracking-wide text-[var(--muted)]">LOADED MODEL</div>
      <div className="truncate text-[12.5px] font-bold" style={{ color: names.length ? 'var(--text)' : 'var(--muted)' }}>
        {names.length ? names.join(' + ') : 'none (asleep)'}
      </div>
      <div className="text-[11px] tabular-nums text-[var(--muted)]">{tps > 0 ? `${Math.round(tps)} tokens/s` : metrics.swaps ? `${metrics.swaps} swap${metrics.swaps === 1 ? '' : 's'}` : ' '}</div>
    </div>
  )
}

export function TopBar(p: Props) {
  const status = p.done === true ? 'Complete' : p.done === false ? 'Stopped' : p.hasProject ? (p.connected ? 'Building' : 'Reconnecting…') : 'Ready'
  const statusColor = p.done === true ? 'var(--good)' : p.done === false ? 'var(--bad)' : p.hasProject ? 'var(--accent)' : 'var(--muted)'
  return (
    <header className="flex h-[64px] shrink-0 items-center gap-5 border-b border-[var(--line)] bg-[var(--panel)] px-4">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-[#5b6cf0] to-[#3a8cff] text-lg font-black text-white shadow-[0_0_18px_#4f7dff55]">Q</div>
        <div className="leading-tight">
          <div className="max-w-[300px] truncate text-[15px] font-bold">{p.title || 'Q: the AI software company'}</div>
          <div className="flex items-center gap-2 text-[12px] text-[var(--muted)]">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: statusColor }} />
            {status}
            {p.build > 0 && <span>· build #{p.build}</span>}
          </div>
        </div>
      </div>

      <div className="w-[220px]">
        <div className="flex justify-between text-[11px] font-semibold tracking-wide text-[var(--muted)]">
          <span>PROGRESS</span>
          <span className="tabular-nums text-[var(--text)]">{p.percent}%</span>
        </div>
        <div className="mt-1 h-[8px] overflow-hidden rounded-full bg-[#1a2033]">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${p.percent}%`, background: p.done === true ? 'var(--good)' : 'linear-gradient(90deg,#4f7dff,#7cc4ff)' }} />
        </div>
      </div>

      <div className="text-[13px]">
        <div className="text-[11px] font-semibold tracking-wide text-[var(--muted)]">ACTIVE</div>
        <div className="font-bold tabular-nums">
          {p.active} <span className="font-normal text-[var(--muted)]">of {p.total}</span>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-5">
        <div className="flex flex-col gap-1">
          <div className="text-[11px] font-semibold tracking-wide text-[var(--muted)]">AUTONOMY</div>
          <div className="seg" role="group" aria-label="Autonomy mode">
            {MODES.map((m) => (
              <button key={m} aria-pressed={p.mode === m} onClick={() => p.onMode(m)}>
                {m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <div className="text-[11px] font-semibold tracking-wide text-[var(--muted)]">DEMO MODE</div>
          <div className="flex items-center gap-2">
            <button
              role="switch"
              aria-checked={p.demo}
              onClick={() => p.onDemo(!p.demo)}
              title="Replay a recorded build: no Ollama, no network"
              className="relative h-6 w-11 rounded-full border border-[var(--line)] transition-colors"
              style={{ background: p.demo ? '#2f5bd6' : '#1a2033' }}
            >
              <span className="absolute top-[2px] h-[18px] w-[18px] rounded-full bg-white transition-all" style={{ left: p.demo ? 23 : 2 }} />
            </button>
            {p.demo && (
              <div className="seg" role="group" aria-label="Replay speed">
                {[1, 2, 4].map((s) => (
                  <button key={s} aria-pressed={p.speed === s} onClick={() => p.onSpeed(s)}>
                    {s}×
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <LoadedModels metrics={p.metrics} />

        <div className="flex flex-col gap-2">
          <Gauge label="VRAM" used={p.metrics?.gpu?.used_gb} total={p.metrics?.gpu?.total_gb} />
          <Gauge label="RAM" used={p.metrics?.ram.used_gb} total={p.metrics?.ram.total_gb} />
        </div>

        {p.appUrl && (
          <a href={p.appUrl} target="_blank" rel="noreferrer" className="rounded-lg bg-[#2f9e5f] px-4 py-2 text-[14px] font-bold text-white no-underline shadow-[0_0_18px_#2f9e5f55] hover:bg-[#38b36e]">
            Open app ↗
          </a>
        )}
      </div>
    </header>
  )
}
