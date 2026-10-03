import { useState } from 'react'
import type { RecordingMeta } from '../api'

const EXAMPLES = ['Build a calculator with history', 'Build a todo app with priorities', 'Build an expense tracker']

interface Props {
  busy: boolean
  demo: boolean
  recordings: RecordingMeta[]
  recording: string
  onRecording: (n: string) => void
  onStart: (goal: string) => void
  ticker: string
  hasProject: boolean
}

export function GoalBar({ busy, demo, recordings, recording, onRecording, onStart, ticker, hasProject }: Props) {
  const [goal, setGoal] = useState(EXAMPLES[0])
  const good = recordings.filter((r) => r.ok)
  const submit = () => goal.trim() && !busy && onStart(goal.trim())
  return (
    <footer className="shrink-0 border-t border-[var(--line)] bg-[var(--panel)] px-4 py-3">
      <div className="mb-2 flex h-6 items-center gap-2 text-[14px] text-[var(--muted)]" aria-live="polite">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: ticker ? 'var(--accent)' : '#2a3350' }} />
        <span className="truncate">{ticker || (hasProject ? 'Waiting for the first event…' : 'Give the team a goal and watch them build it.')}</span>
      </div>
      <div className="flex items-center gap-3">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="What should the team build?"
          className="h-11 min-w-0 flex-1 rounded-lg border border-[var(--line)] bg-[#0b0e17] px-4 text-[16px] text-[var(--text)] outline-none focus:border-[var(--accent)]"
        />
        {demo && (
          <select
            value={recording}
            onChange={(e) => onRecording(e.target.value)}
            title="Recording to replay"
            className="h-11 max-w-[240px] rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 text-[14px] text-[var(--text)]"
          >
            {good.length === 0 && <option value="">No recordings yet</option>}
            {good.map((r) => (
              <option key={r.name} value={r.name}>
                ▶ {r.name} ({Math.round(r.seconds)} s)
              </option>
            ))}
          </select>
        )}
        <button
          onClick={submit}
          disabled={busy || !goal.trim() || (demo && !recording)}
          className="h-11 rounded-lg bg-gradient-to-b from-[#4f7dff] to-[#3563e6] px-6 text-[15px] font-bold text-white shadow-[0_0_20px_#4f7dff44] disabled:opacity-40"
        >
          {busy ? 'Starting…' : demo ? '▶ Play demo' : '⚙ Build it'}
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 [@media(max-height:820px)]:hidden">
        {EXAMPLES.map((x) => (
          <button key={x} onClick={() => setGoal(x)} className="rounded-full border border-[var(--line)] bg-[#0b0e17] px-3 py-1 text-[13px] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]">
            {x}
          </button>
        ))}
      </div>
    </footer>
  )
}
