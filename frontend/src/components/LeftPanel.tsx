import { useState } from 'react'
import type { ConfigInfo, RecordingMeta } from '../api'
import type { BoardArea, OfficeModel } from '../model'

import { card, orderDemos } from '../demos'
import { EXAMPLES, FAMOUS } from '../examples'

// The stack presets Q knows about. Only the ones the backend lists can be built today; the rest are shown as planned.
const PRESET_INFO: Record<string, { label: string; stack: string }> = {
  'fastapi-vanilla': { label: 'FastAPI + vanilla JS', stack: 'FastAPI · SQLite · plain HTML/CSS/JS · pytest' },
  'fastapi-react': { label: 'FastAPI + React', stack: 'FastAPI · SQLite · React/Vite' },
}

interface Props {
  model: OfficeModel
  busy: boolean
  demo: boolean
  hasProject: boolean
  recordings: RecordingMeta[]
  recording: string
  onRecording: (n: string) => void
  config: ConfigInfo | null
  preset: string
  onPreset: (p: string) => void
  fast: boolean
  onFast: (v: boolean) => void
  onStart: (goal: string) => void
}

const STATE_COLOR: Record<BoardArea['state'], string> = { waiting: '#3a4466', working: '#6ea8ff', done: '#4ade80', problem: '#f87171' }

function PresetPicker({ config, value, onChange, locked, shown }: { config: ConfigInfo | null; value: string; onChange: (p: string) => void; locked: boolean; shown: string }) {
  const available = Object.keys(config?.presets ?? { 'fastapi-vanilla': '' })
  const names = [...new Set([...available, ...Object.keys(PRESET_INFO)])]
  const current = locked && shown ? shown : value
  return (
    <div role="radiogroup" aria-label="Stack preset" className="flex flex-col gap-1.5">
      {names.map((n) => {
        const ok = available.includes(n)
        const on = current === n
        return (
          <div key={n} title={ok ? undefined : 'needs npm per build; planned'}>
          <button
            role="radio"
            aria-checked={on}
            disabled={!ok || locked}
            onClick={() => onChange(n)}
            title={ok ? (locked ? 'This replay was recorded with this preset' : PRESET_INFO[n]?.stack) : undefined}
            className="w-full rounded-lg border px-3 py-1.5 text-left transition-colors disabled:pointer-events-none disabled:cursor-default"
            style={{ borderColor: on ? 'var(--accent)' : 'var(--line)', background: on ? '#16213f' : '#0b0e17', opacity: ok || on ? 1 : 0.5 }}
          >
            <div className="flex items-center gap-2 text-[14px] font-bold">
              <span className="inline-block h-3 w-3 rounded-full border-2" style={{ borderColor: on ? 'var(--accent)' : '#3a4466', background: on ? 'var(--accent)' : 'transparent' }} />
              {PRESET_INFO[n]?.label ?? n}
              {!ok && <span className="ml-auto rounded bg-[#243055] px-1.5 py-[1px] text-[10px] font-bold tracking-wide text-[var(--muted)]">COMING SOON</span>}
              {ok && on && locked && <span className="ml-auto text-[10px] font-bold tracking-wide text-[var(--muted)]">FROM RECORDING</span>}
            </div>
            <div className="ml-5 text-[11.5px] leading-tight text-[var(--muted)]">{PRESET_INFO[n]?.stack ?? config?.presets[n]}</div>
          </button>
          </div>
        )
      })}
    </div>
  )
}

function Heading({ children }: { children: string }) {
  return <div className="mb-1 text-[11px] font-semibold tracking-wider text-[var(--muted)]">{children}</div>
}

