import { api } from '../api'
import { Empty } from './Explorer'
import { useRefetch } from './hooks'

/** Role x model pass rates. The benchmark runner and the pre-recorded results arrive in P7; this reads whatever the backend has. */
export function LeaderboardTab() {
  const lb = useRefetch(() => api.leaderboard(), 'lb', 0, 0)
  if (!lb.data) return <Empty text={lb.error || 'Loading…'} />
  if (!lb.data.runs) return <Empty text="No benchmark runs yet. The benchmark suite and its pre-recorded results arrive with the model router." />
  return (
    <div className="h-full overflow-auto p-3">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-left text-[var(--muted)]">
            <th className="p-2">Role</th>
            {lb.data.models.map((m) => (
              <th key={m} className="p-2">{m}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lb.data.roles.map((r) => (
            <tr key={r} className="border-t border-[var(--line)]">
              <td className="p-2 font-semibold">{r}</td>
              {lb.data!.models.map((m) => {
                const c = lb.data!.matrix[r]?.[m]
                return (
                  <td key={m} className="p-2 tabular-nums" style={{ color: c ? (c.pass_rate >= 0.8 ? 'var(--good)' : c.pass_rate >= 0.5 ? 'var(--warn)' : 'var(--bad)') : 'var(--muted)' }}>
                    {c ? `${Math.round(c.pass_rate * 100)}% · ${c.avg_seconds}s · ${c.runs} runs` : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
