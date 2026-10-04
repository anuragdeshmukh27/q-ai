import { api, type BenchCell, type Leaderboard, type RouterRow } from '../api'
import { useState } from 'react'
import { BaselinePanel } from './BaselinePanel'
import { CostPanel } from './CostPanel'
import { Empty } from './Explorer'
import { useRefetch } from './hooks'

const ROLE_NAME: Record<string, string> = {
  architect: 'Architect',
  planner: 'Planner',
  backend: 'Backend',
  frontend: 'Frontend',
  database: 'Database',
  reviewer: 'Reviewer',
  qa: 'QA',
  integrator: 'Integrator',
}

const SOURCE_LABEL: Record<RouterRow['source'], string> = { pin: 'PINNED', score: 'BY SCORE', default: 'SAFE DEFAULT' }
const SOURCE_COLOR: Record<RouterRow['source'], string> = { pin: 'var(--warn)', score: 'var(--good)', default: 'var(--muted)' }

const tone = (rate: number) => (rate >= 0.8 ? 'var(--good)' : rate >= 0.5 ? 'var(--warn)' : 'var(--bad)')

function Cell({ c, chosen }: { c?: BenchCell; chosen: boolean }) {
  if (!c) return <td className="p-2 text-[var(--muted)]">—</td>
  const tip = c.tasks.map((t) => `${t.passed ? '✓' : '✗'} ${t.task} (${t.seconds}s, ${t.iterations} it)`).join('\n')
  return (
    <td className="p-2 align-top tabular-nums" title={tip} style={chosen ? { background: '#16213f', boxShadow: 'inset 0 0 0 1px var(--accent)' } : undefined}>
      <div className="text-[15px] font-bold" style={{ color: tone(c.pass_rate) }}>
        {chosen && <span title="The router uses this model for this role">★ </span>}
        {Math.round(c.pass_rate * 100)}%
        <span className="ml-1.5 text-[12px] font-normal text-[var(--muted)]">{c.passed}/{c.runs} passed</span>
      </div>
      <div className="text-[11.5px] leading-tight text-[var(--muted)]">
        {c.avg_seconds}s avg · {c.avg_iterations} it · {c.avg_tokens >= 1000 ? `${(c.avg_tokens / 1000).toFixed(1)}k` : c.avg_tokens} tokens{c.peak_vram_gb ? ` · ${c.peak_vram_gb} GB VRAM` : ''}
      </div>
    </td>
  )
}

type View = 'models' | 'compare' | 'authorship' | 'cost'
const VIEWS: [View, string][] = [['models', 'Models by role'], ['compare', 'Team vs single agent'], ['authorship', 'Who wrote the code'], ['cost', 'Cost of a build']]

export function LeaderboardTab() {
  const [view, setView] = useState<View>('models')
  return (
    <div className="h-full overflow-auto p-3">
      <div className="mb-3 flex gap-1" role="tablist">
        {VIEWS.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={view === id}
            onClick={() => setView(id)}
            className="rounded-md border px-3 py-1 text-[12.5px] font-semibold"
            style={{ borderColor: view === id ? 'var(--accent)' : 'var(--line)', background: view === id ? '#16213f' : 'transparent', color: view === id ? 'var(--text)' : 'var(--muted)' }}
          >
            {label}
          </button>
        ))}
      </div>
      {view === 'models' ? <ModelsView /> : view === 'cost' ? <CostPanel /> : <BaselinePanel view={view} />}
    </div>
  )
}

/** Role x model benchmark scores, and which model the router gives each employee (with the reason). */
function ModelsView() {
  const lb = useRefetch(() => api.leaderboard(), 'lb', 0, 0)
  if (!lb.data) return <Empty text={lb.error || 'Loading…'} />
  const d: Leaderboard = lb.data
  if (!d.runs) return <Empty text="No benchmark runs yet. Run scripts\benchmark.py to fill the leaderboard." />
  // Best overall first (the safe default wins ties), so the strongest model is the first column.
  const score = (m: string) => d.roles.reduce((a, r) => a + (d.matrix[r]?.[m]?.pass_rate ?? 0), 0)
  const models = [...d.models].sort((a, b) => score(b) - score(a) || (a === d.safe_default ? -1 : b === d.safe_default ? 1 : a.localeCompare(b)))
  const routed = new Map(d.router.map((r) => [r.agent, r]))
  const rows = d.roles.map((r) => ({ role: r, route: routed.get(r) }))
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[12.5px] text-[var(--muted)]">
        <span className="text-[14px] font-bold text-[var(--text)]">Benchmark leaderboard</span>
        <span>{d.runs} runs</span>
        {d.machine && <span>{d.machine}</span>}
        {d.generated && <span>recorded {d.generated}</span>}
        <span>
          Router: another model takes a role only if it beats the safe default ({d.safe_default}) by {Math.round(d.margin * 100)} points on at least {d.min_runs} runs.
        </span>
      </div>
      {d.note && <div className="mb-2 rounded-md border border-[var(--line)] bg-[#0b0e17] px-3 py-2 text-[12.5px] leading-snug">{d.note}</div>}
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-left text-[var(--muted)]">
            <th className="p-2">Role</th>
            {models.map((m) => (
              <th key={m} className="p-2">{m}</th>
            ))}
            <th className="p-2">Router picks</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ role, route }) => (
            <tr key={role} className="border-t border-[var(--line)]">
              <td className="p-2 align-top font-semibold">{ROLE_NAME[role] ?? role}</td>
              {models.map((m) => (
                <Cell key={m} c={d.matrix[role]?.[m]} chosen={route?.model === m} />
              ))}
              <td className="max-w-[320px] p-2 align-top">
                {route ? (
                  <>
                    <div className="font-bold">{route.model_name}</div>
                    <div className="text-[11px] font-bold tracking-wide" style={{ color: SOURCE_COLOR[route.source] }}>{SOURCE_LABEL[route.source]}</div>
                    <div className="text-[11.5px] leading-tight text-[var(--muted)]">{route.reason}</div>
                  </>
                ) : (
                  '—'
                )}
              </td>
            </tr>
          ))}
          {d.router.filter((r) => !d.roles.includes(r.agent)).map((r) => (
            <tr key={r.agent} className="border-t border-[var(--line)]">
              <td className="p-2 align-top font-semibold">{ROLE_NAME[r.agent] ?? r.agent}</td>
              <td className="p-2 text-[var(--muted)]" colSpan={models.length}>not benchmarked</td>
              <td className="max-w-[320px] p-2 align-top">
                <div className="font-bold">{r.model_name}</div>
                <div className="text-[11px] font-bold tracking-wide" style={{ color: SOURCE_COLOR[r.source] }}>{SOURCE_LABEL[r.source]}</div>
                <div className="text-[11.5px] leading-tight text-[var(--muted)]">{r.reason}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.notes && <div className="mt-2 text-[11.5px] text-[var(--muted)]">{d.notes}</div>}
      <div className="mt-1 text-[11.5px] text-[var(--muted)]">Hover a score to see each task. Reviewer scores are the model alone (the automatic checks are switched off); QA scores are the model alone (no traceback hint).</div>
    </div>
  )
}