export function LeftPanel({ model, busy, demo, hasProject, recordings, recording, onRecording, config, preset, onPreset, fast, onFast, onStart }: Props) {
  const [goal, setGoal] = useState(EXAMPLES[0].goal)
  const cards = orderDemos(recordings).map(card)
  const shown = demo ? (cards.find((c) => c.name === recording)?.goal ?? '') : goal
  const submit = () => shown.trim() && !busy && onStart(shown.trim())
  const byId = new Map(model.tasks.map((t) => [t.id, t]))
  const board = model.board
  return (
    <aside className="flex w-[318px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-[var(--line)] bg-[var(--panel)] p-3">
      <div>
        <Heading>GOAL</Heading>
        <textarea
          value={shown}
          readOnly={demo}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          rows={demo ? 4 : 2}
          placeholder="What should the team build?"
          className={`${demo ? "h-[92px]" : "h-[58px]"} w-full resize-none rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 py-1.5 text-[14.5px] leading-snug text-[var(--text)] outline-none focus:border-[var(--accent)]`}
        />
        {!demo && <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((x) => (
            <button key={x.label} onClick={() => setGoal(x.goal)} title={x.goal} className="rounded-full border border-[var(--line)] bg-[#0b0e17] px-2.5 py-0.5 text-[12px] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]">
              {x.label}
            </button>
          ))}
        </div>}
        {!demo && <div className="mt-2.5">
          <Heading>TRY A FAMOUS APP</Heading>
          <div className="flex flex-wrap gap-1.5">
            {FAMOUS.map((x) => (
              <button key={x.label} onClick={() => setGoal(x.goal)} title={`${x.goal}: a small version of it, with what is left out listed`} className="rounded-full border border-[var(--line)] bg-[#0b0e17] px-2.5 py-0.5 text-[12px] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]">
                {x.label}
              </button>
            ))}
          </div>
        </div>}
      </div>

      <div>
        <Heading>STACK PRESET</Heading>
        <PresetPicker config={config} value={preset} onChange={onPreset} locked={demo} shown={hasProject ? model.preset : ''} />
      </div>

      {!demo && (
        <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 py-2 text-[13px]" title="Skips the UI polish pass when the page already uses the UI kit, and allows one model review round per task (the automatic checks still run).">
          <input type="checkbox" checked={fast} onChange={(e) => onFast(e.target.checked)} className="mt-[3px]" />
          <span>
            <span className="font-bold">Fast live mode</span>
            <span className="block text-[11.5px] leading-tight text-[var(--muted)]">One review round per task, no polish when the page already uses the UI kit</span>
          </span>
        </label>
      )}

      {demo && (
        <div>
          <Heading>CHOOSE A RECORDED BUILD</Heading>
          {cards.length === 0 && <div className="text-[13px] text-[var(--muted)]">No recordings yet</div>}
          <div role="radiogroup" aria-label="Recorded build" className="flex flex-col gap-1.5">
            {cards.map((c) => {
              const on = c.name === recording
              return (
                <button
                  key={c.name}
                  role="radio"
                  aria-checked={on}
                  onClick={() => onRecording(c.name)}
                  className="w-full rounded-lg border px-3 py-1.5 text-left transition-colors"
                  style={{ borderColor: on ? 'var(--accent)' : 'var(--line)', background: on ? '#16213f' : '#0b0e17' }}
                >
                  <div className="flex items-center gap-2 text-[14px] font-bold">
                    <span className="inline-block h-3 w-3 shrink-0 rounded-full border-2" style={{ borderColor: on ? 'var(--accent)' : '#3a4466', background: on ? 'var(--accent)' : 'transparent' }} />
                    <span className="truncate">{c.title}</span>
                    <span className="ml-auto shrink-0 text-[12px] font-semibold text-[var(--muted)]">{c.duration}</span>
                  </div>
                  {c.stats && <div className="ml-5 mt-0.5 text-[11.5px] leading-snug text-[#9fb0d4]" data-testid="demo-stats">{c.stats}</div>}
                  <div className="ml-5 mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-[var(--muted)]">
                    {c.app && <span>{c.app}</span>}
                    {c.feature && <span className="rounded bg-[#243055] px-1.5 py-[1px] text-[10.5px] font-bold tracking-wide text-[#a9c1ff]">{c.feature.toUpperCase()}</span>}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <button
        onClick={submit}
        disabled={busy || !shown.trim() || (demo && !recording)}
        className="h-10 shrink-0 rounded-lg bg-gradient-to-b from-[#4f7dff] to-[#3563e6] text-[15px] font-bold text-white shadow-[0_0_20px_#4f7dff44] disabled:opacity-40"
      >
        {busy ? 'Starting…' : demo ? '▶ Play demo' : '⚙ Build it'}
      </button>

      <div>
        <Heading>PM BOARD</Heading>
        <div className="flex flex-col gap-1.5">
          {board.map((a) => {
            const pct = a.total ? Math.round((a.done / a.total) * 100) : 0
            return (
              <div key={a.name}>
                <div className="flex justify-between text-[12.5px] leading-tight">
                  <span className="font-semibold">{a.name}</span>
                  <span className="tabular-nums text-[var(--muted)]">{a.total ? `${a.done}/${a.total}` : '—'}</span>
                </div>
                <div className="mt-0.5 h-[5px] overflow-hidden rounded-full bg-[#1a2033]" role="progressbar" aria-label={a.name} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: STATE_COLOR[a.state] }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div>
        <Heading>{`TASKS (${model.tasks.length})`}</Heading>
        {model.tasks.length === 0 ? (
          <div className="text-[13px] text-[var(--muted)]">The Planner's task graph appears here.</div>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {model.tasks.map((t) => (
              <li key={t.id} className="rounded-md border border-[var(--line)] bg-[#0b0e17] px-2.5 py-1.5 text-[13px]">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-[var(--accent)]">{t.id}</span>
                  <span className="truncate">{t.title}</span>
                  <span className="ml-auto shrink-0 text-[11px] font-bold" style={{ color: { done: '#4ade80', running: '#6ea8ff', failed: '#f87171' }[t.status] ?? '#8a93aa' }}>
                    {t.status.toUpperCase()}
                  </span>
                </div>
                <div className="text-[12px] text-[var(--muted)]">
                  {model.name(t.owner)}
                  {t.depends_on.length > 0 && ` · after ${t.depends_on.map((d) => byId.get(d)?.id ?? d).join(', ')}`}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}
